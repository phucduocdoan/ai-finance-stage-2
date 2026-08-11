"""Score the retrieval a pipeline run actually submitted, with the contest metric.

`evaluate_retrieval.py` sweeps K over a retrieval *stage* (rrf, judge, ...). This
scores what the pipeline really put in `relevant_tables`: no K cap, because the
LLM judge picks a variable number of tables per question and that choice is part
of what is being measured. Those two answer different questions -- the sweep says
"how good could a fixed-K cut be", this says "how good is the submission".

Only questions carrying `gt_tables` are scored (15 of 24 today), so n is small
and every question moves macro P/R by 1/n. Treat single-run deltas accordingly.

Run:
  PYTHONPATH=src .venv_bge/bin/python scripts/eval_submitted_retrieval.py \
      --run artifacts/runs/full_1012.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from finance_qa.core.paths import EVALSET_PATH
from finance_qa.evaluation.retrieval import f2_score, precision_recall_at_k


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, default=Path("artifacts/runs/full_1012.jsonl"))
    args = ap.parse_args(argv)

    evalset = [
        q for q in json.loads(EVALSET_PATH.read_text(encoding="utf-8")) if q.get("gt_tables")
    ]
    run: dict[int, dict] = {}
    with args.run.open(encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            row = json.loads(line)
            run[int(row["id"])] = row

    scored, missing = [], []
    for q in evalset:
        record = run.get(q["qid"])
        if record is None:
            missing.append(q["qid"])
            continue
        submitted = list(record.get("table_ids") or [])
        # k = len(submitted): score the set as submitted, uncapped.
        p, r = precision_recall_at_k(submitted, q["gt_tables"], len(submitted))
        scored.append((q["qid"], len(submitted), len(q["gt_tables"]), p, r))

    if not scored:
        print(f"no scorable questions in {args.run}")
        return 1

    print(f"run: {args.run}")
    for qid, n_sub, n_groups, p, r in scored:
        print(f"  qid{qid:<5} {n_sub:>2} submitted / {n_groups} groups   P={p:.2f} R={r:.2f}")

    precision = sum(row[3] for row in scored) / len(scored)
    recall = sum(row[4] for row in scored) / len(scored)
    print(
        f"\nmacro P={precision:.1%}  R={recall:.1%}  F2={f2_score(precision, recall):.1%}"
        f"  (n={len(scored)})"
    )
    if missing:
        print(f"not in run, excluded from n: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
