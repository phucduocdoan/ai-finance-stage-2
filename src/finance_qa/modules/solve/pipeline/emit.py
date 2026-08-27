"""Convert executed pandas results into solve-state updates."""
from __future__ import annotations

import re
from typing import Any, Mapping

from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.modules.solve.pipeline.outcome import done_payload


_DF_VAR = re.compile(r"\bdf\d+\b")


def emit_result(
    state: Mapping[str, Any],
    result: dict,
    extra_diag: dict | None = None,
    *,
    solver: str = "codegen",
) -> dict:
    """Turn an `aexecute` result into the state update solve nodes return."""
    final = result["solution"]
    # Evidence must list exactly the variables the query reads, or the submission
    # validator rejects the item. Rebuilt from `names` rather than filtered from
    # `state["evidence"]`, because by the time verify_answer runs that list has
    # already been narrowed to the *previous* query's variables -- a revision that
    # switches to another table would then ship without it (13 of 73 items).
    names = state.get("names") or {}
    everything = [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
    ] or list(state.get("evidence") or [])
    # `\bdfN\b`, not `in`: a substring test reads df1 as used by `df10`, which was
    # harmless at 3 variables and is not once `find_rows` can bind more than nine.
    read = set(_DF_VAR.findall(result["pandas_query"]))
    used = [ev for ev in everything if ev["variable"] in read]
    # A table the query reads must also be submitted, or `evidence` points at a
    # CSV missing from `relevant_tables`. Only the ones actually read: retrieval
    # is scored on its own F2, and appending every table a lookup touched would
    # dilute it.
    table_ids = list(state.get("table_ids") or [])
    table_ids += [
        names[ev["variable"]]
        for ev in used
        if names.get(ev["variable"]) and names[ev["variable"]] not in table_ids
    ]
    return {
        "answer": float(result["answer"]),
        "pandas_query": result["pandas_query"],
        "evidence": used or list(state.get("evidence") or []),
        "table_ids": table_ids,
        "solver": solver,
        "solution": final.model_dump(),
        "errors": list(state.get("errors") or []) + result["errors"],
        "diag": {
            **(state.get("diag") or {}),
            "units": result["diag"],
            "target_row": final.target_row,
            "target_column": final.target_column,
            "table_variable": final.table_variable,
            "evidence_tables": list(state.get("evidence_tables") or []),
            **(extra_diag or {}),
        },
    }


def emit_solver_result(
    state: Mapping[str, Any],
    solver: str,
    result: dict,
    diag_payload: Mapping[str, Any] | None,
    *,
    frames: Mapping[str, Any],
    names: Mapping[str, str],
    evidence_tables: list[str],
    solution: Mapping[str, Any] | None = None,
    table_ids: list[str] | None = None,
    codegen_prompt: str = "",
) -> dict:
    """Emit a successful narrow-solver result with solver-local bookkeeping."""
    at_solver = {
        **state,
        "names": names,
        "frames": frames,
        "evidence_tables": evidence_tables,
    }
    if solution is not None:
        at_solver["solution"] = solution
    if table_ids is not None:
        at_solver["table_ids"] = table_ids

    emitted = emit_result(
        at_solver,
        result,
        {solver: done_payload(diag_payload)},
        solver=solver,
    )
    return {
        **emitted,
        "frames": frames,
        "names": names,
        "evidence_tables": evidence_tables,
        "codegen_prompt": codegen_prompt,
    }


__all__ = ["emit_result", "emit_solver_result"]
