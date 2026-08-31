"""Score the raw-table linker's cell ranking against cell-level ground truth.

`data/eval/gold100_raw.jsonl` labels the exact cell each question needs
(`table_id`, `row_label`, `column`, `value`), which is the thing the deterministic
scorer in `raw_table_linker` is supposed to rank first. Scoring against it needs
no LLM and no graph run, so a change to the scoring formula can be measured in
seconds instead of a 30-minute live arm with codegen noise on top.

92 of the 100 questions sit outside both the hand-labeled gold73 ids and the
363-440 band the pipeline was tuned on, so `--unseen` is a real held-out slice.

    PYTHONPATH=src .venv_bge/bin/python scripts/probe_cell_ranking.py
    PYTHONPATH=src .venv_bge/bin/python scripts/probe_cell_ranking.py --unseen --op lookup
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any

from finance_qa.modules.solve.solvers import raw_table_linker as raw

GOLD100 = Path("data/eval/gold100_raw.jsonl")
TUNED_GOLD = ("data/eval/unbiased60_gold.jsonl", "data/eval/manual15_gold.jsonl")
TUNED_BAND = range(363, 441)


def tuned_ids() -> set[int]:
    """Ids whose answers were already inspected while tuning the pipeline."""
    ids = set(TUNED_BAND)
    for path in TUNED_GOLD:
        if Path(path).exists():
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ids.add(int(json.loads(line)["id"]))
    return ids


def gt_keys(row: dict[str, Any]) -> set[tuple[str, str]]:
    """The labeled cells as (table_id, normalized row label)."""
    out: set[tuple[str, str]] = set()
    for cell in row.get("gt_tables") or []:
        if isinstance(cell, dict) and cell.get("table_id"):
            out.add((str(cell["table_id"]), raw._norm(cell.get("row_label"))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseen", action="store_true", help="only ids never inspected while tuning")
    ap.add_argument("--op", action="append", default=[], help="restrict to these gold100 ops")
    ap.add_argument("--limit-per-slot", type=int, default=40)
    ap.add_argument("--show", type=int, default=0, help="print this many misses in detail")
    args = ap.parse_args()

    skip = tuned_ids() if args.unseen else set()
    rows = [
        r
        for line in GOLD100.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for r in [json.loads(line)]
        if r.get("status") == "resolved" and r.get("gt_tables") and int(r["qid"]) not in skip
        and (not args.op or r.get("op") in args.op)
    ]

    stats = collections.Counter()
    by_op: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    misses: list[str] = []
    for row in rows:
        qid, op = int(row["qid"]), str(row.get("op") or "?")
        stats["questions"] += 1
        by_op[op]["questions"] += 1
        request, reason = raw.build_request({
            "question": row["question"],
            "tickers": row.get("tickers") or ([row["ticker"]] if row.get("ticker") else []),
            "years": row.get("years") or [],
            "doc_type": row.get("doc_type"),
        })
        if request is None:
            stats["declined"] += 1
            by_op[op]["declined"] += 1
            continue
        candidates, _ = raw.build_candidates(request, limit_per_slot=args.limit_per_slot)
        if not candidates:
            stats["no_candidates"] += 1
            by_op[op]["no_candidates"] += 1
            continue
        ranked = sorted(candidates, key=lambda c: -c.score)
        wanted = gt_keys(row)
        hits = [i for i, c in enumerate(ranked) if (c.table_id, raw._norm(c.row_label)) in wanted]
        rank = hits[0] if hits else None

        # Does the deterministic gate claim this question instead of handing it to
        # the LLM planner, and is it right when it does?
        decision = raw.deterministic_decision(request, candidates)
        if decision.supported:
            picked = {c.id: c for c in candidates}
            cells = [picked[cid] for cid in decision.candidate_ids if cid in picked]
            right = bool(cells) and all(
                (c.table_id, raw._norm(c.row_label)) in wanted for c in cells
            )
            stats["gate_fired"] += 1
            by_op[op]["gate_fired"] += 1
            stats["gate_right" if right else "gate_wrong"] += 1
            by_op[op]["gate_right" if right else "gate_wrong"] += 1
        else:
            stats["gate_abstained"] += 1
            by_op[op]["gate_abstained"] += 1
        if rank is None:
            stats["gt_absent"] += 1
            by_op[op]["gt_absent"] += 1
        else:
            stats["gt_present"] += 1
            by_op[op]["gt_present"] += 1
            for bucket, cut in (("top1", 1), ("top3", 3), ("top10", 10)):
                if rank < cut:
                    stats[bucket] += 1
                    by_op[op][bucket] += 1
        if rank != 0 and len(misses) < args.show:
            top = ranked[0]
            misses.append(
                f"q{qid} [{op}] rank={rank}\n"
                f"   asked : {row['question'][:110]}\n"
                f"   picked: {top.table_id} | {top.row_label[:70]!r} | {top.column} "
                f"| r={top.row_score:.2f} t={top.table_score:.2f} c={top.column_score:.2f} s={top.score:.3f}\n"
                f"   wanted: {sorted(wanted)[0][0]} | {sorted(wanted)[0][1][:70]!r}"
            )

    n = stats["questions"]
    scored = stats["gt_present"] + stats["gt_absent"]
    print(f"questions={n}  declined={stats['declined']}  no_candidates={stats['no_candidates']}  scored={scored}")
    if scored:
        print(
            f"recall@{args.limit_per_slot}={stats['gt_present']}/{scored}"
            f"  top1={stats['top1']}/{scored}  top3={stats['top3']}/{scored}  top10={stats['top10']}/{scored}"
        )
    print(
        f"deterministic gate: fired={stats['gate_fired']}/{scored}"
        f" right={stats['gate_right']} wrong={stats['gate_wrong']}"
        f"  abstained={stats['gate_abstained']} (those reach the LLM planner)"
    )
    print("\nby op:")
    for op in sorted(by_op, key=lambda o: -by_op[o]["questions"]):
        c = by_op[op]
        s = c["gt_present"] + c["gt_absent"]
        print(
            f"  {op:9s} n={c['questions']:3d} declined={c['declined']:3d} scored={s:3d}"
            f" recall={c['gt_present']:3d} top1={c['top1']:3d} top3={c['top3']:3d}"
        )
    for miss in misses:
        print("\n" + miss)


if __name__ == "__main__":
    main()
