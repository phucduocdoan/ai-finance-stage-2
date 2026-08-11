"""Generate the pandas_query for a question from its retrieved tables.

Orchestration only: load tables → render → call planner LLM → repair chain
→ compile → execute. All repair/validate logic lives in repairs.py and
validators.py; all prompt strings live in prompts.py.
"""

from __future__ import annotations

import asyncio
import json
import re

from langchain_core.messages import HumanMessage
import pandas as pd

from finance_qa.core.http import run_sync
from finance_qa.core.llm import get_chat_model
from finance_qa.modules.codegen.table_profile import profile_table
from finance_qa.modules.tools.python_exec import (
    query_names,
    run_query,
)
from finance_qa.modules.data.table_store import (
    load_frame,
    submission_csv_name,
)
from finance_qa.core.paths import TABLE_METADATA_PATH
from finance_qa.modules.codegen.ir import OperationPlan, compile_plan, validate_plan
from finance_qa.modules.codegen.prompts import PLAN_PROMPT, PLAN_REPAIR
from finance_qa.modules.codegen.repl import arepl_generate
from finance_qa.modules.codegen.repairs import (
    binding_alignment_errors,
    prune_unused_bindings,
    repair_binding_alignment,
    repair_binding_column,
    repair_formula_binding_names,
    repair_non_numeric_bindings,
    repair_plan_order,
    repair_plan_output_unit,
    repair_prior_year_coverage,
    repair_repeated_select_answers,
    repair_select_answer_periods,
    repair_select_answer_years,
)
from finance_qa.modules.codegen.validators import (
    binding_concept_errors,
    plan_contract_errors,
    plan_order_errors,
    semantic_errors,
)
from finance_qa.modules.rag.judge import acall_llm

META_PATH = TABLE_METADATA_PATH

MAX_REPAIRS = 2

CTX_TOKENS = 32_768
THINK_TOKENS = 8_192
CHARS_PER_TOKEN = 2.7
ROW_LADDER = (None, 60, 40, 25, 15, 8)

_INDICATOR_PROMPT = """Trích xuất tên chỉ tiêu tài chính cần tra cứu từ câu hỏi sau.
Chỉ in tên chỉ tiêu ngắn gọn (2-6 từ tiếng Việt), không có tên công ty, mã cổ phiếu, năm, đơn vị đo.
Ví dụ đầu ra: "lợi nhuận sau thuế", "doanh thu thuần", "tổng tài sản", "vay và nợ thuê tài chính ngắn hạn".
Nếu câu hỏi hỏi nhiều chỉ tiêu (tăng trưởng, tỷ lệ), chỉ liệt kê các chỉ tiêu cần tra, cách nhau dấu phẩy.

Câu hỏi: {question}

Chỉ in tên chỉ tiêu, không giải thích."""


async def arewrite_to_indicator(question: str) -> str:
    """Extract the core financial indicator(s) from a question using the local LLM.

    Returns a short phrase like "lợi nhuận sau thuế" for use in row alignment,
    replacing the stopword-based _tokens(question) fallback.
    """
    try:
        raw = await acall_llm(_INDICATOR_PROMPT.format(question=question), thinking=False, max_tokens=64)
        raw = raw.split("</think>")[-1].strip().strip('"').strip("'")
        return raw.splitlines()[0].strip().casefold()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

_TABLE_META: dict[str, dict] | None = None


def _table_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with META_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            key = f"{r['report_id']}|{r['table_pos']}"
            meta[key] = {
                "caption": " / ".join(x for x in (r.get("section_title"), r.get("note_title")) if x),
                "period_cols": set(r.get("period_columns_raw") or []),
                "statement_type": r.get("statement_type", "unknown"),
            }
    return meta


def _get_meta(table_id: str) -> dict:
    global _TABLE_META
    if _TABLE_META is None:
        _TABLE_META = _table_meta()
    return _TABLE_META.get(table_id, {"caption": "", "period_cols": set(), "statement_type": "unknown"})


def caption(table_id: str) -> str:
    return _get_meta(table_id)["caption"]


