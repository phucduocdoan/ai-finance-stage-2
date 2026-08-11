"""Enrich table metadata with deterministic report, CSV, and OCR-page signals."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from finance_qa.core.paths import (
    CODE_STOCK_PATH,
    DATA_DIR,
    FINANCIAL_STATEMENTS_DIR,
    REPORTS_DIR,
    TABLE_METADATA_PATH,
    TABLE_METADATA_V1_PATH,
)


STD_REPORT_RE = re.compile(
    r"^([A-Z0-9]+)_financial_statements_(\d{4})"
    r"(?:_(separate|consolidated|aggregated))?"
    r"(?:_\d+)?$"
)
EXPL_REPORT_RE = re.compile(
    r"^([A-Z0-9]+)_(\d{4})_(?:explanatory_letters|financial_statement_explanations)"
    r"(?:_\d+)?$"
)
TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
PAGE_MARKER = re.compile(r"^=====\s*PAGE\s+\d+\s*=====\s*$", re.MULTILINE)
WHITESPACE_RE = re.compile(r"\s+")

NAME_HINTS = (
    ("ngân hàng", "bank"),
    ("bank", "bank"),
    ("chứng khoán", "securities"),
    ("bảo hiểm", "insurance"),
    ("tái bảo hiểm", "insurance"),
)
YEAR_RE = re.compile(r"(?<!\d)(19|20)(\d{2})(?!\d)")
CONT_RE = re.compile(r"(tiếp\s*theo|\(\s*tiếp\s*\)|continued|cont\.)", re.IGNORECASE)
CONTEXT_MAX_CHARS = 1500
LABEL_LETTERS_RE = re.compile(r"[A-Za-zÀ-ỹĐđ]{3,}")
MAX_LABELS = 60
MAX_LABEL_LEN = 200
LABEL_COL_MAX_INDEX = 2
FALLBACK_STMTS = {"balance_sheet", "income_statement", "cash_flow"}


@dataclass(frozen=True)
class MetadataEnrichmentPaths:
    output_dir: Path = DATA_DIR
    statements_dir: Path = FINANCIAL_STATEMENTS_DIR
    meta_v1_path: Path = TABLE_METADATA_V1_PATH
    meta_v2_path: Path = TABLE_METADATA_PATH
    stats_path: Path = REPORTS_DIR / "enrich_v2_stats.md"
    code_stock_path: Path = CODE_STOCK_PATH


def load_ticker_names(code_stock_path: Path = CODE_STOCK_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    with code_stock_path.open(encoding="utf-8") as fp:
        rdr = csv.reader(fp)
        next(rdr, None)
        for row in rdr:
            if len(row) >= 2:
                out[row[0].strip()] = row[1].strip()
    return out


def parse_report_id(rid: str) -> tuple[str, int | None, str]:
    m = STD_REPORT_RE.match(rid)
    if m:
        return m.group(1), int(m.group(2)), m.group(3) or ""
    m = EXPL_REPORT_RE.match(rid)
    if m:
        return m.group(1), int(m.group(2)), "explanations"
    return "", None, ""


def report_id_to_ocr_path(report_id: str, statements_dir: Path = FINANCIAL_STATEMENTS_DIR) -> Path:
    parts = report_id.split("_financial_statements_", 1)
    if len(parts) != 2:
        return statements_dir / f"__missing__/{report_id}.txt"
    ticker = parts[0]
    year = parts[1].split("_", 1)[0]
    return statements_dir / ticker / year / report_id / f"{report_id}_extracted.txt"


def find_table_offsets(text: str) -> list[int]:
    return [m.start() for m in TABLE_PATTERN.finditer(text)]


def industry_from_mau_tag(mau_tag: str) -> str:
    if not mau_tag:
        return ""
    org = mau_tag.rsplit(" ", 1)[-1].upper()
    if org in ("TCTD", "NH"):
        return "bank"
    if org == "CTCK":
        return "securities"
    if org == "BH":
        return "insurance"
    if org == "DN":
        return "general"
    return ""


def industry_from_company_name(company_name: str) -> str:
    if not company_name:
        return ""
    low = company_name.lower()
    for needle, seg in NAME_HINTS:
        if needle in low:
            return seg
    return ""


def derive_industry_segment(mau_tag: str, report_industry: str, company_name: str) -> str:
    seg = industry_from_mau_tag(mau_tag)
    if seg:
        return seg
    if report_industry:
        return report_industry
    seg = industry_from_company_name(company_name)
    if seg:
        return seg
    return "general" if company_name else "unknown"


def scan_report_industries(meta_path: Path) -> dict[str, str]:
    votes: dict[str, Counter[str]] = {}
    with meta_path.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            seg = industry_from_mau_tag(rec.get("mau_tag", ""))
            if seg:
                votes.setdefault(rec.get("report_id", ""), Counter())[seg] += 1
    return {rid: c.most_common(1)[0][0] for rid, c in votes.items()}


def parse_period_years(
    header_flat: str,
    period_columns_raw: list[str] | None,
    report_year: int | None,
    statement_type: str = "",
) -> list[int]:
    years: set[int] = set()
    for src in filter(None, [header_flat, *(period_columns_raw or [])]):
        for m in YEAR_RE.finditer(src):
            y = int(m.group(1) + m.group(2))
            if 1990 <= y <= 2035:
                years.add(y)
    if years:
        return sorted(years, reverse=True)
    if report_year and (period_columns_raw or statement_type in FALLBACK_STMTS):
        return [report_year, report_year - 1]
    return []


def detect_continuation(note_title: str, header_flat: str, section_title: str) -> bool:
    return any(s and CONT_RE.search(s) for s in (note_title, header_flat, section_title))


def extract_page_prose(text: str, table_offset: int) -> str:
    page_start = 0
    for m in PAGE_MARKER.finditer(text, 0, table_offset):
        page_start = m.end()
    m2 = PAGE_MARKER.search(text, table_offset)
    page_end = m2.start() if m2 else len(text)
    window = TABLE_PATTERN.sub(" ", text[page_start:page_end])
    return WHITESPACE_RE.sub(" ", window).strip()[:CONTEXT_MAX_CHARS]


def pick_label_col(rows: list[list[str]]) -> int:
    max_c = min(LABEL_COL_MAX_INDEX + 1, max((len(r) for r in rows[1:]), default=0))
    best_col, best_score = 0, -1
    for c in range(max_c):
        score = 0
        for r in rows[1:]:
            if len(r) <= c:
                continue
            v = r[c].strip()
            if len(v) >= 3 and LABEL_LETTERS_RE.search(v):
                score += 1
        if score > best_score:
            best_col, best_score = c, score
    return best_col


def enrich_csv(csv_path: Path) -> tuple[str, list[str]]:
    try:
        with csv_path.open(encoding="utf-8", newline="") as fp:
            rows = list(csv.reader(fp))
    except Exception:
        return "", []

    if not rows:
        return "", []

    header_flat = " | ".join(c.strip() for c in rows[0] if c.strip())
    label_col = pick_label_col(rows)
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows[1:]:
        if not row or len(row) <= label_col:
            continue
        cell = row[label_col].strip()
        if cell and LABEL_LETTERS_RE.search(cell) and len(labels) < MAX_LABELS:
            trimmed = cell[:MAX_LABEL_LEN]
            if trimmed not in seen:
                seen.add(trimmed)
                labels.append(trimmed)
    return header_flat, labels


class MetadataEnricher:
    """Build `tables_metadata_v2.jsonl` from v1 metadata, CSVs, and OCR text."""

    def __init__(self, paths: MetadataEnrichmentPaths | None = None) -> None:
        self.paths = paths or MetadataEnrichmentPaths()

    def run(self) -> int:
        self.paths.meta_v2_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.stats_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.paths.meta_v1_path.exists():
            print(f"ERROR: {self.paths.meta_v1_path} not found. Run enrich_table_metadata.py first.")
            return 1

        t0 = time.perf_counter()
        ticker_names = load_ticker_names(self.paths.code_stock_path)
        print(f"Loaded {len(ticker_names)} tickers from code_stock.csv")

        report_industry = scan_report_industries(self.paths.meta_v1_path)
        print(f"Report-level industry votes: {len(report_industry)} reports")

        stats = Counter()
        industry_counts: Counter[str] = Counter()
        csv_missing = 0
        empty_labels = 0
        empty_context = 0
        empty_doc_type = 0
        empty_period_years = 0
        is_cont_count = 0
        ocr_missing_reports: set[str] = set()
        n_total = 0
        cur_report: str | None = None
        cur_text = ""
        cur_offsets: list[int] = []

        with self.paths.meta_v1_path.open(encoding="utf-8") as fin, self.paths.meta_v2_path.open(
            "w", encoding="utf-8"
        ) as fout:
            for line in fin:
                rec = json.loads(line)
                n_total += 1

                ticker, year, doc_type = parse_report_id(rec["report_id"])
                rec["ticker"] = ticker
                rec["year"] = year
                rec["doc_type"] = doc_type
                rec["company_name"] = ticker_names.get(ticker, "")
                if ticker and not rec["company_name"]:
                    stats["ticker_no_name"] += 1

                csv_path = self.paths.output_dir / rec["csv_path"]
                if csv_path.exists():
                    header_flat, labels = enrich_csv(csv_path)
                else:
                    csv_missing += 1
                    header_flat, labels = "", []

                rec.pop("parse_status", None)
                rec.pop("header_preview", None)
                rec["header_flat"] = header_flat
                rec["first_col_labels"] = labels
                rec["industry_segment"] = derive_industry_segment(
                    rec.get("mau_tag", ""),
                    report_industry.get(rec["report_id"], ""),
                    rec["company_name"],
                )
                rec["period_years"] = parse_period_years(
                    header_flat,
                    rec.get("period_columns_raw"),
                    rec.get("year"),
                    rec.get("statement_type", ""),
                )
                rec["is_continuation"] = detect_continuation(
                    rec.get("note_title", ""), header_flat, rec.get("section_title", "")
                )

                rid = rec["report_id"]
                if rid != cur_report:
                    cur_report = rid
                    ocr_path = report_id_to_ocr_path(rid, self.paths.statements_dir)
                    if ocr_path.exists():
                        cur_text = ocr_path.read_text(encoding="utf-8", errors="replace")
                        cur_offsets = find_table_offsets(cur_text)
                    else:
                        cur_text = ""
                        cur_offsets = []
                        ocr_missing_reports.add(rid)

                tpos = rec.get("table_pos", -1)
                if cur_text and 0 <= tpos < len(cur_offsets):
                    rec["context_page_text"] = extract_page_prose(cur_text, cur_offsets[tpos])
                else:
                    rec["context_page_text"] = ""

                if not labels:
                    empty_labels += 1
                if not rec["context_page_text"]:
                    empty_context += 1
                if not rec["doc_type"]:
                    empty_doc_type += 1
                if not rec["period_years"]:
                    empty_period_years += 1
                if rec["is_continuation"]:
                    is_cont_count += 1
                industry_counts[rec["industry_segment"]] += 1
                stats[f"stmt_{rec.get('statement_type', 'unknown')}"] += 1
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

                if n_total % 10000 == 0:
                    print(f"  [{n_total:,}] processed")

        elapsed = time.perf_counter() - t0
        print(f"\nDone: {n_total:,} rows in {elapsed:.1f}s")
        print(f"CSV missing: {csv_missing}")
        print(f"Empty first_col_labels: {empty_labels}")
        print(f"Empty context_page_text: {empty_context}")
        print(f"Reports with missing OCR: {len(ocr_missing_reports)}")
        self.write_stats(
            n_total=n_total,
            elapsed=elapsed,
            csv_missing=csv_missing,
            empty_labels=empty_labels,
            empty_context=empty_context,
            empty_doc_type=empty_doc_type,
            empty_period_years=empty_period_years,
            is_cont_count=is_cont_count,
            ocr_missing_reports=ocr_missing_reports,
            stats=stats,
            industry_counts=industry_counts,
        )
        print(f"Stats: {self.paths.stats_path}")
        return 0

    def write_stats(
        self,
        *,
        n_total: int,
        elapsed: float,
        csv_missing: int,
        empty_labels: int,
        empty_context: int,
        empty_doc_type: int,
        empty_period_years: int,
        is_cont_count: int,
        ocr_missing_reports: set[str],
        stats: Counter,
        industry_counts: Counter[str],
    ) -> None:
        lines = ["# Enrich v2 stats", ""]
        lines.append(f"- Input: `{self.paths.meta_v1_path.name}`")
        lines.append(f"- Output: `{self.paths.meta_v2_path.name}` ({self.paths.meta_v2_path.stat().st_size / 1e6:.1f} MB)")
        lines.append(f"- Rows: **{n_total:,}**")
        lines.append(f"- Time: **{elapsed:.1f}s**")
        lines.append(f"- CSV missing: {csv_missing}")
        lines.append(f"- Empty `first_col_labels`: {empty_labels} ({empty_labels / n_total * 100:.1f}%)")
        lines.append(f"- Empty `context_page_text`: {empty_context} ({empty_context / n_total * 100:.1f}%)")
        lines.append(f"- Reports with missing OCR: {len(ocr_missing_reports)}")
        lines.append(f"- Tickers without company_name mapping: {stats['ticker_no_name']}")
        lines.append(f"- Empty `doc_type`: {empty_doc_type} ({empty_doc_type / n_total * 100:.1f}%)")
        lines.append(f"- Empty `period_years`: {empty_period_years} ({empty_period_years / n_total * 100:.1f}%)")
        lines.append(f"- `is_continuation=true`: {is_cont_count} ({is_cont_count / n_total * 100:.1f}%)")
        lines.append("")
        lines.append("## industry_segment distribution")
        lines.append("")
        lines.append("| Segment | Số bảng | Tỉ lệ |")
        lines.append("|---|---:|---:|")
        for seg, count in industry_counts.most_common():
            lines.append(f"| `{seg}` | {count:,} | {count / n_total * 100:.1f}% |")
        lines.append("")
        lines.append("## Fields added")
        lines.append("")
        lines.append("**Tầng 1 derived**: `ticker`, `year`, `doc_type`, `company_name`")
        lines.append("")
        lines.append("**Tầng 2 from CSV**: `header_flat`, `first_col_labels`")
        lines.append("")
        lines.append(
            f"**Tầng 2 from OCR page**: `context_page_text` (cap {CONTEXT_MAX_CHARS} chars, whitespace collapsed, `<table>` stripped)"
        )
        lines.append("")
        lines.append("**Semantic signals**: `industry_segment`, `period_years`, `is_continuation`")
        self.paths.stats_path.write_text("\n".join(lines), encoding="utf-8")

    async def arun(self) -> int:
        return await asyncio.to_thread(self.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    return MetadataEnricher().run()
