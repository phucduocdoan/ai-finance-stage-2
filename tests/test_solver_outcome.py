"""Regression tests for the shared solver outcome contract."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.pipeline.outcome import (  # noqa: E402
    answered,
    append_unique,
    declined,
    done_payload,
    errored,
    solver_done,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


state = {"diag": {"retrieve": {"done": True}}, "errors": ["old"]}

miss = declined(
    state,
    "raw_table_linker",
    "not enough candidates",
    payload={"candidate_count": 1},
    errors=["raw_table_linker: not enough candidates"],
)
diag = miss["diag"]["raw_table_linker"]
check("declined marks done false", diag["status"] == "declined" and not diag["done"])
check("declined preserves payload", diag["candidate_count"] == 1)
check("declined appends errors", miss["errors"] == ["old", "raw_table_linker: not enough candidates"])
check("declined is not router-done", not solver_done(miss, "raw_table_linker"))

boom = errored(state, "cell_locator", "ValueError: bad table")
check("errored status is explicit", boom["diag"]["cell_locator"]["status"] == "error")

done = {"diag": {"formula_facts": done_payload({"table_ids": ["ABC|1"]})}}
check("done payload routes as done", solver_done(done, "formula_facts"))
check("legacy done flag still routes as done", solver_done({"diag": {"x": {"done": True}}}, "x"))

check(
    "append unique preserves first-seen order",
    append_unique(["A|1", "B|2"], ["B|2", "C|3"]) == ["A|1", "B|2", "C|3"],
)

hit = answered(
    state,
    "structured_facts",
    answer=12,
    pandas_query="float(12)",
    evidence=[{"variable": "df1", "csv_path": "data/a.csv"}],
    table_ids=append_unique(["A|1"], ["A|1", "B|2"]),
    diag_payload={"source": "fact_store"},
    errors=state["errors"],
    frames={},
    names={},
    evidence_tables=["B|2"],
    codegen_prompt="",
    solution={},
)
check("answered stores solver name", hit["solver"] == "structured_facts")
check("answered coerces numeric answer", hit["answer"] == 12.0)
check("answered marks diag done", hit["diag"]["structured_facts"]["status"] == "done")
check("answered preserves previous diag", hit["diag"]["retrieve"]["done"] is True)
check("answered keeps explicit empty prompt", hit["codegen_prompt"] == "")