def render_tables(
    frames: dict[str, pd.DataFrame], table_ids: dict[str, str], rows: int | None
) -> str:
    """Full-table rendering with structural annotations in the header.

    Adds [main_report]/[note] tag and value-col year hints above the full DataFrame
    body. The model needs to see actual row values to identify the right indicator row.
    """
    blocks = []
    for var, df in frames.items():
        meta = _get_meta(table_ids[var])
        profile = profile_table(df, table_ids[var], meta)
        title = meta["caption"]

        kind_tag = f" [{profile.table_kind}]" if profile.table_kind != "unknown" else ""
        header = f"### {var}  ({table_ids[var]}){'  — ' + title if title else ''}{kind_tag}"

        ann: list[str] = []
        if profile.value_cols:
            val_parts = []
            for c in profile.value_cols:
                yr = profile.year_map.get(str(c))
                raw_dtype = df[c].dtype.name if c in df.columns else "?"
                dtype_tag = "float" if "float" in raw_dtype else ("int" if "int" in raw_dtype else "str")
                hints = ([f"≈{yr}"] if yr else []) + [dtype_tag]
                val_parts.append(f"'{c}' ({', '.join(hints)})")
            ann.append("Cột giá trị: " + " | ".join(val_parts))
        elif profile.year_map:
            report_years = sorted(set(profile.year_map.values()))
            ann.append("report_year: " + ", ".join(str(y) for y in report_years))
        shown = df if rows is None else df.head(rows)
        note = "" if rows is None or len(df) <= rows else f"\n  ... còn {len(df) - rows} dòng"

        blocks.append(header + "\n" + "\n".join(ann) + "\n" + shown.to_string() + note)
    return "\n\n".join(blocks)


async def abuild_plan_prompt(question: str, frames, table_ids) -> str:
    budget = int((CTX_TOKENS - THINK_TOKENS) * CHARS_PER_TOKEN * 0.95)
    indicator = await arewrite_to_indicator(question)
    annotated = question + (f"\nChỉ tiêu tài chính cần tra: {indicator}" if indicator else "")
    for rows in ROW_LADDER:
        prompt = PLAN_PROMPT.format(question=annotated, tables=render_tables(frames, table_ids, rows))
        if len(prompt) <= budget:
            return prompt
    return prompt


def build_plan_prompt(question: str, frames, table_ids) -> str:
    """Sync `abuild_plan_prompt`, for the offline prompt probes."""
    return run_sync(abuild_plan_prompt(question, frames, table_ids))


