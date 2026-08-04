"""Build per-table doc_text for retrieval indexing.

One row per table: doc_text = statement_label | note_title | section_title |
first_col_labels (joined) | header_flat.

Per docs/v0_retrieval_pipeline.md (Q5+Q6, finalized 2026-08-03):
context_page_text is deliberately excluded — it has OCR noise, may contain
cell values, and isn't needed for retrieval routing.

The design doc originally also listed `parent_section`; that field does not
exist in tables_metadata_v2.jsonl (schema audit over all 146,246 records), so
it is dropped rather than joined in as an empty segment.

`statement_label` was added after measuring the eval set. A primary statement is
not a "note", so it has no `note_title`, and 4,696 balance sheets have no
`section_title` either: their doc_text used to open on raw row labels ("C. NỢ
PHẢI TRẢ I. Nợ ngắn hạn 1. Phải trả người bán…") with nothing saying what the
table *is*. 11 of the 13 GT tables in the eval set are such statements, and they
lost to short note tables that happened to repeat the queried line item. The
label is emitted only for non-note statement types (~19k of 146k tables): adding
a constant string to the 124,279 `note` rows would carry no information, and
would burn the same 30 chars in every candidate the LLM judge reads.

Run:
  .venv_bge/bin/python scripts/build_doc_text.py [--limit N]

Output:
  data/indexes/tables_doc_text.parquet  (report_id, table_pos, doc_text)
"""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd

from finance_qa.paths import DOCUMENT_TEXT_PATH, TABLE_METADATA_PATH


METADATA_PATH = TABLE_METADATA_PATH
PARQUET_PATH = DOCUMENT_TEXT_PATH


# Vietnamese names, because that is what the questions are written in and what
# the encoder and the judge see. `note` is deliberately absent (see module docs);
# so is `unknown`, which would assert something we don't know.
STATEMENT_LABELS = {
    "balance_sheet": "BẢNG CÂN ĐỐI KẾ TOÁN",
    "income_statement": "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH",
    "cash_flow": "BÁO CÁO LƯU CHUYỂN TIỀN TỆ",
    "equity_change": "BÁO CÁO THAY ĐỔI VỐN CHỦ SỞ HỮU",
    "entity_info": "THÔNG TIN DOANH NGHIỆP",
}

# Balance sheets are split across pages often enough (1,715 + 1,321 tables) that
# which half you are looking at is the whole question for a liabilities query.
SUBTYPE_LABELS = {
    "bs_assets": "phần TÀI SẢN",
    "bs_liabilities_equity": "phần NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU",
}


def statement_label(rec: dict) -> str:
    label = STATEMENT_LABELS.get(rec.get("statement_type") or "", "")
    if not label:
        return ""
    subtype = SUBTYPE_LABELS.get(rec.get("statement_subtype") or "", "")
    return f"{label} — {subtype}" if subtype else label


def build_doc_text(rec: dict) -> str:
    parts = [
        statement_label(rec),
        rec.get("note_title") or "",
        rec.get("section_title") or "",
        " ".join(rec.get("first_col_labels") or []),
        rec.get("header_flat") or "",
    ]
    # Skip empty segments: a leading " |  | " is pure noise for the dense encoder.
    return " | ".join(p for p in parts if p.strip())


def build_judge_text(rec: dict) -> str:
    """Narrower view for the LLM judge prompt.

    Retrieval and the judge want different things out of the same row, so they get
    different views rather than one flat string:

    - `section_title` is boilerplate. Its top values are "THUYẾT MINH BÁO CÁO TÀI
      CHÍNH HỢP NHẤT (tiếp theo)" and spelling variants; it says only which
      *report* the table came from, which the judge already reads off `report_id`,
      and which the hard filter has already guaranteed. 8.1% of the prompt.
    - `header_flat` is the period columns ("Số cuối năm / Số đầu năm"), identical
      for nearly every table in a report, so it cannot discriminate between them.
      14.0% of the prompt.

    Together 22% of the judge's context for no signal -- and the prompt overflows
    the 32k window on large reports (a 131-candidate pool hit 32,775 tokens and
    the call 400'd, silently costing a question whose GT sat at pool position 0).

    Both fields stay in `doc_text` for the index: BM25 discounts the boilerplate
    by IDF anyway, and dropping `header_flat` measurably *lost* retrieval
    (intra-report top5 72.2% -> 63.9%, diag_repr.py).
    """
    parts = [
        statement_label(rec),
        rec.get("note_title") or "",
        " ".join(rec.get("first_col_labels") or []),
    ]
    return " | ".join(p for p in parts if p.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Debug: cap number of records")
    args = ap.parse_args()

    t0 = time.perf_counter()
    records: list[dict] = []
    with METADATA_PATH.open(encoding="utf-8") as fp:
        for i, line in enumerate(fp):
            if args.limit and i >= args.limit:
                break
            rec = json.loads(line)
            records.append({
                "report_id": rec["report_id"],
                "table_pos": rec["table_pos"],
                "doc_text": build_doc_text(rec),
                "judge_text": build_judge_text(rec),
            })

    df = pd.DataFrame.from_records(records)
    print(f"Built doc_text for {len(df):,} tables")

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET_PATH, index=False, compression="snappy")
    elapsed = time.perf_counter() - t0
    print(f"Wrote {PARQUET_PATH} ({PARQUET_PATH.stat().st_size / 1e6:.1f} MB) in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
