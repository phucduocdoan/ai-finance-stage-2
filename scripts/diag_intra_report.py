"""Diagnostic: is the remaining error an *intra-report* table-selection problem?

The report tier scores 100% at every K, so the hard filter already nails "which
document". That means every point we are still losing is lost picking a table
*inside* a report we already found. This script measures exactly that: for each GT
table, rank only the tables of its own report and report where the GT lands, plus
what outranked it.

If the GT ranks badly among its own siblings, the doc_text representation is the
problem. If it ranks well intra-report but badly in the full pool, the problem is
cross-report interference (multi-year / multi-ticker questions).

  .venv_bge/bin/python scripts/diag_intra_report.py
"""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from finance_qa.evaluation.retrieval import DENSE_PATH, EVALSET_PATH
from finance_qa.core.paths import DOCUMENT_TEXT_PATH
from finance_qa.modules.rag.indexing.bm25 import BM25, load_doc_texts
from finance_qa.modules.rag.indexing.dense import encode_queries, load_model
from finance_qa.modules.rag.retrievers.filters import index_by_ticker_year, load_tables, shortlist


def main() -> int:
    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    tables = load_tables()
    index = index_by_ticker_year(tables)
    doc_texts = load_doc_texts()
    bm25 = BM25(doc_texts)

    vecs = np.load(DENSE_PATH)
    meta = pd.read_parquet(DOCUMENT_TEXT_PATH)
    row_of = {
        f"{r}|{p}": i
        for i, (r, p) in enumerate(zip(meta["report_id"], meta["table_pos"]))
    }
    tok, model = load_model()
    qvecs = encode_queries([e["question"] for e in evalset], tok, model)

    by_report: dict[str, list[str]] = defaultdict(list)
    for t in tables:
        by_report[t["report_id"]].append(f"{t['report_id']}|{t['table_pos']}")

    stats = {"bm25": [], "dense": []}
    for qi, e in enumerate(evalset):
        if not e["gt_tables"]:
            continue
        cands = shortlist(e, index, all_tables=tables)
        pool_keys = {f"{t['report_id']}|{t['table_pos']}" for t in cands}
        print(f"\n#{e['qid']} ({e['level'][:2]}) {e['question'][:88]}")

        for g in e["gt_tables"]:
            gt = next((m for m in g if m in pool_keys), None)
            if gt is None:
                print(f"   {g[0]}: GT ngoài shortlist")
                continue
            sibs = [k for k in by_report[gt.rsplit("|", 1)[0]] if k in pool_keys]
            n = len(sibs)

            bm_rank = [k for k, _ in bm25.top_k(e["question"], sibs, k=n)]
            idx = np.array([row_of[k] for k in sibs])
            sims = vecs[idx].astype(np.float32) @ qvecs[qi].astype(np.float32)
            dn_rank = [sibs[i] for i in np.argsort(-sims)]

            rb, rd = bm_rank.index(gt) + 1, dn_rank.index(gt) + 1
            stats["bm25"].append(rb)
            stats["dense"].append(rd)
            print(f"   {gt}  ({n} bảng cùng report)  bm25 #{rb}  dense #{rd}")
            for k in bm_rank[: rb - 1][:3]:
                print(f"      bm25 trên nó: {k.rsplit('|', 1)[1]:>4}  {doc_texts[k][:110]}")

    for name, ranks in stats.items():
        ranks.sort()
        top1 = sum(r == 1 for r in ranks) / len(ranks)
        top3 = sum(r <= 3 for r in ranks) / len(ranks)
        print(f"\n{name:5} intra-report: top1 {top1:.1%}  top3 {top3:.1%}  "
              f"med #{ranks[len(ranks) // 2]}  max #{ranks[-1]}  (n={len(ranks)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
