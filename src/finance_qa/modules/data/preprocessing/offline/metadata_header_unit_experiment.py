"""Build `tables_metadata_v3.jsonl`: re-derive `header_flat` + a new `unit` field.

Staging artifact for the experiment in `docs/retrieval_preprocessing_2026-08-21.md` §3.1/§6.
Reads the existing `tables_metadata_v2.jsonl` row by row and, for every row, re-parses that
table's *raw* HTML (via `grid.expand_table` + `header_flatten.flatten_header`) instead of
trusting the v2 `header_flat`, which came from a naive, span-blind CSV extraction
(`extract_tables.py`). Every other field is copied through unchanged.

Does not touch `tables_metadata_v2.jsonl` (`DECISIONS.md` §8: protected artifact, rebuilds go
through staging paths). Writes exactly as many rows, in exactly the same
`(report_id, table_pos)` order, as the v2 file it reads -- verified after the fact, not just
assumed, by `verify_order`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from finance_qa.core.paths import FINANCIAL_STATEMENTS_DIR, METADATA_DIR, TABLE_METADATA_PATH
from finance_qa.modules.data.preprocessing.offline.grid import expand_table
from finance_qa.modules.data.preprocessing.offline.header_flatten import flatten_header
from finance_qa.modules.data.preprocessing.offline.metadata_enrichment import report_id_to_ocr_path


EXPECTED_ROWS = 146_246

TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_OPEN_TAG_RE = re.compile(r"^<table[^>]*>", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"</table>$", re.IGNORECASE)


@dataclass(frozen=True)
class MetadataV3Paths:
    meta_v2_path: Path = TABLE_METADATA_PATH
    meta_v3_path: Path = METADATA_DIR / "tables_metadata_v3.jsonl"
    statements_dir: Path = FINANCIAL_STATEMENTS_DIR


def table_inner_htmls(text: str) -> list[str]:
    """Inner HTML (the part between the tags) of every `<table>` in a report, in the same
    file order `extract_tables.py` uses to assign `table_pos` (1-based, ordinal)."""
    out = []
    for m in TABLE_PATTERN.finditer(text):
        raw = m.group(0)
        inner = _CLOSE_TAG_RE.sub("", _OPEN_TAG_RE.sub("", raw))
        out.append(inner)
    return out


def verify_order(v2_path: Path, v3_path: Path) -> None:
    """Hard check, not an assumption: the two files carry the same (report_id, table_pos)
    sequence, row for row."""

    def keys(path: Path):
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                rec = json.loads(line)
                yield (rec["report_id"], rec["table_pos"])

    for i, (a, b) in enumerate(zip(keys(v2_path), keys(v3_path))):
        if a != b:
            raise AssertionError(f"row {i}: v2 key {a} != v3 key {b}")


class MetadataV3Builder:
    """Rebuild `header_flat` + `unit` for every row of the v2 metadata file."""

    def __init__(self, paths: MetadataV3Paths | None = None) -> None:
        self.paths = paths or MetadataV3Paths()

    def run(self, limit: int | None = None) -> int:
        t0 = time.perf_counter()
        self.paths.meta_v3_path.parent.mkdir(parents=True, exist_ok=True)

        cur_report: str | None = None
        cur_tables: list[str] = []
        n_total = 0
        n_fallback = 0

        with self.paths.meta_v2_path.open(encoding="utf-8") as fin, self.paths.meta_v3_path.open(
            "w", encoding="utf-8"
        ) as fout:
            for line in fin:
                if limit and n_total >= limit:
                    break
                rec = json.loads(line)
                n_total += 1
                rid = rec["report_id"]
                tpos = rec["table_pos"]

                if rid != cur_report:
                    cur_report = rid
                    ocr_path = report_id_to_ocr_path(rid, self.paths.statements_dir)
                    cur_tables = table_inner_htmls(
                        ocr_path.read_text(encoding="utf-8", errors="replace")
                    ) if ocr_path.exists() else []

                idx = tpos - 1
                if 0 <= idx < len(cur_tables):
                    grid = expand_table(cur_tables[idx])
                    header_flat, unit = flatten_header(grid)
                else:
                    # OCR file missing or table_pos out of range for this report: keep the
                    # v2 header rather than silently emptying a row we cannot re-derive.
                    n_fallback += 1
                    header_flat, unit = rec.get("header_flat", ""), ""

                rec["header_flat"] = header_flat
                rec["unit"] = unit
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

                if n_total % 20000 == 0:
                    print(f"  [{n_total:,}] processed")

        elapsed = time.perf_counter() - t0
        print(
            f"Done: {n_total:,} rows in {elapsed:.1f}s "
            f"({n_fallback} fell back to the v2 header: OCR file missing or table_pos mismatch)"
        )

        if limit is None:
            if n_total != EXPECTED_ROWS:
                raise AssertionError(f"expected {EXPECTED_ROWS:,} rows, wrote {n_total:,}")
            verify_order(self.paths.meta_v2_path, self.paths.meta_v3_path)
            print("verified: v3 row count and (report_id, table_pos) order match v2")
        return 0

    async def arun(self, limit: int | None = None) -> int:
        return await asyncio.to_thread(self.run, limit)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Debug: cap number of rows read")
    args = ap.parse_args(argv)
    return MetadataV3Builder().run(limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
