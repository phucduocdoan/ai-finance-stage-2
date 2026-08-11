"""Tests for the end-to-end runner's own logic (no data files, no GPU, no LLM).

What is worth testing here is not retrieval or planning -- both have their own
tests -- but the three properties the runner exists for: a failing stage is
recorded instead of thrown, resume is append-only with last-wins, and the
submission item carries the fields `submission_rule.txt` asks for. The judge and
planner are replaced by stubs, so each stage's failure mode is provoked directly.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.pipelines import submission as runner
from finance_qa.pipelines.submission import (
    _parse_ids,
    read_records,
    run_question,
    submission_item,
    summarize,
)
from finance_qa.modules.rag.candidates import Pool


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


DOC = "AAA_financial_statements_2020_consolidated"
QUESTION = {"id": 7, "question": "Tổng tài sản năm 2020 là bao nhiêu?"}
POOL = Pool(query="tài sản", keys=[f"{DOC}|{i}" for i in (1, 2, 3)], ranked=[f"{DOC}|3", f"{DOC}|1"])

PLAN = {
    "pandas_query": "float(df1.iloc[3, 1])",
    "answer": 1234.5,
    "evidence": [{"variable": "df1", "csv_path": f"data/{DOC}_table_3.csv"}],
    "error": "",
    "attempts": 1,
    "planner": True,
    "plan": {"bindings": []},
    "plan_adjustments": [],
    "planner_error": "",
}


# -- submission shape ------------------------------------------------------

item = submission_item(QUESTION, [f"{DOC}|3", f"{DOC}|1"], PLAN)
check("item keeps the question id and text", (item["id"], item["question"]) == (7, QUESTION["question"]))
check("answer comes from execution, not from the model's prose", item["answer"] == 1234.5)
check("relevant_tables is every table the planner saw", item["relevant_tables"] == [f"{DOC}|3", f"{DOC}|1"])
# Evidence is narrower than relevant_tables on purpose: the query only reads one
# frame, and validate() enforces evidence == query variables exactly.
check("evidence stays narrow", [e["variable"] for e in item["evidence"]] == ["df1"])
check("relevant_docs is deduped", item["relevant_docs"] == [DOC])
check(
    "multi-doc tables produce one doc each, in order",
    submission_item(QUESTION, [f"{DOC}|3", "BBB_x|1", f"{DOC}|1"], PLAN)["relevant_docs"]
    == [DOC, "BBB_x"],
)


# -- per-stage errors ------------------------------------------------------

class Stub:
    """A retriever whose judge behaviour is scripted per test."""

    def __init__(self, picks=None, raises=False):
        self.picks = picks
        self.raises = raises

    def select(self, question, pool, *, thinking=True):
        if self.raises:
            raise RuntimeError("judge HTTP 400")
        return {
            "query": pool.query,
            "n_candidates": len(pool.keys),
            "pool_size": len(pool.ranked),
            "picks": list(self.picks or []),
            "ranked": list(pool.ranked),
        }


def with_stubs(generate, validate):
    """Swap the two application APIs run_question calls, restore afterwards."""
    original = (runner.generate, runner.validate)
    runner.generate, runner.validate = generate, validate
    return original


def restore(original):
    runner.generate, runner.validate = original


ok_generate = lambda *a, **k: dict(PLAN)  # noqa: E731 - one-line stubs read better inline
ok_validate = lambda item, **k: []  # noqa: E731

saved = with_stubs(ok_generate, ok_validate)

record = run_question(Stub(picks=[f"{DOC}|3"]), QUESTION, POOL)
check("a clean run is ok with no stage blamed", (record["status"], record["stage"]) == ("ok", ""))
check("the judge's picks become the planner's tables", record["table_ids"] == [f"{DOC}|3"])
check("the item is kept for submission assembly", record["item"]["id"] == 7)
check("pool sizes are recorded for later diagnosis", (record["n_candidates"], record["pool_size"]) == (3, 2))
check("latency is only set on a completed run", "latency_seconds" in record)

# An empty pick list is a failed judge call, not a claim that nothing is
# relevant, so falling back to the retrieval order beats submitting no evidence.
fallback = run_question(Stub(picks=[]), QUESTION, POOL)
check("an empty judge degrades to the retrieval ranking", fallback["table_ids"] == POOL.ranked)
check("the fallback is flagged, not hidden", fallback["judge_fallback"] is True)
check("max_tables caps what the planner is handed", len(run_question(Stub(picks=[]), QUESTION, POOL, max_tables=1)["table_ids"]) == 1)

judge_down = run_question(Stub(raises=True), QUESTION, POOL)
check("a judge exception is data, not a crash", judge_down["status"] == "error")
check("the failing stage is named", judge_down["stage"] == "retrieve")
check("the exception text is kept", "judge HTTP 400" in judge_down["error"])

empty = run_question(Stub(picks=[]), QUESTION, Pool(query="q", keys=[], ranked=[]))
check("an empty shortlist fails at retrieve", (empty["status"], empty["stage"]) == ("error", "retrieve"))

restore(saved)

saved = with_stubs(lambda *a, **k: (_ for _ in ()).throw(ValueError("no frame")), ok_validate)
planner_down = run_question(Stub(picks=[f"{DOC}|3"]), QUESTION, POOL)
check("a planner exception is attributed to plan", (planner_down["status"], planner_down["stage"]) == ("error", "plan"))
check("timing survives a planner failure", "plan_seconds" in planner_down)
restore(saved)

saved = with_stubs(lambda *a, **k: {**PLAN, "error": "query không chạy được"}, ok_validate)
unrunnable = run_question(Stub(picks=[f"{DOC}|3"]), QUESTION, POOL)
check("a planner-reported error fails the question", unrunnable["status"] == "error")
check("the planner's own diagnostics are kept", unrunnable["pandas_query"] == PLAN["pandas_query"])
restore(saved)

# `invalid` is deliberately distinct from `error`: the pipeline produced an item,
# it just would not survive submission, which is a different thing to go fix.
saved = with_stubs(ok_generate, lambda item, **k: ["evidence rỗng"])
bad = run_question(Stub(picks=[f"{DOC}|3"]), QUESTION, POOL)
check("a schema violation is 'invalid', not 'error'", bad["status"] == "invalid")
check("all validation errors are kept", bad["validation_errors"] == ["evidence rỗng"])
restore(saved)


# -- resume ----------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "run.jsonl"
    check("a missing results file is an empty resume, not an error", read_records(path) == {})
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": 1, "status": "ok"},
                {"id": 2, "status": "error"},
                {"id": 2, "status": "ok"},  # a retry appended later
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    done = read_records(path)
    check("resume reads one record per id", set(done) == {1, 2})
    check("a later retry wins over the earlier failure", done[2]["status"] == "ok")

    path.write_text('{"id": 1}\nnot json\n', encoding="utf-8")
    try:
        read_records(path)
        raised = False
    except ValueError as exc:
        raised = "run.jsonl:2" in str(exc)
    check("a corrupt line names its line number", raised)


# -- selection and summary -------------------------------------------------

check("no --ids means every question", _parse_ids(None, {1, 2}) == {1, 2})
check("--ids selects a subset", _parse_ids("2, 1", {1, 2, 3}) == {1, 2})
for bad_ids in ("x", "9"):
    try:
        _parse_ids(bad_ids, {1, 2})
        rejected = False
    except ValueError:
        rejected = True
    check(f"--ids {bad_ids!r} is rejected up front", rejected)

summary = summarize([
    {"id": 1, "status": "ok", "stage": "", "error": "", "latency_seconds": 10.0,
     "planner": True, "table_ids": ["a", "b"]},
    {"id": 2, "status": "error", "stage": "plan", "error": "boom", "table_ids": ["a"],
     "judge_fallback": True},
    {"id": 3, "status": "invalid", "stage": "validate", "error": "evidence rỗng", "table_ids": ["a"]},
])
check("ok rate counts only clean questions", (summary["ok"], summary["ok_rate"]) == (1, round(1 / 3, 4)))
check("invalid and error are counted apart", (summary["invalid"], summary["error"]) == (1, 1))
check("failures are grouped by stage", summary["failed_stage"] == {"plan": 1, "validate": 1})
check("judge fallbacks are counted", summary["judge_fallback"] == 1)
check("latency averages over completed questions only", summary["mean_latency_seconds"] == 10.0)
check("every failure is listed for triage", [f["id"] for f in summary["failures"]] == [2, 3])
check("empty results summarize without dividing by zero", summarize([])["ok_rate"] is None)

print("tất cả PASS")
