"""Recall@K for the retrieval stages, measured on data/eval/evalset.json.

Two tiers, because the eval set has two (see build_evalset.py):
  - table tier  (15 questions): did we retrieve the GT `report_id|table_pos`?
  - report tier (24 questions): did we retrieve any table from the GT report?

GT is a list of **groups** of interchangeable ids. Two metrics per tier, both
worth watching:
  - recall@K:  mean over questions of (groups hit / groups total). Partial
               credit. This is the number to optimize.
  - all@K:     fraction of questions where *every* group was hit. Stricter, and
               closer to what submission needs, since `relevant_tables` has to
               list all the evidence -- a 5-year question with 4/5 tables found
               still can't be answered.

Stages: `filter` (no ranking), `bm25`, `dense`, `rrf` (BM25 + dense, k=60),
`judge` (LLM picks out of the pool -- see judge.py).
Dense/rrf/judge need data/indexes/tables_dense.npy and a GPU.

The dense channel and the reranker are swappable backends (`--dense-backend`,
`--reranker`); defaults are the measured ones, bge-m3 with no reranker.

The pool itself comes from `finance_qa.modules.rag.candidates`, which is also what
the batch runner uses, so these numbers describe the production policy. Its
defaults (stripped retrieval query, primary-statement expansion, judge_text for
the judge prompt) can be switched off with --no-strip / --no-primary to reproduce
the older measurements.

Run:
  .venv_bge/bin/python scripts/evaluate_retrieval.py --stage rrf
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finance_qa.core.paths import DENSE_INDEX_PATH, EVALSET_PATH
from finance_qa.modules.rag.candidates import (
    CHANNEL_K,
    RRF_K,
    CandidateRetriever,
    rerank_with_picks,
    rrf_fuse,
)
from finance_qa.modules.rag.retrievers.clients import EMBEDDING_BACKENDS, RERANKER_BACKENDS


DENSE_PATH = DENSE_INDEX_PATH

KS = (5, 10, 15, 30, 50)

# Competition-metric sweep range for precision/recall/F2 (table tier only).
# Kept separate from KS so the existing recall@K/all-hit@K output is untouched.
PRF_KS = tuple(range(1, 16))

__all__ = [
    "CHANNEL_K",
    "DENSE_PATH",
    "EVALSET_PATH",
    "KS",
    "PRF_KS",
    "RRF_K",
    "dedupe_reports",
    "f2_score",
    "main",
    "precision_recall_at_k",
    "recall_at_k",
    "rrf_fuse",
]


def recall_at_k(ranked: list[str], groups: list[list[str]], k: int) -> tuple[float, bool]:
    """(fraction of groups hit in top-k, all groups hit)."""
    top = set(ranked[:k])
    hits = sum(1 for g in groups if any(m in top for m in g))
    return hits / len(groups), hits == len(groups)


def precision_recall_at_k(ranked: list[str], groups: list[list[str]], k: int) -> tuple[float, float]:
    """(precision, recall) for the top-k predicted set, per the organizer's formula.

    correct = number of groups with >=1 member in the top-k (same numerator recall_at_k
    uses). Precision divides by the actual predicted-set size (len(top), which can be
    less than k when the pool is short) -- a predicted table that duplicates an
    already-hit group still counts against that denominator, so it still costs
    precision. That's intentional, not a bug.
    """
    top = ranked[:k]
    hits = sum(1 for g in groups if any(m in set(top) for m in g))
    recall = hits / len(groups)
    precision = hits / len(top) if top else 0.0
    return precision, recall


def f2_score(precision: float, recall: float) -> float:
    """F2 = (5*P*R) / (4*P + R), computed once from macro-averaged P and R."""
    if precision + recall == 0:
        return 0.0
    return 5 * precision * recall / (4 * precision + recall)


def dedupe_reports(ranked_tables: list[str]) -> list[str]:
    """Table ranking -> report ranking, keeping each report's best rank."""
    seen: dict[str, None] = {}
    for key in ranked_tables:
        seen.setdefault(key.rsplit("|", 1)[0], None)
    return list(seen)


