"""Extract all <table> blocks from OCR-extracted financial reports.

Reads every *_extracted.txt under ViFinQA/financial_statements/, finds each
<table>...</table> block, and writes a CSV per table preserving the raw
row/column structure. Also emits an index (JSONL), stats (Markdown), and an
error log.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

from bs4 import BeautifulSoup

import _bootstrap  # noqa: F401

from finance_qa.paths import (
    DATA_DIR,
    FINANCIAL_STATEMENTS_DIR,
    METADATA_DIR,
    REPORTS_DIR,
    TABLES_DIR,
)


STATEMENTS_DIR = FINANCIAL_STATEMENTS_DIR
OUTPUT_DIR = DATA_DIR
INDEX_PATH = METADATA_DIR / "tables_index.jsonl"
STATS_PATH = REPORTS_DIR / "extract_stats.md"
ERROR_LOG_PATH = REPORTS_DIR / "extract_errors.log"

TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
PAGE_PATTERN = re.compile(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", re.IGNORECASE)


@dataclass
class TableRecord:
    report_id: str
    table_pos: int
    csv_path: str
    page_number: int | None
    num_rows: int
    num_cols: int
    header_preview: str
    parse_status: str


def find_ocr_files() -> list[Path]:
    return sorted(STATEMENTS_DIR.glob("*/*/*/*_extracted.txt"))


def report_id_from_path(path: Path) -> str:
    return path.stem.removesuffix("_extracted")


def build_page_index(text: str) -> list[tuple[int, int]]:
    """Return list of (char_offset, page_number) sorted by offset."""
    return [(m.start(), int(m.group(1))) for m in PAGE_PATTERN.finditer(text)]


def page_for_offset(pages: list[tuple[int, int]], offset: int) -> int | None:
    """Find the page whose marker precedes the given offset."""
    if not pages:
        return None
    lo, hi = 0, len(pages) - 1
    result: int | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if pages[mid][0] <= offset:
            result = pages[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def parse_table_html(html: str) -> tuple[list[list[str]], str]:
    """Parse a <table> block into rows. Returns (rows, status)."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return [], "error"

    table = soup.find("table")
    if table is None:
        return [], "malformed_html"

    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        row = [cell.get_text(" ", strip=True) for cell in cells]
        rows.append(row)

    if not rows:
        return [], "empty"

    max_cols = max(len(r) for r in rows)
    if max_cols == 0:
        return [], "empty"

    normalized = [r + [""] * (max_cols - len(r)) for r in rows]
    return normalized, "ok"


