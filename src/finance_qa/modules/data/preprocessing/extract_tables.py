"""Extract OCR HTML tables into raw CSV files and table index metadata."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from finance_qa.core.paths import (
    DATA_DIR,
    FINANCIAL_STATEMENTS_DIR,
    METADATA_DIR,
    REPORTS_DIR,
    TABLES_DIR,
)


TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
PAGE_PATTERN = re.compile(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", re.IGNORECASE)


@dataclass(frozen=True)
class TableExtractionPaths:
    statements_dir: Path = FINANCIAL_STATEMENTS_DIR
    output_dir: Path = DATA_DIR
    metadata_dir: Path = METADATA_DIR
    reports_dir: Path = REPORTS_DIR
    tables_dir: Path = TABLES_DIR
    index_path: Path = METADATA_DIR / "tables_index.jsonl"
    stats_path: Path = REPORTS_DIR / "extract_stats.md"
    error_log_path: Path = REPORTS_DIR / "extract_errors.log"


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


class TableExtractor:
    """File-backed table extraction service for OCR reports."""

    def __init__(self, paths: TableExtractionPaths | None = None) -> None:
        self.paths = paths or TableExtractionPaths()

    def prepare_outputs(self) -> None:
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
        self.paths.tables_dir.mkdir(parents=True, exist_ok=True)

    def find_ocr_files(self) -> list[Path]:
        return sorted(self.paths.statements_dir.glob("*/*/*/*_extracted.txt"))

    @staticmethod
    def report_id_from_path(path: Path) -> str:
        return path.stem.removesuffix("_extracted")

    @staticmethod
    def build_page_index(text: str) -> list[tuple[int, int]]:
        return [(m.start(), int(m.group(1))) for m in PAGE_PATTERN.finditer(text)]

    @staticmethod
    def page_for_offset(pages: list[tuple[int, int]], offset: int) -> int | None:
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

    @staticmethod
    def parse_table_html(html: str) -> tuple[list[list[str]], str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("Table extraction requires beautifulsoup4 to be installed") from exc

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
            rows.append([cell.get_text(" ", strip=True) for cell in cells])

        if not rows:
            return [], "empty"

        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return [], "empty"
        return [r + [""] * (max_cols - len(r)) for r in rows], "ok"

    @staticmethod
    def header_preview_of(rows: list[list[str]]) -> str:
        if not rows:
            return ""
        first = " | ".join(cell for cell in rows[0] if cell)
        return first[:200] + "..." if len(first) > 200 else first

    @staticmethod
    def write_csv(csv_path: Path, rows: list[list[str]]) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as fp:
            csv.writer(fp).writerows(rows)

    def process_file(self, path: Path, errors: list[str]) -> list[TableRecord]:
        report_id = self.report_id_from_path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"{report_id}\tREAD_ERROR\t{exc}")
            return []

        pages = self.build_page_index(text)
        records: list[TableRecord] = []
        for pos, match in enumerate(TABLE_PATTERN.finditer(text), start=1):
            rows, status = self.parse_table_html(match.group(0))
            page = self.page_for_offset(pages, match.start())
            csv_rel = Path("tables") / report_id / f"table_{pos}.csv"
            csv_abs = self.paths.output_dir / csv_rel

            if rows:
                self.write_csv(csv_abs, rows)
            else:
                csv_abs.parent.mkdir(parents=True, exist_ok=True)
                csv_abs.write_text("", encoding="utf-8")

            if status != "ok":
                errors.append(f"{report_id}\ttable_{pos}\t{status}\tpage={page}")

            records.append(
                TableRecord(
                    report_id=report_id,
                    table_pos=pos,
                    csv_path=str(csv_rel),
                    page_number=page,
                    num_rows=len(rows),
                    num_cols=len(rows[0]) if rows else 0,
                    header_preview=self.header_preview_of(rows),
                    parse_status=status,
                )
            )
        return records

    def write_stats_md(self, records: list[TableRecord], num_files: int, elapsed: float) -> None:
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
            f"- Số dòng: p50 {percentile(row_counts, 50)}, p90 {percentile(row_counts, 90)}, max {row_counts[-1] if row_counts else 0}",
            f"- Số cột: p50 {percentile(col_counts, 50)}, p90 {percentile(col_counts, 90)}, max {col_counts[-1] if col_counts else 0}",
            "",
            "## Ghi chú",
            "",
            "- `page_number` là số trang xuất hiện trong marker `===== PAGE N =====` gần nhất trước bảng.",
            "- Schema CSV giữ nguyên rows/cols từ HTML gốc, không normalize header.",
            "- Bảng lỗi/rỗng vẫn được ghi CSV rỗng để giữ liên kết `csv_path` hợp lệ.",
        ]
        self.paths.stats_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self) -> int:
        self.prepare_outputs()
        files = self.find_ocr_files()
        if not files:
            print(f"No OCR files found under {self.paths.statements_dir}", file=sys.stderr)
            return 1

        print(f"Processing {len(files)} OCR files...")
        started = time.time()
        all_records: list[TableRecord] = []
        errors: list[str] = []
        for idx, path in enumerate(files, start=1):
            all_records.extend(self.process_file(path, errors))
            if idx % 100 == 0 or idx == len(files):
                print(f"[{idx}/{len(files)}] files, {len(all_records)} tables")

        with self.paths.index_path.open("w", encoding="utf-8") as fp:
            for rec in all_records:
                fp.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

        elapsed = time.time() - started
        self.write_stats_md(all_records, len(files), elapsed)
        self.paths.error_log_path.write_text("\n".join(errors) + ("\n" if errors else ""), encoding="utf-8")

        print(f"Done: {len(all_records)} tables from {len(files)} files in {elapsed:.1f}s")
        print(f"Index: {self.paths.index_path}")
        print(f"Stats: {self.paths.stats_path}")
        print(f"Errors: {self.paths.error_log_path} ({len(errors)} entries)")
        return 0

    async def arun(self) -> int:
        return await asyncio.to_thread(self.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    return TableExtractor().run()
