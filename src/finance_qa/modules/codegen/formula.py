"""Formula solver over canonical financial data.

`_collect_canonical()` already pulls the full dataset into memory
({ticker: {year: {metric: value}}}). The preferred path asks the model for a
Pydantic `CanonicalPlan`, validates it, then executes all arithmetic and data
access deterministically in Python.

Falls back to a one-shot formula reasoner, then to repl (`solver="formula_skip"`),
when canonical metrics cannot represent the question or the model cannot produce
a valid plan/numeric answer.
"""
from __future__ import annotations

import os
import re
from typing import Any
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from finance_qa.modules.codegen.fact_plan import aplan_and_execute_fact_plan
from finance_qa.modules.codegen.prompts import EXTRACT_PROMPT, FORMULA_PROMPT, FORMULA_SYSTEM
from finance_qa.modules.tools.metrics import (
    execute_canonical_plan,
    execute_nested_selection,
    metric_catalog,
    pandas_expr_for_metric,
    planner_metric_ids,
    ratios_for,
)
from finance_qa.core.http import run_sync
from finance_qa.core.llm import get_chat_model
from finance_qa.modules.data.canonical import canonical_frame, _get_table_meta
from finance_qa.modules.data.preprocessing.questions import detect_unit
from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.modules.tools.python_exec import query_names

_TRACE = os.environ.get("FORMULA_TRACE", "") not in ("", "0")


# ── Canonical data collection ─────────────────────────────────────────────────

_CANONICAL_STMTS = {"balance_sheet", "income_statement", "cash_flow"}


