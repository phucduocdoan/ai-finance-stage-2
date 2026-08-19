"""Run the query, repair it at most twice, then apply the unit conversion.

Order matters: repair first, scale last. Repair fixes *execution* errors, which
are about pandas syntax and indexing; scaling is deterministic and cannot fail,
so putting it after repair keeps the model's attention on the one thing it is
being asked to fix. The submitted `pandas_query` is the scaled string, because
the grader re-executes it and must reproduce the submitted answer.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen import CODEGEN_SYSTEM, STRUCTURED_METHOD, PandasSolution
from finance_qa.modules.solve.context import page_text
from finance_qa.modules.solve.units import (
    detect_unit,
    resolve_source_unit,
    scale_expression,
    strip_scale_factor,
    unit_from_hint,
)
from finance_qa.modules.tools.python_exec import run_query

MAX_REPAIRS = 2

# Control-arm temperature. Not 0.0, because without `repair_history` the repair
# prompt differs from the generation prompt by one appended error line, so at
# temperature 0 the model re-emits the identical query: all 8 questions that died
# on the 60-question gold set logged the *same* error twice more and never varied.
#
# That reading of the symptom was wrong. The cause is not sampling: `_arepair`
# built a fresh two-message prompt on every attempt, so attempt 2 never saw
# attempt 1's query or error and had no way to know it was repeating itself.
# Measured on the gold94 runs, noise at 0.3 does not fix it — of the questions
# that entered the loop, the error was byte-identical across every attempt for 5
# of 8 (base1), 5 of 7 (base2) and 4 of 7 (fanout), q381 and q396 three times over.
REPAIR_TEMPERATURE = 0.3

# History arm. With the attempts block below, the prompt genuinely changes between
# attempts — it grows by one failed query each time — so the reason to inject noise
# is gone and the retry can be as reproducible as the first call.
HISTORY_TEMPERATURE = 0.0

_DF_VAR = re.compile(r"\bdf\d+\b")

REPAIR_SYSTEM = CODEGEN_SYSTEM + """

