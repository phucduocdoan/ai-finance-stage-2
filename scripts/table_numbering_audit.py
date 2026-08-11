"""Empirical audit of table-extraction variants vs the organizer-reported 143,815 count."""

from __future__ import annotations

import re
from collections import Counter

from bs4 import BeautifulSoup

import _bootstrap  # noqa: F401

from finance_qa.core.paths import FINANCIAL_STATEMENTS_DIR


STATEMENTS_DIR = FINANCIAL_STATEMENTS_DIR

TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
OPEN_TAG_PATTERN = re.compile(r"<table\b", re.IGNORECASE)
CLOSE_TAG_PATTERN = re.compile(r"</table\s*>", re.IGNORECASE)


def parse_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        row = [c.get_text(" ", strip=True) for c in cells]
        rows.append(row)
    return rows


def main() -> None:
    files = sorted(STATEMENTS_DIR.glob("*/*/*/*_extracted.txt"))
    print(f"Total files: {len(files)}")

    variant_a = 0  # current regex, all matches
    variant_b = 0  # exclude 0/1-row tables
    variant_c = 0  # exclude <2 columns
    variant_d = 0  # exclude all-empty-cell tables
    variant_e = 0  # count of <table opening tags
    variant_f = 0  # BeautifulSoup find_all("table") whole-doc
    variant_g_bc = 0  # b AND c combined
    variant_g_bcd = 0  # b AND c AND d combined

    nested_count = 0  # files with nested <table> (open tag inside a table's regex-matched span before its close)
    unclosed_files = 0
    unclosed_total_diff = 0

    # per-report counts for variant a vs b/c/d to measure "shift" impact
    per_report_a: dict[str, int] = {}
    per_report_b: dict[str, int] = {}
    per_report_c: dict[str, int] = {}
    per_report_d: dict[str, int] = {}

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        report_id = path.stem.removesuffix("_extracted")

        matches = list(TABLE_PATTERN.finditer(text))
        variant_a += len(matches)
        per_report_a[report_id] = len(matches)

        # nested check: does another '<table' occur strictly inside a matched span
        # (excluding at the match start itself)?
        has_nested = False
        for m in matches:
            inner = text[m.start() + 1 : m.end()]
            if OPEN_TAG_PATTERN.search(inner):
                has_nested = True
                break
        if has_nested:
            nested_count += 1

        n_open = len(OPEN_TAG_PATTERN.findall(text))
        n_close = len(CLOSE_TAG_PATTERN.findall(text))
        if n_open != n_close:
            unclosed_files += 1
            unclosed_total_diff += abs(n_open - n_close)
        variant_e += n_open

        # BeautifulSoup whole-document parse
        soup = BeautifulSoup(text, "html.parser")
        variant_f += len(soup.find_all("table"))

        b_count = 0
        c_count = 0
        d_count = 0
        bc_count = 0
        bcd_count = 0
        for m in matches:
            rows = parse_rows(m.group(0))
            n_rows = len(rows)
            n_cols = max((len(r) for r in rows), default=0)
            all_empty = all(not cell.strip() for r in rows for cell in r) if rows else True

            keep_b = n_rows >= 2
            keep_c = n_cols >= 2
            keep_d = not all_empty

            if keep_b:
                b_count += 1
            if keep_c:
                c_count += 1
            if keep_d:
                d_count += 1
            if keep_b and keep_c:
                bc_count += 1
            if keep_b and keep_c and keep_d:
                bcd_count += 1

        variant_b += b_count
        variant_c += c_count
        variant_d += d_count
        variant_g_bc += bc_count
        variant_g_bcd += bcd_count
        per_report_b[report_id] = b_count
        per_report_c[report_id] = c_count
        per_report_d[report_id] = d_count

    target = 143815
    print("\nVariant -> count -> delta from 143,815")
    for name, val in [
        ("(a) current regex, all matches", variant_a),
        ("(b) exclude 0/1-row tables", variant_b),
        ("(c) exclude <2 column tables", variant_c),
        ("(d) exclude all-empty-cell tables", variant_d),
        ("(e) count of <table opening tags", variant_e),
        ("(f) BeautifulSoup find_all('table') whole-doc", variant_f),
        ("(g1) b AND c combined", variant_g_bc),
        ("(g2) b AND c AND d combined", variant_g_bcd),
    ]:
        print(f"  {name}: {val:,}  (delta {val - target:+,})")

    print(f"\nFiles with nested <table> (open tag found inside a matched span): {nested_count}")
    print(f"Files with open/close <table> tag count mismatch: {unclosed_files}, total abs tag-count diff: {unclosed_total_diff}")

    # Reports whose count differs between variant a and b/c/d
    def diff_reports(other: dict[str, int], name: str) -> None:
        affected = []
        for rid, a_count in per_report_a.items():
            o_count = other.get(rid, 0)
            if o_count != a_count:
                affected.append(a_count - o_count)
        print(f"\n{name}: reports affected = {len(affected)} / {len(per_report_a)}")
        if affected:
            sorted_abs = sorted(abs(x) for x in affected)
            median = sorted_abs[len(sorted_abs) // 2]
            print(f"  median absolute shift in table count = {median}, max = {max(sorted_abs)}")

    diff_reports(per_report_b, "(a) vs (b) exclude 0/1-row")
    diff_reports(per_report_c, "(a) vs (c) exclude <2 cols")
    diff_reports(per_report_d, "(a) vs (d) exclude all-empty")


if __name__ == "__main__":
    main()