def _collect_canonical(
    frames: dict[str, Any],
    names: dict[str, str],
    provenance: dict[tuple[str, str, str], tuple[str, int, int]] | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Return {ticker: {year_str: {metric_id: float}}} from all loaded frames.

    When `provenance` is passed, it is filled with (ticker, year, metric) ->
    (frame variable, row position, column position) for every value kept, which
    is what lets the solver emit a runnable pandas query over those cells.
    """
    data: dict[str, dict[str, dict[str, float]]] = {}
    priority: dict[tuple[str, str, str], int] = {}
    for var, table_id in names.items():
        df = frames.get(var)
        if df is None:
            continue
        meta = _get_table_meta(table_id)
        if not meta.get("has_ma_so_column"):
            continue
        stmt = meta.get("statement_type", "")
        if stmt not in _CANONICAL_STMTS:
            continue
        ticker = meta.get("ticker") or "unknown"
        report_match = re.search(r"financial_statements_(20\d{2})", table_id)
        report_year = int(report_match.group(1)) if report_match else None
        frame_prov: dict[tuple[str, int], tuple[int, int]] = {}
        canon = canonical_frame(df, table_id, stmt, frame_prov)
        for metric_id, yr_vals in canon.items():
            for yr_int, val in yr_vals.items():
                yr = str(yr_int)
                key = (ticker, yr, metric_id)
                # Prefer the current column from that year's own report over the
                # same year repeated as a comparative prior column in the next
                # report. Restated prior-year figures can be useful elsewhere,
                # but for "năm 2021" questions the primary source is the 2021
                # current-year statement.
                rank = 2 if report_year == yr_int else 1
                if rank >= priority.get(key, 0):
                    data.setdefault(ticker, {}).setdefault(yr, {})[metric_id] = val
                    priority[key] = rank
                    cell = frame_prov.get((metric_id, yr_int))
                    if provenance is not None and cell is not None:
                        provenance[key] = (var, cell[0], cell[1])
    return data


def _execute_nested_selection(
    data: dict[str, dict[str, dict[str, float]]],
    years: list[int] | None,
    rank_metric: str,
    direction: str,
    answer_metric: str,
) -> tuple[float, str] | None:
    """Compatibility wrapper for older tests/scripts."""
    return execute_nested_selection(data, years, rank_metric, direction, answer_metric)


MetricId = Literal[*planner_metric_ids()]
FilterOp = Literal[">", ">=", "<", "<=", "==", "below_median", "above_median"]
Direction = Literal["max", "min"]
YearOffsetReference = Literal["none", "next_year", "previous_year"]


class CanonicalUniverse(BaseModel):
    """Ticker/year universe for the canonical financial query."""

    tickers: list[str] = Field(default_factory=list, description="Stock tickers to consider.")
    years: list[int] = Field(default_factory=list, description="Fiscal years to consider.")


class CanonicalFilter(BaseModel):
    """A row filter applied before selection."""

    metric: MetricId = Field(description="Canonical metric used for filtering.")
    op: FilterOp = Field(description="Comparison operator or median-relative operator.")
    value: float | None = Field(default=None, description="Threshold for numeric comparison operators.")


class CanonicalSelect(BaseModel):
    """Select the row with the maximum/minimum value of a metric."""

    metric: MetricId = Field(description="Metric used to rank candidate rows.")
    direction: Direction = Field(description="Whether to choose the maximum or minimum metric value.")
    offset_years: int = Field(default=0, description="Use 1 only for 'the year after', -1 only for 'the year before'.")


class CanonicalAnswer(BaseModel):
    """Metric and unit requested as the final answer."""

    metric: MetricId = Field(description="Canonical metric to return from the selected row.")
    unit: str = Field(default="", description="Requested output unit from the question, e.g. 'lần', 'phần trăm', 'tỷ đồng'.")


class CanonicalPlan(BaseModel):
    """Structured canonical-finance query plan inferred from the question."""

    unsupported: bool = Field(default=False, description="True only when canonical metrics cannot represent the question.")
    median_filter_mentioned: bool = Field(default=False, description="True only when the question explicitly mentions median/trung vị.")
    year_offset_reference: YearOffsetReference = Field(default="none", description="Whether the question asks for the year after or before the selected year.")
    universe: CanonicalUniverse = Field(default_factory=CanonicalUniverse)
    filters: list[CanonicalFilter] = Field(default_factory=list)
    select: CanonicalSelect | None = None
    answer: CanonicalAnswer | None = None

    @model_validator(mode="after")
    def validate_consistency(self):
        if self.unsupported:
            return self
        if self.answer is None:
            raise ValueError("supported canonical plans must include answer")
        for filt in self.filters:
            if filt.op in {"below_median", "above_median"}:
                if not self.median_filter_mentioned:
                    raise ValueError("median-relative filters require median_filter_mentioned=true")
            elif filt.value is None:
                raise ValueError(f"filter op {filt.op!r} requires a numeric value")
        if self.select is None:
            if self.year_offset_reference != "none":
                raise ValueError("year_offset_reference requires a select step")
            return self
        offset = self.select.offset_years
        if abs(offset) > 1:
            raise ValueError("offset_years only supports -1, 0, or 1")
        if offset > 0 and self.year_offset_reference != "next_year":
            raise ValueError("positive offset_years requires year_offset_reference='next_year'")
        if offset < 0 and self.year_offset_reference != "previous_year":
            raise ValueError("negative offset_years requires year_offset_reference='previous_year'")
        if offset == 0 and self.year_offset_reference != "none":
            raise ValueError("zero offset_years requires year_offset_reference='none'")
        return self


def _canonical_plan_prompt(question: str) -> str:
    """Prompt for the structured canonical planner."""
    return f"""\
Câu hỏi: {question}

Hãy trả về CanonicalPlan cho phép Python execute sau trên dữ liệu canonical.
Nhiệm vụ của bạn CHỈ là lập plan, không cần biết số cụ thể. Nếu các chỉ tiêu trong
câu hỏi map được vào metric catalog thì phải đặt unsupported=false. Chỉ đặt
unsupported=true khi câu hỏi cần khoản mục không có metric tương ứng trong catalog.

Metric catalog:
{metric_catalog()}

Plan schema:
{{
  "median_filter_mentioned": true,
  "year_offset_reference": "none",
  "universe": {{"tickers": ["HPG"], "years": [2020, 2021]}},
  "filters": [
    {{"metric": "net_profit", "op": ">", "value": 0}},
    {{"metric": "gross_margin", "op": "below_median"}}
  ],
  "select": {{"metric": "quick_ratio", "direction": "min", "offset_years": 1}},
  "answer": {{"metric": "icr", "unit": "lần"}}
}}

Rules:
- Chỉ dùng metric id đúng trong catalog: {", ".join(planner_metric_ids())}.
- D/E = de_ratio; khả năng thanh toán lãi vay = icr; thanh toán hiện hành = current_ratio.
- "biên lợi nhuận gộp" = gross_margin, KHÔNG phải gross_profit.
- "dòng tiền hoạt động trên nợ ngắn hạn" = cfo_to_short_term_debt.
- "CFO trên LNST" = cfo_to_net_profit.
- "LNST chưa chuyển hóa thành CFO" / "phần LNST chưa chuyển hóa thành CFO" = net_profit_minus_cfo.
- "LNST" mặc định dùng net_profit; chỉ dùng net_profit_attributable_to_owners khi câu hỏi nói rõ
  "thuộc cổ đông công ty mẹ".
- Nếu câu hỏi nói "năm sau/năm tiếp theo/năm kế tiếp/cuối năm kế tiếp" thì
  year_offset_reference="next_year" và offset_years=1.
- Nếu câu hỏi nói "năm trước" thì year_offset_reference="previous_year" và offset_years=-1.
- Nếu không nói năm sau/năm trước thì year_offset_reference="none" và offset_years=0.
- "chỉ tính các năm có LNST > 0" dùng filter net_profit > 0.
- "trong số các công ty/năm có CFO dương" chỉ dùng filter net_cash_operating > 0.
- "thấp hơn trung vị" dùng op below_median; "cao hơn trung vị" dùng op above_median.
- Chỉ dùng below_median/above_median khi câu hỏi thật sự nói "trung vị"; khi đó median_filter_mentioned=true.
- Không thêm filter median nếu câu hỏi không có chữ "trung vị"/"median".
- answer.unit lấy từ câu hỏi: tỷ, triệu, nghìn tỷ, phần trăm, lần, hoặc bỏ trống.
- Không tự tính số trong JSON; chỉ mô tả phép chọn/lọc/trả lời.

Ví dụ mapping:
- "A vào năm sau năm có B thấp nhất" -> select.metric=B, direction=min,
  offset_years=1, answer.metric=A.
- "xét các năm có A thấp hơn trung vị, B tại năm có C cao nhất là bao nhiêu"
  -> filter A below_median, select C max, answer B, KHÔNG offset_years.
- Với cấu trúc "vào/tại/ở năm có X cao nhất/thấp nhất, Y là bao nhiêu":
  X là select.metric; Y là answer.metric.
- Ví dụ: "công ty có biên lợi nhuận gộp cao nhất trong số các công ty có CFO dương
  có ICR là bao nhiêu" -> median_filter_mentioned=false; filters=[net_cash_operating > 0];
  select.metric=gross_margin; answer.metric=icr."""


async def ainfer_canonical_plan(question: str) -> CanonicalPlan | None:
    """Infer the structured canonical plan without executing it."""
    try:
        plan_obj = await get_chat_model(thinking=False, max_tokens=768).with_structured_output(
            CanonicalPlan
        ).ainvoke([HumanMessage(_canonical_plan_prompt(question))])
    except Exception as e:
        if _TRACE:
            print(f"[formula] canonical plan error: {e}")
        return None

    if not isinstance(plan_obj, CanonicalPlan):
        return None
    if _TRACE:
        print(f"[formula] canonical plan: {plan_obj.model_dump(exclude_none=True)}")
    return plan_obj


def infer_canonical_plan(question: str) -> CanonicalPlan | None:
    """Sync `ainfer_canonical_plan`, for the offline failure audits."""
    return run_sync(ainfer_canonical_plan(question))


async def _aplan_and_execute_canonical_plan(
    question: str,
    data: dict[str, dict[str, dict[str, float]]],
    tickers: list[str] | None,
    years: list[int] | None,
    unit_hint: str | None,
    resolved: dict[str, Any] | None = None,
    diag: dict[str, Any] | None = None,
) -> tuple[float, str] | None:
    """Let the model fill a Pydantic plan; Python validates and executes."""
    plan_obj = await ainfer_canonical_plan(question)
    if plan_obj is None:
        return None
    if plan_obj.unsupported:
        if diag is not None:
            diag["canonical_plan"] = "unsupported"
        return None
    plan = plan_obj.model_dump(exclude_none=True)
    if diag is not None:
        diag["canonical_plan"] = plan
    return execute_canonical_plan(
        data,
        plan,
        default_tickers=tickers,
        default_years=years,
        unit_hint=unit_hint,
        resolved=resolved,
    )


# Headline raw metrics worth showing alongside the ratios. The full canonical
# row carries ~60 fields; dumping all of them buries the signal, so we keep the
# line items questions actually reference.
_HEADLINE = [
    "net_revenue", "gross_profit", "operating_profit", "profit_before_tax",
    "net_profit", "interest_expense", "net_cash_operating",
    "total_assets", "total_debt", "equity",
]


def _render(data: dict) -> str:
    """Render each year as pre-computed ratios + a few headline raw metrics."""
    lines: list[str] = []
    for ticker in sorted(data):
        lines.append(f"{ticker}:")
        for yr in sorted(data[ticker]):
            metrics = data[ticker][yr]
            ratios = ratios_for(metrics)
            rtxt = ", ".join(f"{k}={v:.10g}" for k, v in sorted(ratios.items()))
            raw = ", ".join(f"{k}={metrics[k]:.6g}" for k in _HEADLINE if k in metrics)
            lines.append(f"  {yr}: {rtxt}")
            lines.append(f"      [VND] {raw}")
    return "\n".join(lines)


# ── LLM client ────────────────────────────────────────────────────────────────

@tool
def final_answer(answer: float) -> float:
    """Nộp đáp số cuối cùng dưới dạng số thực."""
    return answer


async def _aextract_number(reasoning: str) -> float | None:
    """Second call: turn the reasoning's final answer into an exact JSON float.

    The server has no auto tool-choice, so we cannot let the model reason and
    emit a tool call in one shot. We reason in text (thinking on, no tools) then
    force final_answer here — a JSON float avoids the decimal-drop bug we hit
    parsing numbers out of free text."""
    llm = get_chat_model(thinking=False, max_tokens=256).bind_tools(
        [final_answer], tool_choice="required"
    )
    prompt = EXTRACT_PROMPT + reasoning
    try:
        ai: AIMessage = await llm.ainvoke([HumanMessage(prompt)])
    except Exception as e:
        if _TRACE:
            print(f"[formula] extract error: {e}")
        return None
    for tc in ai.tool_calls:
        if tc["name"] == "final_answer" and tc["args"].get("answer") is not None:
            v = float(tc["args"]["answer"])
            return v if v == v and v not in (float("inf"), float("-inf")) else None
    return None


def _postprocess_formula_answer(question: str, answer: float, unit_hint: str | None = None) -> float:
    """Repair obvious one-shot money-unit misses without touching ratios."""
    hinted = (unit_hint or "").strip().lower()
    unit = hinted if hinted not in {"", "none", "(không nêu — giữ nguyên giá trị gốc)"} else detect_unit(question)
    unit = (unit or "").strip().lower()
    magnitude = abs(answer)
    if unit == "nghìn tỷ" and magnitude >= 1e9:
        return answer / 1e12
    if unit == "trăm tỷ" and magnitude >= 1e8:
        return answer / 1e11
    if unit == "tỷ" and magnitude >= 1e7:
        return answer / 1e9
    if unit == "triệu" and magnitude >= 1e5:
        return answer / 1e6
    return answer


async def _asolve(question: str, data: dict, thinking: bool, max_tokens: int) -> float | None:
    """Reason over the full data table, then emit the number."""
    llm = get_chat_model(thinking=thinking, max_tokens=max_tokens)  # no tools — let the model reason freely
    prompt = FORMULA_PROMPT.format(table=_render(data), question=question)
    try:
        ai: AIMessage = await llm.ainvoke([SystemMessage(FORMULA_SYSTEM), HumanMessage(prompt)])
    except Exception as e:
        if _TRACE:
            print(f"[formula] solve error: {e}")
        return None
    reasoning = ai.content or ""
    if not reasoning.strip():
        return None
    if _TRACE:
        tail = reasoning.strip().splitlines()[-1] if reasoning.strip() else ""
        print(f"  reasoning tail: {tail}")
    return await _aextract_number(reasoning)


# ── Public service ────────────────────────────────────────────────────────────

_SKIP = "formula_skip"


def _prefers_fact_plan(question: str) -> bool:
    """Return true for operations CanonicalPlan does not model well."""
    q = question.lower()
    indicators = (
        "bình quân",
        "trung bình",
        "giả định",
        "kịch bản",
        "nếu ",
        "giảm",
        "tăng trên",
        "so với kỳ so sánh",
        "đòn bẩy kinh doanh",
        "số ngày tồn kho",
        "doh",
        "giải phóng",
        "tài sản cố định",
        "vòng quay",
    )
    return any(indicator in q for indicator in indicators)


def _evidence(
    names: dict[str, str], query: str, fallback: set[str] | None = None
) -> list[dict[str, str]]:
    """Evidence is whatever frames the query actually reads -- nothing wider.

    A literal query reads no frame, so `fallback` names the frames the answer was
    actually computed from; the REPL solver reports evidence the same way.
    """
    used = query_names(query) or (fallback or set())
    return [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
        if var in used
    ]


def _packaged(
    result: float,
    trace: str,
    data: dict[str, dict[str, dict[str, float]]],
    provenance: dict[tuple[str, str, str], tuple[str, int, int]],
    resolved: dict[str, Any],
    names: dict[str, str],
    prior_errors: list[str],
    diag: dict[str, Any],
) -> dict:
    """Ship a runnable `pandas_query`, or a literal when no source cell is traceable.

    The submission is scored by re-running `pandas_query`, so the trace string
    the planners build for diagnostics cannot be the query itself. When the
    answer comes from one identifiable row we rebuild it over the real CSV
    cells; the one-shot reasoner has no plan to trace, so it falls back to the
    literal answer -- the same thing the REPL solver already ships. The trace is
    kept in `errors` so the fallback stays visible.
    """
    expr = None
    if resolved:
        expr = pandas_expr_for_metric(
            data,
            provenance,
            ticker=str(resolved.get("ticker") or ""),
            year=resolved.get("year") or 0,
            metric_id=str(resolved.get("metric") or ""),
            unit=resolved.get("unit"),
            expected=result,
        )
    query = expr or repr(float(result))
    contributing = {var for var, _row, _col in provenance.values()}
    diag.update(trace=trace, resolved=dict(resolved), traceable=bool(expr))
    row = data.get(str(resolved.get("ticker") or ""), {}).get(str(resolved.get("year") or ""))
    if row:
        # The canonical row the answer was read from: this is what separates an
        # extraction fault (row is wrong) from a mapping fault (row is right).
        diag["row"] = {
            "ratios": {k: round(v, 6) for k, v in sorted(ratios_for(row).items())},
            "raw": {k: row[k] for k in _HEADLINE if k in row},
        }
    return {
        "answer": result,
        "pandas_query": query,
        "evidence": _evidence(names, query, contributing or set(names)),
        "solver": "formula",
        "errors": prior_errors if expr else prior_errors + [f"formula: query not traceable to cells ({trace})"],
        "diag": diag,
    }


async def asolve_formula(
    *,
    question: str,
    frames: dict[str, Any],
    names: dict[str, str],
    tickers: list[str] | None = None,
    years: list[int] | None = None,
    unit_hint: str | None = None,
    errors: list[str] | None = None,
    thinking: bool = True,
    max_tokens: int = 8192,
) -> dict:
    """Solve a finance formula question over loaded frames.

    Returns a graph/submission-shaped patch. `solver="formula_skip"` means the
    caller should route to a broader fallback such as REPL.
    """
    prior_errors = list(errors or [])
    effective_unit = unit_hint or detect_unit(question)
    diag: dict[str, Any] = {
        "solver": "formula",
        "unit_hint": unit_hint or "",
        "unit_used": effective_unit,
        "tickers": list(tickers or []),
        "years": list(years or []),
    }

    def _skip(reason: str) -> dict:
        diag["path"] = "skip"
        return {
            "solver": _SKIP,
            "errors": prior_errors + [f"formula_skip: {reason}"],
            "diag": {**diag, "skip_reason": reason},
        }

    provenance: dict[tuple[str, str, str], tuple[str, int, int]] = {}
    data = _collect_canonical(frames, names, provenance)
    diag["canonical"] = {t: sorted(data[t]) for t in sorted(data)}
    if not data:
        return _skip("no canonical data")

    prefer_fact = _prefers_fact_plan(question)
    diag["prefers_fact_plan"] = prefer_fact
    resolved: dict[str, Any] = {}
    deterministic = None
    if prefer_fact:
        deterministic = await aplan_and_execute_fact_plan(
            question,
            data,
            tickers=tickers or [],
            years=years or [],
            unit_hint=effective_unit,
            resolved=resolved,
            diag=diag,
        )
        diag["path"] = "fact_plan"

    if deterministic is None:
        deterministic = await _aplan_and_execute_canonical_plan(
            question,
            data,
            tickers=tickers or [],
            years=years or [],
            unit_hint=effective_unit,
            resolved=resolved,
            diag=diag,
        )
        diag["path"] = "canonical_plan"

    if deterministic is None and not prefer_fact:
        deterministic = await aplan_and_execute_fact_plan(
            question,
            data,
            tickers=tickers or [],
            years=years or [],
            unit_hint=effective_unit,
            resolved=resolved,
            diag=diag,
        )
        diag["path"] = "fact_plan"

    if deterministic is not None:
        result, trace = deterministic
        return _packaged(result, trace, data, provenance, resolved, names, prior_errors, diag)

    result = await _asolve(question, data, thinking=thinking, max_tokens=max_tokens)
    diag["path"] = "oneshot"
    if result is None:
        return _skip("solver returned no answer")
    raw = result
    result = _postprocess_formula_answer(question, result, unit_hint or "")
    diag["oneshot_raw"] = raw

    return _packaged(
        result,
        f"formula_oneshot({len(data)} tickers)",
        data,
        provenance,
        {},
        names,
        prior_errors,
        diag,
    )


def solve_formula(
    *,
    question: str,
    frames: dict[str, Any],
    names: dict[str, str],
    tickers: list[str] | None = None,
    years: list[int] | None = None,
    unit_hint: str | None = None,
    errors: list[str] | None = None,
    thinking: bool = True,
    max_tokens: int = 8192,
) -> dict:
    """Sync `asolve_formula`, for single-question scripts."""
    return run_sync(
        asolve_formula(
            question=question,
            frames=frames,
            names=names,
            tickers=tickers,
            years=years,
            unit_hint=unit_hint,
            errors=errors,
            thinking=thinking,
            max_tokens=max_tokens,
        )
    )
