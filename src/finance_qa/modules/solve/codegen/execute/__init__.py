"""Run the query, repair it at most twice, then apply the unit conversion.

Order matters: repair first, scale last. Repair fixes *execution* errors, which
are about pandas syntax and indexing; scaling is deterministic and cannot fail,
so putting it after repair keeps the model's attention on the one thing it is
being asked to fix. The submitted `pandas_query` is the scaled string, because
the grader re-executes it and must reproduce the submitted answer.

Compatibility facade: the implementation is split across this package's
submodules (execute_repair, execute_units, execute_year, execute_count). This
module re-exports their public names so existing imports of
`finance_qa.modules.solve.codegen.execute` keep working unchanged.

`_arepair` and `arun_with_repair` (and `aexecute`, which calls it) are defined
here rather than in `execute_repair` because tests monkeypatch the module-level
`_arepair` attribute in place (e.g. `execute._arepair = fake_repair`) and rely on
`arun_with_repair`'s call to `_arepair` resolving that same rebound name — which
only happens when both live in the same module namespace as the one tests
import.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen.execute.execute_count import canonical_count, is_count_query
from finance_qa.modules.solve.codegen.execute.execute_repair import (
    HISTORY_TEMPERATURE,
    MAX_REPAIRS,
    REPAIR_SYSTEM,
    REPAIR_TEMPERATURE,
    _attempts_block,
    describe_error,
    multiplies_by_zero,
)
from finance_qa.modules.solve.codegen.execute.execute_units import (
    apply_units,
    as_magnitude,
    between_two_companies,
)
from finance_qa.modules.solve.codegen.execute.execute_year import project_year
from finance_qa.modules.solve.common.intent import intent_norm
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution
from finance_qa.modules.tools.python_exec import run_query


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
        elif multiplies_by_zero(query):
            errors.append(f"execute[{attempt}]: query nhân ô với 0, đáp án bị gán cứng")
            attempts.append((query, (
                "Truy vấn nhân một ô với 0 rồi cộng hằng số, nên kết quả là hằng số "
                "đó chứ không phải số đọc từ bảng. Luật cấm gán cứng kết quả. Hãy "
                "tính đáp án từ các ô thật, hoặc để trống nếu không tính được."
            )))
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


async def aexecute(
    solution: PandasSolution,
    prompt: str,
    frames: Mapping[str, pd.DataFrame],
    *,
    question: str,
    unit_hint: str = "",
    names: Mapping[str, str] | None = None,
    tickers: Sequence[str] = (),
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
        solution, frames, question=question, unit_hint=unit_hint, names=names,
        tickers=tickers,
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
    "apply_units", "arun_with_repair", "as_magnitude", "between_two_companies",
    "canonical_count", "describe_error", "is_count_query", "project_year",
]