The previous query failed to execute. Fix the pandas query. Do not change the
evidence table you read from. The error is followed by the true shape and the
true column names of every dataframe the query touched — the fixed query must
index by a name from that list, copied character for character."""


def _blank_cell_error(exc: Exception) -> bool:
    """Is this the failure where the query found a cell holding no number?

    Three shapes of the same mistake: the cell is empty (`nan`), the cell holds
    text (`'V.19.'`, `'Đang hoạt động'`, `'1,23%'`), or arithmetic ran against a
    column that is text. Naming the column list back at the model does not help
    here — the column it used exists, it is the *cell* that is unusable.
    """
    if isinstance(exc, (TypeError, ValueError)):
        return any(
            token in str(exc)
            for token in ("non-finite", "could not convert string to float",
                          "did not contain a loop", "not supported for the input types",
                          "unsupported operand")
        )
    return False


def _row_dump(solution: PandasSolution, frames: Mapping[str, pd.DataFrame]) -> str:
    """The row the model said it was aiming at, cell by cell.

    This is the single largest hole in the repair loop: over a 1012-question run
    `ValueError: query returned non-finite nan` was logged 91 times, more than
    every other execution error combined, and it names neither the row nor the
    value. The repair had nothing to work from and re-emitted the query it had
    just written — measured, the error was byte-identical on all three attempts
    for 56 of the 79 questions that ended at 0.0.
    """
    frame = frames.get(solution.table_variable)
    if frame is None:
        return ""
    try:
        row = frame.iloc[int(str(solution.target_row).strip())]
    except (TypeError, ValueError, IndexError):
        return ""  # a label-indexed or multi-cell query: the dump would be a guess
    cells = [
        f"{str(col)!r}={'(rỗng)' if pd.isna(val) or not str(val).strip() else repr(str(val).strip())}"
        for col, val in row.items()
    ]
    return (
        f"Hàng bạn đã đọc, {solution.table_variable}.iloc[{solution.target_row}], "
        f"chứa: {'; '.join(cells)}"
    )


def describe_error(
    exc: Exception,
    query: str,
    frames: Mapping[str, pd.DataFrame],
    solution: PandasSolution | None = None,
) -> str:
    """The failure as the repair call needs to see it.

    `str(exc)` alone is what made the loop a no-op: a `KeyError` arrives as the
    bare string `'2018'` — no exception type, no indication that the problem is a
    column name, no list of the names that do exist. Every repair got that, and
    every repair answered with the query it had just written.
    """
    lines = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, KeyError):
        lines.append("(không có cột hay nhãn nào mang tên này)")
    if solution is not None and _blank_cell_error(exc):
        dump = _row_dump(solution, frames)
        if dump:
            lines.append(dump)
        lines.append(
            "Ô bạn đọc không chứa số. Chọn ô khác: cùng chỉ tiêu nhưng ở cột số "
            "liệu khác, hoặc hàng khác mang đúng nhãn chỉ tiêu mà câu hỏi cần. "
            "Không ép kiểu, không bịa số."
        )
    for var in sorted(set(_DF_VAR.findall(query))):
        frame = frames.get(var)
        if frame is None:
            lines.append(f"{var}: biến này không tồn tại")
            continue
        columns = ", ".join(repr(str(col)) for col in frame.columns)
        lines.append(
            f"{var}: {frame.shape[0]} hàng x {frame.shape[1]} cột; "
            f"chỉ có các cột [{columns}]; vị trí hàng hợp lệ 0..{frame.shape[0] - 1}"
        )
    return "\n".join(lines)


def _attempts_block(attempts: Sequence[tuple[str, str]]) -> str:
    """Every query already tried and why it failed, most recent one in full.

    The earlier entries keep only the first line of `describe_error` — the rest of
    it is the shape and column list of the same dataframes, which does not change
    between attempts, so repeating it three times would spend prompt budget on
    dilution. What the model is missing is the *queries it has already spent*, and
    those are one line each.
    """
    lines = []
    for i, (query, detail) in enumerate(attempts, 1):
        body = detail if i == len(attempts) else (detail.splitlines() or [""])[0]
        lines.append(f"Lần {i} — truy vấn đã chạy:\n{query or '(rỗng)'}\nLỗi:\n{body}")
    lines.append(
        "Tất cả các truy vấn trên đã chạy và đều lỗi. Đừng nộp lại bất kỳ truy vấn "
        "nào trong số đó — hãy đọc một ô khác."
    )
    return "\n\n".join(lines)


async def _arepair(
    prompt: str, attempts: Sequence[tuple[str, str]], *, history: bool
) -> PandasSolution:
    """One repair call. With `history`, it sees every attempt; without, only the last.

    The attempts are rendered into the user message rather than replayed as an
    AIMessage/ToolMessage exchange because `with_structured_output` returns the
    parsed object and discards the raw reply — a reconstructed tool-call turn would
    be invented, not recorded. A plain block carries the same facts.
    """
    query, detail = attempts[-1]
    if history:
        user = f"{prompt}\n\n{_attempts_block(attempts)}"
        temperature = HISTORY_TEMPERATURE
    else:
        user = (
            f"{prompt}\n\n"
            f"Truy vấn trước đó:\n{query}\n\n"
            f"Lỗi khi chạy:\n{detail}"
        )
        temperature = REPAIR_TEMPERATURE
    model = get_chat_model(thinking=False, max_tokens=1024, temperature=temperature)
    result = await model.with_structured_output(
        PandasSolution, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=REPAIR_SYSTEM), HumanMessage(content=user)])
    if not isinstance(result, PandasSolution):
        result = PandasSolution.model_validate(result)
    return result


async def arun_with_repair(
    solution: PandasSolution,
    prompt: str,
    frames: Mapping[str, pd.DataFrame],
    *,
    max_repairs: int = MAX_REPAIRS,
    repair_history: bool = False,
) -> tuple[PandasSolution, float | None, list[str]]:
    """Execute ``solution.pandas_query``, repairing on error.

    Returns ``(solution, raw_value, errors)`` where ``solution`` is the last one
    attempted and ``raw_value`` is the cell value *before* unit conversion, or
    None if every attempt failed.
    """
    errors: list[str] = []
    # Every (query, failure) the loop has spent, which is not what the run record
    # keeps: the column dump is a few hundred chars per attempt and belongs in the
    # prompt, not in the JSONL. Accumulated rather than overwritten so the repair
    # call can see what it has already tried — see `REPAIR_TEMPERATURE`.
    attempts: list[tuple[str, str]] = []
    for attempt in range(max_repairs + 1):
        query = (solution.pandas_query or "").strip()
        if not query:
            errors.append("codegen: pandas_query rỗng")
            attempts.append((query, "Truy vấn rỗng — hãy viết một biểu thức pandas."))
        else:
            try:
                return solution, float(run_query(query, dict(frames))), errors
            except Exception as exc:  # noqa: BLE001 - the repair loop's input
                errors.append(f"execute[{attempt}]: {type(exc).__name__}: {exc}")
                attempts.append((query, describe_error(exc, query, frames, solution)))
        if attempt == max_repairs:
            break
        try:
            solution = await _arepair(prompt, attempts, history=repair_history)
        except Exception as exc:  # noqa: BLE001 - repair itself can fail
            errors.append(f"repair[{attempt}]: {exc}")
            break
    return solution, None, errors


def apply_units(
    solution: PandasSolution,
    frames: Mapping[str, pd.DataFrame],
    *,
    question: str,
    unit_hint: str = "",
    names: Mapping[str, str] | None = None,
) -> tuple[str, dict]:
    """Convert the value's unit exactly once. Returns ``(query, diag)``.

    Exactly once is the whole job. The model was doing it too — writing
    ``/ 1e11`` into its own query and mislabelling the source unit on top — so the
    conversion landed twice and the answer came out 1e15 away from gold. So the
    model's arithmetic is stripped, and its `source_unit` is honoured only when it
    says the value is not money.

    The source unit is read from the table (banner cell, column name, or the
    "Đơn vị tính" line on the page). The target unit comes from the question,
    because that is where "bao nhiêu triệu đồng" is written; the model's
    `target_unit` is the fallback.
    """
    frame = frames.get(solution.table_variable)
    table_id = (names or {}).get(solution.table_variable, "")
    detected, where = (None, "")
    if frame is not None:
        detected, where = detect_unit(
            frame, solution.target_column or None, page_text(table_id) if table_id else ""
        )

    source, fallback = resolve_source_unit(detected, solution.source_unit)
    target = unit_from_hint(question) or unit_from_hint(unit_hint) or solution.target_unit or "unknown"
    raw_query, removed = strip_scale_factor(solution.pandas_query)
    query = scale_expression(raw_query, source, target)
    return query, {
        "source_unit": source,
        "source_unit_from": where or fallback,
        "model_source_unit": solution.source_unit,
        "target_unit": target,
        "scaled": query != raw_query,
        "model_factors_stripped": removed,
    }


async def aexecute(
    solution: PandasSolution,
    prompt: str,
    frames: Mapping[str, pd.DataFrame],
    *,
    question: str,
    unit_hint: str = "",
    names: Mapping[str, str] | None = None,
    max_repairs: int = MAX_REPAIRS,
    repair_history: bool = False,
) -> dict:
    """Full execute-and-repair step. Returns the answer, final query and diag."""
    solution, raw, errors = await arun_with_repair(
        solution, prompt, frames, max_repairs=max_repairs, repair_history=repair_history
    )
    if raw is None:
        # 0.0 with the last query attached: the query is still worth submitting
        # because execution is scored on re-running it, and a query that errors
        # for us may still be the graded one that matters. Never submit a bare
        # float literal — that forfeits the execution objective outright.
        return {
            "answer": 0.0,
            "pandas_query": solution.pandas_query.strip() or "0.0",
            "solution": solution,
            "errors": errors,
            "diag": {"failed": True},
        }

    query, diag = apply_units(
        solution, frames, question=question, unit_hint=unit_hint, names=names
    )
    try:
        answer = float(run_query(query, dict(frames)))
    except Exception as exc:  # noqa: BLE001 - scaling should never break a query
        errors.append(f"scale: {exc}")
        return {
            "answer": raw,
            "pandas_query": solution.pandas_query.strip(),
            "solution": solution,
            "errors": errors,
            "diag": {**diag, "scale_failed": True},
        }

    return {
        "answer": answer,
        "pandas_query": query,
        "solution": solution,
        "errors": errors,
        # `raw_value` is the query as the *model* wrote it, so it still carries any
        # factor listed in `model_factors_stripped`.
        "diag": {**diag, "raw_value": raw, "repairs": len(errors)},
    }


__all__ = [
    "HISTORY_TEMPERATURE", "MAX_REPAIRS", "REPAIR_TEMPERATURE", "aexecute",
    "apply_units", "arun_with_repair", "describe_error",
]
