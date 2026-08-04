"""Verify the two fixes diag_repr.py pointed at, on real union-pool recall.

diag_repr showed the loss is concentrated on primary-statement questions:
balance_sheet GT lands in its own report's top-3 only 18.2% of the time, because
the balance sheet is ~5% of a report's tables and the ~71% that are notes drown
it. Restricting to the right statement_type takes that to 100%.

Two ways to act on that, both tested here:

  strip   -- drop ticker / year / company-name tokens from the retrieval query.
             The hard filter already consumed them, so they only serve to boost
             the entity_info tables that repeat the company name.
  primary -- unconditionally add every balance_sheet / income_statement /
             cash_flow / equity_change table of every shortlisted report to the
             pool. No query classifier needed: the primary statements are ~10%
             of a report, so this is cheap, and it makes primary-statement recall
             structurally 100% instead of hoping BM25 ranks them.

Pool recall is the judge's ceiling, so this is the number that matters.

  .venv_bge/bin/python scripts/diag_pool_variants.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from diag_repr import strip_entity
from finance_qa.evaluation.retrieval import DENSE_PATH, EVALSET_PATH, recall_at_k
from finance_qa.paths import DOCUMENT_TEXT_PATH
from finance_qa.retrieval.bm25 import BM25, load_doc_texts
from finance_qa.retrieval.dense import encode_queries, load_model
from finance_qa.retrieval.filters import index_by_ticker_year, load_tables, shortlist

PRIMARY = {"balance_sheet", "income_statement", "cash_flow", "equity_change"}
CHANNEL_K = 50


def main() -> int:
    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    tables = load_tables()
    index = index_by_ticker_year(tables)
    by_key = {f"{t['report_id']}|{t['table_pos']}": t for t in tables}
    doc_texts = load_doc_texts()
    bm25 = BM25(doc_texts)

    vecs = np.load(DENSE_PATH)
    meta = pd.read_parquet(DOCUMENT_TEXT_PATH)
    row_of = {f"{r}|{p}": i
              for i, (r, p) in enumerate(zip(meta["report_id"], meta["table_pos"]))}
    tok, model = load_model()

    names = defaultdict(set)
    for t in tables:
        for w in re.findall(r"\w+", (t.get("company_name") or "").lower()):
            names[t["ticker"]].add(w)

    tbl = [e for e in evalset if e["gt_tables"]]
    shortlists = [[f"{t['report_id']}|{t['table_pos']}"
                   for t in shortlist(e, index, all_tables=tables)] for e in tbl]
    queries = {
        "raw": [e["question"] for e in tbl],
        "strip": [strip_entity(e["question"],
                               set().union(*(names[t] for t in e["tickers"]))
                               if e["tickers"] else set()) for e in tbl],
    }
    qvecs = {k: encode_queries(v, tok, model) for k, v in queries.items()}

    for qname in ("raw", "strip"):
        for primary in (False, True):
            rec = allh = 0.0
            sizes = []
            for qi, (e, keys) in enumerate(zip(tbl, shortlists)):
                bm = [k for k, _ in bm25.top_k(queries[qname][qi], keys, k=CHANNEL_K)]
                idx = np.array([row_of[k] for k in keys])
                sims = vecs[idx].astype(np.float32) @ qvecs[qname][qi].astype(np.float32)
                dn = [keys[i] for i in np.argsort(-sims)[:CHANNEL_K]]
                pool = list(dict.fromkeys(bm + dn))
                if primary:
                    extra = [k for k in keys
                             if by_key[k]["statement_type"] in PRIMARY and k not in set(pool)]
                    pool += extra
                sizes.append(len(pool))
                r, a = recall_at_k(pool, e["gt_tables"], 10**9)
                rec += r / len(tbl)
                allh += a / len(tbl)
            sizes.sort()
            tag = f"{qname} + primary" if primary else qname
            print(f"{tag:16} pool recall {rec:5.1%}  all-hit {allh:5.1%}  "
                  f"| pool med {sizes[len(sizes) // 2]}, max {sizes[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
