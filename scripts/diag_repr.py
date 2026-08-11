"""Compare table-metadata representations on the metric that actually matters now.

Report retrieval is already 100%, so the whole remaining problem is "which table
inside a report we have already found". This scores exactly that: intra-report
rank of each GT table among its own siblings. No LLM, no re-embedding -- BM25 is
rebuilt per variant, which is seconds.

Variants test two independent axes:

  representation -- what text we index per table
  query          -- what text we search with

The query axis exists because the hard filter has already consumed ticker + year:
every candidate is guaranteed to be the right company and the right year, so the
company name in the question is pure noise, and it specifically boosts the
entity_info / "THÔNG TIN DOANH NGHIỆP" tables that repeat that name verbatim.

  .venv_bge/bin/python scripts/diag_repr.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

import _bootstrap  # noqa: F401

from finance_qa.evaluation.retrieval import EVALSET_PATH
from finance_qa.modules.data.preprocessing.document_text import statement_label
from finance_qa.modules.rag.indexing.bm25 import BM25
from finance_qa.modules.rag.candidates import strip_entity
from finance_qa.modules.rag.retrievers.filters import index_by_ticker_year, load_tables, shortlist


def repr_full(rec: dict) -> str:
    """Current production doc_text."""
    parts = [
        statement_label(rec),
        rec.get("note_title") or "",
        rec.get("section_title") or "",
        " ".join(rec.get("first_col_labels") or []),
        rec.get("header_flat") or "",
    ]
    return " | ".join(p for p in parts if p.strip())


def repr_title(rec: dict) -> str:
    """Titles only -- no row-label soup, no header."""
    parts = [statement_label(rec), rec.get("note_title") or "",
             rec.get("section_title") or ""]
    return " | ".join(p for p in parts if p.strip())


def repr_title_rows(rec: dict) -> str:
    """Titles + row labels, but no header_flat (period columns are the same for
    every table in a report, so they can only add noise)."""
    parts = [statement_label(rec), rec.get("note_title") or "",
             rec.get("section_title") or "",
             " ".join(rec.get("first_col_labels") or [])]
    return " | ".join(p for p in parts if p.strip())


VARIANTS = {"full": repr_full, "title": repr_title, "title+rows": repr_title_rows}


def main() -> int:
    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    tables = load_tables()
    index = index_by_ticker_year(tables)
    by_key = {f"{t['report_id']}|{t['table_pos']}": t for t in tables}
    by_report: dict[str, list[str]] = defaultdict(list)
    for k, t in by_key.items():
        by_report[t["report_id"]].append(k)

    names_by_ticker: dict[str, set[str]] = defaultdict(set)
    for t in tables:
        for tok in re.findall(r"\w+", (t.get("company_name") or "").lower()):
            names_by_ticker[t["ticker"]].add(tok)

    # Precompute the per-question shortlist once; it is variant-independent.
    work = []
    for e in evalset:
        if not e["gt_tables"]:
            continue
        cands = shortlist(e, index, all_tables=tables)
        pool = {f"{t['report_id']}|{t['table_pos']}" for t in cands}
        names = set().union(*(names_by_ticker[t] for t in e["tickers"])) if e["tickers"] else set()
        work.append((e, pool, strip_entity(e["question"], names)))

    for vname, fn in VARIANTS.items():
        texts = {k: fn(t) for k, t in by_key.items()}
        bm25 = BM25(texts)
        for qname in ("raw", "stripped"):
            ranks, oracle_ranks = [], []
            for e, pool, stripped in work:
                q = e["question"] if qname == "raw" else stripped
                for g in e["gt_tables"]:
                    gt = next((m for m in g if m in pool), None)
                    if gt is None:
                        continue
                    sibs = [k for k in by_report[gt.rsplit("|", 1)[0]] if k in pool]
                    ranked = [k for k, _ in bm25.top_k(q, sibs, k=len(sibs))]
                    ranks.append(ranked.index(gt) + 1)
                    # Oracle: how good would it get if a query classifier told us
                    # the statement_type? Upper bound on statement-type routing.
                    st = by_key[gt]["statement_type"]
                    same = [k for k in sibs if by_key[k]["statement_type"] == st]
                    o = [k for k, _ in bm25.top_k(q, same, k=len(same))]
                    oracle_ranks.append(o.index(gt) + 1)
            n = len(ranks)
            def s(rs):
                rs = sorted(rs)
                return (f"top1 {sum(r == 1 for r in rs) / n:5.1%}  "
                        f"top3 {sum(r <= 3 for r in rs) / n:5.1%}  "
                        f"top5 {sum(r <= 5 for r in rs) / n:5.1%}  med #{rs[n // 2]:>2}")
            print(f"{vname:11} {qname:9} {s(ranks)}   | +oracle_type {s(oracle_ranks)}")
    print(f"\n(n={len(ranks)} GT groups, intra-report rank among siblings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