def header_preview_of(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    first = " | ".join(cell for cell in rows[0] if cell)
    if len(first) > 200:
        first = first[:200] + "..."
    return first


def write_csv(csv_path: Path, rows: list[list[str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerows(rows)


def process_file(
    path: Path,
    errors: list[str],
) -> list[TableRecord]:
    report_id = report_id_from_path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        errors.append(f"{report_id}\tREAD_ERROR\t{exc}")
        return []

    pages = build_page_index(text)
    records: list[TableRecord] = []

    for pos, match in enumerate(TABLE_PATTERN.finditer(text), start=1):
        html = match.group(0)
        rows, status = parse_table_html(html)
        page = page_for_offset(pages, match.start())

        csv_rel = Path("tables") / report_id / f"table_{pos}.csv"
        csv_abs = OUTPUT_DIR / csv_rel

        if rows:
            write_csv(csv_abs, rows)
        else:
            # Still create an empty CSV to keep path valid; downstream can
            # detect emptiness via parse_status/num_rows.
            csv_abs.parent.mkdir(parents=True, exist_ok=True)
            csv_abs.write_text("", encoding="utf-8")

        num_rows = len(rows)
        num_cols = len(rows[0]) if rows else 0

        if status != "ok":
            errors.append(
                f"{report_id}\ttable_{pos}\t{status}\tpage={page}"
            )

        records.append(
            TableRecord(
                report_id=report_id,
                table_pos=pos,
                csv_path=str(csv_rel),
                page_number=page,
                num_rows=num_rows,
                num_cols=num_cols,
                header_preview=header_preview_of(rows),
                parse_status=status,
            )
        )

    return records


def write_stats_md(records: list[TableRecord], num_files: int, elapsed: float) -> None:
    total_tables = len(records)
    status_counts = Counter(r.parse_status for r in records)
    per_report = Counter(r.report_id for r in records)

    tables_per_report = sorted(per_report.values())
    reports_with_tables = len(per_report)
    reports_without_tables = num_files - reports_with_tables

    def pct(n: int) -> str:
        return f"{100.0 * n / total_tables:.1f}%" if total_tables else "0%"

    def percentile(sorted_values: list[int], p: float) -> int:
        if not sorted_values:
            return 0
        k = max(0, min(len(sorted_values) - 1, int(round((p / 100) * (len(sorted_values) - 1)))))
        return sorted_values[k]

    row_counts = sorted(r.num_rows for r in records if r.parse_status == "ok")
    col_counts = sorted(r.num_cols for r in records if r.parse_status == "ok")

    lines = [
        "# Thống kê extract bảng",
        "",
        f"- Số file OCR đã xử lý: **{num_files:,}**",
        f"- Tổng số bảng trích được: **{total_tables:,}**",
        f"- Report có ít nhất 1 bảng: **{reports_with_tables:,}**",
        f"- Report không có bảng nào: **{reports_without_tables:,}**",
        f"- Thời gian chạy: **{elapsed:.1f}s**",
        "",
        "## Phân bố trạng thái parse",
        "",
        "| Trạng thái | Số bảng | Tỉ lệ |",
        "|---|---:|---:|",
    ]
    for status, count in status_counts.most_common():
        lines.append(f"| `{status}` | {count:,} | {pct(count)} |")

    lines += [
        "",
        "## Phân bố số bảng / report",
        "",
        f"- Min: {min(tables_per_report) if tables_per_report else 0}",
        f"- p50: {percentile(tables_per_report, 50)}",
        f"- p90: {percentile(tables_per_report, 90)}",
        f"- p99: {percentile(tables_per_report, 99)}",
        f"- Max: {max(tables_per_report) if tables_per_report else 0}",
        "",
        "## Phân bố kích thước bảng (chỉ tính bảng `ok`)",
        "",
        f"- Số dòng — p50: {percentile(row_counts, 50)}, p90: {percentile(row_counts, 90)}, max: {row_counts[-1] if row_counts else 0}",
        f"- Số cột — p50: {percentile(col_counts, 50)}, p90: {percentile(col_counts, 90)}, max: {col_counts[-1] if col_counts else 0}",
        "",
        "## Ghi chú",
        "",
        "- `page_number` là số trang xuất hiện trong marker `===== PAGE N =====` gần nhất trước bảng.",
        "- Schema CSV giữ nguyên rows/cols từ HTML gốc, không normalize header.",
        "- Bảng lỗi/rỗng vẫn được ghi CSV (file rỗng) để giữ liên kết `csv_path` hợp lệ.",
    ]

    STATS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    files = find_ocr_files()
    if not files:
        print(f"No OCR files found under {STATEMENTS_DIR}", file=sys.stderr)
        return 1

    print(f"Processing {len(files)} OCR files...")
    started = time.time()

    all_records: list[TableRecord] = []
    errors: list[str] = []

    with INDEX_PATH.open("w", encoding="utf-8") as index_fp:
        for i, path in enumerate(files, start=1):
            records = process_file(path, errors)
            for rec in records:
                index_fp.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
                all_records.append(rec)
            if i % 100 == 0 or i == len(files):
                print(
                    f"  [{i}/{len(files)}] {len(all_records):,} tables, "
                    f"{len(errors)} issues"
                )

    elapsed = time.time() - started

    ERROR_LOG_PATH.write_text(
        "\n".join(errors) + ("\n" if errors else ""), encoding="utf-8"
    )
    write_stats_md(all_records, num_files=len(files), elapsed=elapsed)

    print(f"Done in {elapsed:.1f}s. {len(all_records):,} tables, {len(errors)} issues.")
    print(f"Index:  {INDEX_PATH}")
    print(f"Stats:  {STATS_PATH}")
    print(f"Errors: {ERROR_LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
