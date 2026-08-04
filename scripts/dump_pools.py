"""Cache the retrieval pools for the eval set, so judge experiments cost only LLM calls.

Everything upstream of the judge is deterministic and takes ~2 min (BM25 build +
dense load + GPU query encode). Dumping it once means judge_ab.py can try a dozen
prompt variants without touching the GPU.

Also prints **union pool recall**, which is the judge's ceiling: the judge can only
pick what is in the pool, so no prompt work can beat this number.

The pool policy itself lives in `finance_qa.retrieval.candidates` (shared with the
evaluator and the batch runner); this script only caches its output.

  .venv_bge/bin/python scripts/dump_pools.py [--channel-k 50]

Output: /tmp/pools.json  (not in the repo -- it is a cache, and it goes stale the
moment doc_text or the dense index is rebuilt)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from finance_qa.evaluation.retrieval import recall_at_k
from finance_qa.paths import EVALSET_PATH
from finance_qa.retrieval.candidates import CHANNEL_K, CandidateRetriever

POOLS_PATH = Path("/tmp/pools.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-k", type=int, default=CHANNEL_K)
    ap.add_argument("--no-primary", action="store_true")
    ap.add_argument("--no-strip", action="store_true")
    args = ap.parse_args()

    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    retriever = CandidateRetriever(
        channel_k=args.channel_k,
        expand_primary=not args.no_primary,
        strip_query=not args.no_strip,
        load_judge_text=True,
    )
    built = retriever.build_pools(evalset)

    pools = [
        {
            "qid": e["qid"],
            "level": e["level"],
            "question": e["question"],
            "query": pool.query,
            "gt_tables": e["gt_tables"],
            "gt_reports": e["gt_reports"],
            "bm25": pool.rankings.get("bm25", []),
            "dense": pool.rankings.get("dense", []),
            "rrf": pool.ranked,
            "n_cands": len(pool.keys),
            # judge_ab.py's key name for the text the judge reads, which is the
            # narrow judge_text view, not the indexed doc_text.
            "doc_text": dict(retriever.judge_items(pool)),
        }
        for e, pool in zip(evalset, built)
    ]

    POOLS_PATH.write_text(json.dumps(pools, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {POOLS_PATH} ({POOLS_PATH.stat().st_size / 1e6:.1f} MB), "
          f"channel_k={args.channel_k}")

    tbl = [p for p in pools if p["gt_tables"]]
    sizes = sorted(len(p["rrf"]) for p in tbl)
    rec = sum(recall_at_k(p["rrf"], p["gt_tables"], 10**9)[0] for p in tbl) / len(tbl)
    allh = sum(recall_at_k(p["rrf"], p["gt_tables"], 10**9)[1] for p in tbl) / len(tbl)
    print(f"union pool: size med {sizes[len(sizes) // 2]}, max {sizes[-1]}")
    print(f"POOL RECALL (judge ceiling): {rec:.1%} recall, {allh:.1%} all-hit")
    for p in tbl:
        r = recall_at_k(p["rrf"], p["gt_tables"], 10**9)[0]
        if r < 1.0:
            missing = [g[0] for g in p["gt_tables"] if not any(m in p["rrf"] for m in g)]
            print(f"  #{p['qid']} ({p['level'][:2]}) {r:.0%} -- absent: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
