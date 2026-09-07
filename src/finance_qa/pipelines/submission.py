"""The submission item shape shared by the pipeline runners.

`scripts/pipeline/run_graph.py` builds one of these per question from the solve_qa graph's
final state; `scripts/pipeline/build_submission.py` packages a run's items into the
leaderboard ZIP.
"""

from __future__ import annotations

from typing import Any


def submission_item(
    question: dict[str, Any], table_ids: list[str], plan: dict[str, Any]
) -> dict[str, Any]:
    """The submission JSON for one question.

    `relevant_tables` is every table handed to the planner, not just the ones the
    query ended up reading: retrieval is scored on its own, so dropping a
    correctly retrieved table because the planner did not need it would throw
    away recall. `evidence` stays narrow -- it must match the query exactly.
    """
    docs: dict[str, None] = {}
    for table_id in table_ids:
        docs.setdefault(table_id.rsplit("|", 1)[0], None)
    return {
        "id": question["id"],
        "question": question["question"],
        "answer": plan.get("answer"),
        "relevant_docs": list(docs),
        "relevant_tables": list(table_ids),
        "evidence": plan.get("evidence", []),
        "pandas_query": plan.get("pandas_query", ""),
    }