def score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-question rows into the two-tier summary."""

    def agg(tier: str) -> dict[str, Any]:
        vals = [r for r in rows if r[tier]]
        if not vals:
            return {}
        by_level: dict[str, list[dict]] = defaultdict(list)
        for r in vals:
            by_level[r["level"]].append(r)
        return {
            "n": len(vals),
            "recall": {k: sum(r[tier][str(k)] for r in vals) / len(vals) for k in KS},
            "all_hit": {
                k: sum(r[f"{tier}_all"][str(k)] for r in vals) / len(vals) for k in KS
            },
            "by_level": {
                level: {
                    "n": len(sub),
                    "recall_at_15": sum(r[tier]["15"] for r in sub) / len(sub),
                    "all_at_15": sum(r[f"{tier}_all"]["15"] for r in sub) / len(sub),
                }
                for level, sub in sorted(by_level.items())
            },
        }

    def table_prf() -> dict[str, Any]:
        """Macro-averaged precision/recall/F2 over PRF_KS (table tier, skips
        questions with no gt_tables groups)."""
        vals = [r for r in rows if r.get("table_pr")]
        if not vals:
            return {}
        by_k = {}
        for k in PRF_KS:
            precisions = [r["table_pr"][str(k)][0] for r in vals]
            recalls = [r["table_pr"][str(k)][1] for r in vals]
            p = sum(precisions) / len(precisions)
            rc = sum(recalls) / len(recalls)
            by_k[k] = {"precision": p, "recall": rc, "f2": f2_score(p, rc)}
        return {"n": len(vals), "by_k": by_k}

    n_cands = sorted(r["n_cands"] for r in rows)
    return {
        "n_questions": len(rows),
        "candidates": {
            "median": n_cands[len(n_cands) // 2] if n_cands else 0,
            "max": max(n_cands) if n_cands else 0,
        },
        "pool_size": {
            "median": sorted(r["pool_size"] for r in rows)[len(rows) // 2] if rows else 0,
            "max": max((r["pool_size"] for r in rows), default=0),
        },
        "table": agg("table"),
        "report": agg("report"),
        "table_prf": table_prf(),
        "table_misses_at_15": [
            {"qid": r["qid"], "level": r["level"], "recall_at_15": r["table"]["15"]}
            for r in rows
            if r["table"] and r["table"]["15"] < 1.0
        ],
    }


def print_summary(stage: str, summary: dict[str, Any]) -> None:
    print(
        f"stage={stage}  candidates: med {summary['candidates']['median']}, "
        f"max {summary['candidates']['max']}  |  pool: med "
        f"{summary['pool_size']['median']}, max {summary['pool_size']['max']}"
    )
    for tier, label in (("table", "TABLE tier"), ("report", "REPORT tier")):
        block = summary[tier]
        if not block:
            continue
        print(f"\n{label}  (n={block['n']})")
        print("  K      recall   all-hit")
        for k in KS:
            print(f"  @{k:<5} {block['recall'][k]:6.1%}   {block['all_hit'][k]:6.1%}")
        print("  per level (recall@15 / all@15):")
        for level, sub in block["by_level"].items():
            print(
                f"    {level} (n={sub['n']}): "
                f"{sub['recall_at_15']:6.1%} / {sub['all_at_15']:6.1%}"
            )
    prf = summary["table_prf"]
    if prf:
        print(f"\nTABLE tier precision/recall/F2 (n={prf['n']}, macro-averaged)")
        print("  K      precision  recall    F2")
        for k in PRF_KS:
            m = prf["by_k"][k]
            print(f"  @{k:<5} {m['precision']:6.1%}   {m['recall']:6.1%}   {m['f2']:6.1%}")
        best_k = max(prf["by_k"], key=lambda k: prf["by_k"][k]["f2"])
        best = prf["by_k"][best_k]
        print(
            f"  best F2 @K={best_k}: P={best['precision']:.1%} R={best['recall']:.1%} "
            f"F2={best['f2']:.1%}"
        )

    if summary["table_misses_at_15"]:
        print("\ntable-tier misses @15:")
        for miss in sorted(summary["table_misses_at_15"], key=lambda m: m["recall_at_15"]):
            print(f"  #{miss['qid']} ({miss['level']}): recall {miss['recall_at_15']:.0%}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Measure recall@K of the retrieval stages on the eval set."
    )
    ap.add_argument(
        "--stage", default="rrf", choices=["filter", "bm25", "dense", "rrf", "judge"]
    )
    ap.add_argument("--channel-k", type=int, default=CHANNEL_K)
    ap.add_argument(
        "--no-strip", action="store_true", help="search with the raw question"
    )
    ap.add_argument(
        "--no-primary",
        action="store_true",
        help="do not add every shortlisted primary statement to the pool",
    )
    ap.add_argument(
        "--dense-backend",
        default="bge-m3",
        choices=list(EMBEDDING_BACKENDS),
        help="dense channel encoder; qwen3-4b needs its DeepInfra index built",
    )
    ap.add_argument(
        "--reranker",
        default=None,
        choices=list(RERANKER_BACKENDS),
        help="reorder the fused pool with a cross-encoder (default: off)",
    )
    ap.add_argument(
        "--judge-top-n",
        type=int,
        default=None,
        help="show the judge only the top N of the pool (default: the whole pool)",
    )
    ap.add_argument("--no-thinking", action="store_true", help="judge without thinking")
    ap.add_argument("--output", type=Path, help="write per-question JSONL + summary here")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stage = args.stage

    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    retriever = CandidateRetriever(
        channel_k=args.channel_k,
        use_bm25=stage in ("bm25", "rrf", "judge"),
        use_dense=stage in ("dense", "rrf", "judge"),
        expand_primary=not args.no_primary,
        strip_query=not args.no_strip,
        load_judge_text=stage == "judge",
        dense_backend=args.dense_backend,
        # `filter` has no ranking to reorder, so a reranker there would only cost money.
        reranker=args.reranker if stage != "filter" else None,
        judge_top_n=args.judge_top_n,
    )

    started = time.perf_counter()
    pools = retriever.build_pools(evalset)

    rows = []
    for question, pool in zip(evalset, pools):
        ranked = pool.ranked
        picks: list[str] = []
        if stage == "judge":
            selection = retriever.select(
                question, pool, thinking=not args.no_thinking
            )
            picks = selection["picks"]
            ranked = selection["ranked"]
            print(
                f"  #{question['qid']}: pool {len(pool.ranked)}, picked {len(picks)}",
                flush=True,
            )

        ranked_reports = dedupe_reports(ranked)
        row: dict[str, Any] = {
            "qid": question["qid"],
            "level": question["level"][:2],
            "query": pool.query,
            "n_cands": len(pool.keys),
            "pool_size": len(pool.ranked),
            "picks": picks,
            "table": {}, "report": {}, "table_all": {}, "report_all": {},
        }
        for k in KS:
            recall, all_hit = recall_at_k(ranked_reports, question["gt_reports"], k)
            row["report"][str(k)] = recall
            row["report_all"][str(k)] = all_hit
            if question["gt_tables"]:
                recall, all_hit = recall_at_k(ranked, question["gt_tables"], k)
                row["table"][str(k)] = recall
                row["table_all"][str(k)] = all_hit
        if question["gt_tables"]:
            row["table_pr"] = {
                str(k): precision_recall_at_k(ranked, question["gt_tables"], k)
                for k in PRF_KS
            }
        rows.append(row)

    elapsed = time.perf_counter() - started
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "channel_k": args.channel_k,
        "strip_query": not args.no_strip,
        "expand_primary": not args.no_primary,
        "dense_backend": args.dense_backend,
        "reranker": args.reranker,
        "judge_top_n": args.judge_top_n,
        "thinking": stage == "judge" and not args.no_thinking,
        "elapsed_seconds": round(elapsed, 1),
        **score_rows(rows),
    }
    print_summary(stage, summary)

    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary_path = output.with_suffix(".summary.json")
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {output}\nwrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
