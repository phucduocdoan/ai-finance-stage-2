"""Acceptance test for build_gold_candidates.py: recall AND accepted-table
volume, side by side, per question.

Earlier versions of this check (run ad hoc, not as a script) measured group
recall only -- "did the resolver's shortlist contain every gt_tables group's
member". That number alone is not usable to pick a threshold: a run can hit
36/36 groups while also accepting hundreds of false-positive tables, and
recall-only scoring can't see it. This script reports both:

  - recall:  per qid, hit/miss for each of evalset.json's own gt_tables
             groups (any member of the group present in accepted_table_ids
             counts as a hit for that group) -- ground truth is evalset.json,
             never the resolver's own (approximate) gt_tables output.
  - volume:  len(accepted_table_ids) per qid, i.e. how many tables the
             resolver is actually willing to call evidence after the
             empty-value filter and the per-report cap.

A high-recall / high-volume result must read as a failure, not a success.

Read-only against data/eval/evalset.json (for ground truth only -- this
script does not modify it) and against build_gold_candidates.py's resolver
functions. Never writes evalset.json.

Usage:
  python scripts/gold_acceptance_test.py
  python scripts/gold_acceptance_test.py --threshold 88,90,92,95 --max-per-report 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_gold_candidates import (
    META_PATH,
    QUESTIONS_PATH,
    DEFAULT_THRESHOLD,
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_PER_REPORT,
    DEFAULT_MAX_MAIN_PER_REPORT,
    build_candidates_for_question,
    build_report_index,
    load_questions_by_id,
)

ROOT = Path(__file__).resolve().parent.parent
EVALSET_PATH = ROOT / "data/eval/evalset.json"

ACCEPTANCE_TEST_QIDS = [1, 17, 40, 44, 55, 100, 363, 524, 582, 605, 674, 752, 754, 818, 820]


def f2_score(precision: float, recall: float) -> float:
    """Same formula as finance_qa.evaluation.retrieval.f2_score, inlined here
    rather than imported -- this script (like build_gold_candidates.py) is
    meant to have zero dependency on the RAG pipeline, and importing that
    module chain-imports the embedding stack."""
    if precision + recall == 0:
        return 0.0
    return 5 * precision * recall / (4 * precision + recall)


def load_gold_groups() -> dict[int, list[list[str]]]:
    data = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    return {int(r["qid"]): r["gt_tables"] for r in data if r.get("gt_tables")}


def run_one(qid: int, threshold: int, max_candidates: int, max_per_report: int,
            max_main_per_report: int,
            questions, ticker_year_reports, report_tables, ticker_company,
            gold: dict[int, list[list[str]]]) -> dict:
    q = questions[qid]
    record = build_candidates_for_question(
        q, ticker_year_reports, report_tables, ticker_company,
        threshold=threshold, max_candidates=max_candidates, max_per_report=max_per_report,
        max_main_per_report=max_main_per_report,
    )
    accepted = set(record["accepted_table_ids"])
    groups = gold.get(qid, [])
    hits = [any(t in accepted for t in group) for group in groups]
    # Diagnostic: of the groups we MISSED, how many were reachable in principle
    # (present somewhere in cell_detail's candidates) but got excluded by the
    # per-report cap rather than never being found at all -- distinguishes a
    # threshold/matching miss from a precision-cap miss.
    all_candidate_ids = {
        c["table_id"] for cell in record["cell_detail"] for c in cell["candidates"]
    }
    flagged_ids = {tid for f in record["flagged_for_manual"] for tid in f["table_ids"]}
    missed_via_cap = [
        i for i, hit in enumerate(hits)
        if not hit and any(t in flagged_ids for t in groups[i])
    ]
    missed_no_qualifying = [
        i for i, hit in enumerate(hits)
        if not hit and i not in missed_via_cap and any(t in all_candidate_ids for t in groups[i])
    ]
    missed_never_found = [
        i for i, hit in enumerate(hits)
        if not hit and i not in missed_via_cap and i not in missed_no_qualifying
    ]
    n_hit = sum(hits)
    return {
        "qid": qid,
        "n_groups": len(groups),
        "n_hit": n_hit,
        "n_accepted": len(accepted),
        "n_flagged_reports": record["n_flagged_for_manual"],
        "missed_via_cap": len(missed_via_cap),
        "missed_no_qualifying": len(missed_no_qualifying),
        "missed_never_found": len(missed_never_found),
        # Per-question precision/recall, same shape as
        # finance_qa.evaluation.retrieval.precision_recall_at_k (hits counted
        # by group, over the whole accepted set rather than a ranked top-k --
        # there's no ranking here, accepted is already a final unordered set):
        # precision = groups-hit / accepted-tables, recall = groups-hit / groups.
        "precision": n_hit / len(accepted) if accepted else 0.0,
        "recall": n_hit / len(groups) if groups else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", default=str(DEFAULT_THRESHOLD), help="comma-separated thresholds to test")
    ap.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    ap.add_argument("--max-per-report", type=int, default=DEFAULT_MAX_PER_REPORT)
    ap.add_argument("--max-main-per-report", type=int, default=DEFAULT_MAX_MAIN_PER_REPORT)
    ap.add_argument("--qids", help="comma-separated qids (default: the 15 known-gold qids)")
    args = ap.parse_args()

    thresholds = [int(x) for x in args.threshold.split(",") if x.strip()]
    qids = [int(x) for x in args.qids.split(",")] if args.qids else ACCEPTANCE_TEST_QIDS

    gold = load_gold_groups()
    questions = load_questions_by_id(QUESTIONS_PATH)
    ticker_year_reports, report_tables, ticker_company = build_report_index(META_PATH)

    for threshold in thresholds:
        print(f"\n=== threshold={threshold} max_candidates={args.max_candidates} "
              f"max_per_report={args.max_per_report} max_main_per_report={args.max_main_per_report} ===")
        header = (f"{'qid':>5} {'hit/groups':>11} {'accepted':>9} {'flagged':>8} "
                  f"{'miss(cap)':>10} {'miss(noqual)':>12} {'miss(never)':>11}")
        print(header)
        print("-" * len(header))
        total_hit = total_groups = total_accepted = total_flagged = 0
        precisions, recalls = [], []
        for qid in qids:
            r = run_one(qid, threshold, args.max_candidates, args.max_per_report,
                        args.max_main_per_report,
                        questions, ticker_year_reports, report_tables, ticker_company, gold)
            print(f"{r['qid']:>5} {r['n_hit']:>4}/{r['n_groups']:<6} {r['n_accepted']:>9} "
                  f"{r['n_flagged_reports']:>8} {r['missed_via_cap']:>10} "
                  f"{r['missed_no_qualifying']:>12} {r['missed_never_found']:>11}")
            total_hit += r["n_hit"]
            total_groups += r["n_groups"]
            total_accepted += r["n_accepted"]
            total_flagged += r["n_flagged_reports"]
            precisions.append(r["precision"])
            recalls.append(r["recall"])
        print("-" * len(header))
        recall = total_hit / total_groups if total_groups else 0.0
        macro_p = sum(precisions) / len(precisions) if precisions else 0.0
        macro_r = sum(recalls) / len(recalls) if recalls else 0.0
        macro_f2 = f2_score(macro_p, macro_r)
        print(f"TOTAL: {total_hit}/{total_groups} groups hit ({recall:.1%} recall)   "
              f"{total_accepted} accepted tables total ({total_accepted/len(qids):.1f}/q)   "
              f"{total_flagged} report(s) flagged for manual review")
        print(f"macro P={macro_p:.1%}  R={macro_r:.1%}  F2={macro_f2:.1%}  "
              "(per-question precision=groups_hit/accepted, recall=groups_hit/groups)")


if __name__ == "__main__":
    main()