def _evidence(names: dict[str, str], query: str) -> list[dict[str, str]]:
    used = query_names(query)
    return [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
        if var in used
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _column_hint(errors: list[str], frames: dict[str, pd.DataFrame]) -> str:
    """Inject actual column names for any variable with a column-not-found error."""
    seen: dict[str, str] = {}
    for err in errors:
        m = re.search(r"column không tồn tại trong (df\w+)", err)
        if m:
            var = m.group(1)
            if var in frames and var not in seen:
                cols = " | ".join(f"'{c}'" for c in frames[var].columns)
                seen[var] = cols
    if not seen:
        return ""
    lines = ["\nCÁC CỘT THỰC TẾ (dùng tên chính xác để sửa lỗi column không tồn tại):"]
    for var, cols in seen.items():
        lines.append(f"  {var}: {cols}")
    return "\n".join(lines)


async def _arequest_plan(prompt: str, *, thinking: bool, max_tokens: int) -> dict:
    """Ask the model for a typed planner IR and return the historical dict shape."""
    result = await get_chat_model(
        thinking=thinking,
        max_tokens=max_tokens,
    ).with_structured_output(OperationPlan).ainvoke([HumanMessage(content=prompt)])
    if not isinstance(result, OperationPlan):
        result = OperationPlan.model_validate(result)
    return result.to_plan_dict()


async def agenerate(
    question: str,
    table_ids: list[str],
    thinking: bool = False,
    use_planner: bool = True,
    fallback: bool = True,
) -> dict:
    """question + picked tables -> {pandas_query, answer, evidence, error}."""
    def _pos(tid: str) -> int:
        try:
            return int(tid.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            return 999

    table_ids = sorted(table_ids, key=_pos)
    names = {f"df{i}": tid for i, tid in enumerate(table_ids, 1)}
    # Parquet reads: disk IO plus pandas parsing, so off the loop rather than on it.
    frames = await asyncio.to_thread(
        lambda: {var: load_frame(tid) for var, tid in names.items()}
    )

    # --- Skip planner if disabled ---
    if not use_planner:
        return await arepl_generate(question, frames, names)

    # --- Planner path ---
    plan_base = await abuild_plan_prompt(question, frames, names)
    plan_prompt = plan_base
    plan_error = ""
    last_plan = None
    plan_attempts = 0
    for attempt in range(MAX_REPAIRS + 1):
        plan_attempts += 1
        plan_thinking = thinking or attempt == 1
        plan = None
        adjustments = []
        try:
            plan = await _arequest_plan(
                plan_prompt,
                thinking=plan_thinking,
                max_tokens=8192 if plan_thinking else 4096,
            )
        except Exception as exc:  # noqa: BLE001
            errors = [f"LLM không trả về structured plan: {type(exc).__name__}: {exc}"]
        last_plan = plan
        if plan is not None:
            for repair_fn, args in [
                (repair_formula_binding_names, (plan,)),
                (repair_binding_column, (plan, frames)),
                (repair_repeated_select_answers, (plan,)),
                (repair_select_answer_years, (plan,)),
                (repair_select_answer_periods, (plan, names)),
                (prune_unused_bindings, (plan,)),
                (repair_non_numeric_bindings, (plan, frames, names)),
            ]:
                plan, changes = repair_fn(*args)
                adjustments.extend(changes)

            errors = validate_plan(plan, frames)
            if not errors:
                plan, changes = repair_prior_year_coverage(question, plan, frames)
                adjustments.extend(changes)
                errors = validate_plan(plan, frames)
            if not errors:
                plan, changes = repair_binding_alignment(question, plan, frames)
                adjustments.extend(changes)
                errors = binding_alignment_errors(question, plan, frames)
            if not errors:
                errors = binding_concept_errors(question, plan, frames)
            if not errors:
                plan, change = repair_plan_output_unit(question, plan)
                if change:
                    adjustments.append(change)
            if not errors:
                plan, change = repair_plan_order(question, plan, names)
                if change:
                    adjustments.append(change)
                errors = plan_order_errors(question, plan, names)
            if not errors:
                errors = plan_contract_errors(question, plan, names)
            if not errors:
                try:
                    query = compile_plan(plan, frames)
                    answer = run_query(query, frames)
                    errors = semantic_errors(question, query, frames)
                except Exception as exc:  # noqa: BLE001
                    errors = [f"{type(exc).__name__}: {exc}"]

        if not errors:
            return {
                "pandas_query": query,
                "answer": answer,
                "evidence": _evidence(names, query),
                "error": "",
                "attempts": plan_attempts,
                "verified": True,
                "planner": True,
                "plan": plan,
                "plan_adjustments": adjustments,
            }
        plan_error = "; ".join(errors)
        plan_prompt = plan_base + "\n\n" + PLAN_REPAIR.format(
            previous_plan=(
                json.dumps(plan, ensure_ascii=False, indent=2)
                if isinstance(plan, dict)
                else "(không nhận được structured plan)"
            ),
            errors="\n".join(f"- {error}" for error in errors),
        ) + _column_hint(errors, frames)

    # --- Fallback: REPL exploration loop (skippable to isolate the planner) ---
    if not fallback:
        return {
            "pandas_query": "",
            "answer": None,
            "evidence": [],
            "error": plan_error or "planner failed",
            "attempts": plan_attempts,
            "planner": True,
            "plan": last_plan,
            "plan_adjustments": [],
        }
    return await arepl_generate(question, frames, names, plan_error, last_plan)


def generate(
    question: str,
    table_ids: list[str],
    thinking: bool = False,
    use_planner: bool = True,
    fallback: bool = True,
) -> dict:
    """Sync `agenerate`, for the offline evaluators and the planner experiments."""
    return run_sync(
        agenerate(
            question,
            table_ids,
            thinking=thinking,
            use_planner=use_planner,
            fallback=fallback,
        )
    )
