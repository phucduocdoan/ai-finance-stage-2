"""Enrich questions with deterministic metadata.

For each question in ViFinQA/questions/questions.jsonl, add:
  - ticker:        primary ticker (first found), or None
  - tickers:       list of all tickers referenced
  - years:         list of years mentioned (int), with "2016-2020" spans expanded
  - unit_hint:     unit at the end of the question (trăm tỷ / tỷ / triệu / đồng /
                   phần trăm / lần / none)
  - doc_type:      consolidated | separate | unknown (only if stated explicitly)
  - answer_shape:  single_cell | derived
  - multi_year:    len(years) > 1
  - multi_company: len(tickers) > 1

Then emit questions_stats.html summarizing the distribution.
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter

from finance_qa.paths import (
    CODE_STOCK_PATH,
    QUESTION_METADATA_PATH,
    RAW_QUESTIONS_PATH,
    REPORTS_DIR,
)


QUESTIONS_PATH = RAW_QUESTIONS_PATH
ENRICHED_PATH = QUESTION_METADATA_PATH
STATS_PATH = REPORTS_DIR / "questions_stats.html"


# Manual aliases: shorthand names not derivable from the CSV entry
# (bank shortforms, brand names differing from legal name, short 5-char names).
MANUAL_ALIASES: dict[str, list[str]] = {
    "HUT": ["Tasco"],
    "NAB": ["Nam Á"],
    "KBC": ["Kinh Bắc"],
    "BAB": ["Bắc Á"],
    "SGB": ["Saigonbank"],
    "MBB": ["MBBank"],
    "EIB": ["Eximbank"],
    "HPG": ["Hòa Phát", "Hoà Phát"],
    "HSG": ["Hoa Sen"],
    "NKG": ["Nam Kim"],
    "MSN": ["Masan"],
    "VNM": ["Vinamilk"],
    "DBC": ["Dabaco"],
    "DPM": ["Đạm Phú Mỹ"],
    "DCM": ["Đạm Cà Mau"],
    "OGC": ["Đại Dương"],
    "ASM": ["Sao Mai"],
    "MPC": ["Minh Phú"],
}


def load_ticker_data() -> tuple[set[str], dict[str, str]]:
    tickers: set[str] = set()
    names: dict[str, str] = {}
    with CODE_STOCK_PATH.open(encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            t = row["Mã CK"].strip().upper()
            tickers.add(t)
            names[t] = row["Tên công ty"].strip()
    return tickers, names


_PREFIX_RE = re.compile(
    r"^(CTCP\s*-\s*Tổng\s*Công\s*ty|Tổng\s*Công\s*ty\s*cổ\s*phần|"
    r"Ngân\s*hàng\s*TMCP|Tổng\s*[Cc]ông\s*ty|Tập\s*đoàn|"
    r"CTCP|Công\s*ty)\s+",
    re.IGNORECASE,
)
_SUFFIX_RE = re.compile(r"\s*-\s*CTCP\s*$", re.IGNORECASE)


def name_signatures(name: str) -> list[str]:
    """Yield distinctive substrings that identify the company.

    Applies suffix strip, then iterative prefix stripping (so
    "CTCP Tập đoàn Hòa Phát" yields "Tập đoàn Hòa Phát" and "Hòa Phát").
    """
    sigs: list[str] = [name]
    core = _SUFFIX_RE.sub("", name).strip()
    if core and core != name:
        sigs.append(core)
    prev = core
    for _ in range(3):
        stripped = _PREFIX_RE.sub("", prev, count=1).strip()
        if not stripped or stripped == prev:
            break
        sigs.append(stripped)
        prev = stripped
    return sigs


# Match "PC1", "AAA", "REE" — allow digits after first letter.
TICKER_CANDIDATE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,3})\b")
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
# "2016-2020", "2021 – 2024", "từ năm 2022 đến năm 2025" — one period, not two
# separate mentions. Argmax-over-range questions need every year in between.
YEAR_RANGE_PATTERN = re.compile(
    r"\b(20\d{2})\s*(?:-|–|—|đến|tới)\s*(?:năm\s*)?(20\d{2})\b"
)

# Unit hints are usually near the end. Patterns include the complete phrase so a
# longer unit ("nghìn tỷ đồng") wins over its nested suffix ("tỷ đồng"/"đồng").
UNIT_PATTERNS = [
    ("nghìn tỷ", re.compile(r"\bnghìn\s+tỷ(?:\s+đồng)?\b", re.IGNORECASE)),
    ("trăm tỷ", re.compile(r"\btrăm\s+tỷ(?:\s+đồng)?\b", re.IGNORECASE)),
    ("tỷ", re.compile(r"\btỷ(?!\s+(?:lệ|số|suất))\b(?:\s+đồng)?", re.IGNORECASE)),
    ("triệu", re.compile(r"\btriệu(?:\s+(?:đồng|cổ\s+phiếu))?\b", re.IGNORECASE)),
    ("phần trăm", re.compile(r"\b(?:điểm\s+)?phần\s+trăm\b|%", re.IGNORECASE)),
    ("lần", re.compile(r"\blần\b", re.IGNORECASE)),
    ("đồng", re.compile(r"\bđồng\b", re.IGNORECASE)),
]

COUNT_ANSWER_RE = re.compile(
    r"(?:có\s+)?bao\s+nhiêu\s+(?:doanh\s+nghiệp|công\s+ty|ngân\s+hàng)",
    re.IGNORECASE,
)

SEPARATE_RE = re.compile(
    r"công ty mẹ|riêng lẻ|riêng biệt|báo cáo riêng|cơ sở riêng", re.IGNORECASE
)
CONSOLIDATED_RE = re.compile(r"hợp nhất", re.IGNORECASE)

DERIVED_KEYWORDS = [
    "chênh lệch", "hiệu số", "tổng", "trung bình", "trung vị",
    "tỷ lệ", "tỷ số", "tỷ suất", "biên lợi nhuận",
    "vòng quay", "tăng trưởng", "cao nhất", "thấp nhất",
    "trong số", "trong các", "trong nhóm", "phần trăm", "điểm phần trăm",
    "hệ số", "ROE", "ROA", "ROIC", "CFO", "tính ", "so với",
    "chiếm bao nhiêu",
]


def find_tickers(
    text: str,
    valid: set[str],
    name_index: list[tuple[str, str]],
) -> list[str]:
    """Find tickers by (1) direct code match, (2) company-name fallback.

    name_index is a list of (signature, ticker) pairs sorted by signature length
    descending, so we match the most distinctive substrings first.
    """
    hits: list[tuple[int, str]] = []
    for m in TICKER_CANDIDATE.finditer(text):
        candidate = m.group(1).upper()
        if candidate in valid:
            hits.append((m.start(), candidate))

    # Company-name matches and direct ticker matches enter the same position-sorted
    # stream. The old two-pass append order turned "An Bình ... Quân đội" into
    # [MBB, ABB] merely because one signature happened to be scanned first, which
    # reverses A-B comparison semantics downstream.
    lower_text = text.lower()
    for signature, ticker in name_index:
        start = lower_text.find(signature.lower())
        if start >= 0:
            hits.append((start, ticker))

    found: list[str] = []
    seen: set[str] = set()
    for _, ticker in sorted(hits):
        if ticker not in seen:
            found.append(ticker)
            seen.add(ticker)
    return found


def build_name_index(names: dict[str, str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    # Manual aliases: no length filter (short shorthand names like "Tasco").
    for ticker, aliases in MANUAL_ALIASES.items():
        for sig in aliases:
            pairs.append((sig, ticker))
    # Auto-derived from company names: keep only distinctive ones.
    for ticker, name in names.items():
        for sig in name_signatures(name):
            if len(sig) >= 6:
                pairs.append((sig, ticker))
    # Longest signatures first — more distinctive.
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def find_years(text: str) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for m in YEAR_PATTERN.finditer(text):
        y = int(m.group(1))
        if y not in seen:
            seen.add(y)
            ordered.append(y)
    for m in YEAR_RANGE_PATTERN.finditer(text):
        for y in range(int(m.group(1)) + 1, int(m.group(2))):
            if y not in seen:
                seen.add(y)
                ordered.append(y)
    return ordered


def detect_unit(text: str) -> str:
    # An explicit entity-count question outranks ratio units occurring inside its
    # filter conditions (for example "trên 1 lần ... có bao nhiêu doanh nghiệp").
    if COUNT_ANSWER_RE.search(text):
        return "count"

    def latest_unit(fragment: str) -> str | None:
        candidates = []
        for label, pattern in UNIT_PATTERNS:
            candidates.extend(
                (match.end(), match.end() - match.start(), label)
                for match in pattern.finditer(fragment)
            )
        if not candidates:
            return None
        # Prefer the last mention because it normally describes the requested
        # output, then the longest phrase to resolve overlapping money units.
        return max(candidates)[2]

    # Consider only the last ~60 chars where the requested output unit tends to sit.
    tail = text[-60:] if len(text) > 60 else text
    return latest_unit(tail) or latest_unit(text) or "none"


def detect_doc_type(text: str) -> str:
    """Reporting scope, but only when the question states it explicitly (Q4).

    Corpus `doc_type` vocabulary is {consolidated, separate, aggregated,
    explanations} — industry ("ngân hàng", "chứng khoán") is a different axis
    and never matched any table, so it is not reported here. `unknown` means
    no hard filter: the question did not say, or it spans both scopes.
    """
    separate = bool(SEPARATE_RE.search(text))
    consolidated = bool(CONSOLIDATED_RE.search(text))
    if separate and not consolidated:
        return "separate"
    if consolidated and not separate:
        return "consolidated"
    return "unknown"


def detect_answer_shape(text: str, years: list[int], tickers: list[str]) -> str:
    if len(years) > 1 or len(tickers) > 1:
        return "derived"
    lower = text.lower()
    for kw in DERIVED_KEYWORDS:
        if kw.lower() in lower:
            return "derived"
    return "single_cell"


def enrich(
    question: dict,
    valid_tickers: set[str],
    name_index: list[tuple[str, str]],
) -> dict:
    text = question["question"]
    tickers = find_tickers(text, valid_tickers, name_index)
    years = find_years(text)
    unit_hint = detect_unit(text)
    doc_type = detect_doc_type(text)
    answer_shape = detect_answer_shape(text, years, tickers)

    return {
        **question,
        "ticker": tickers[0] if tickers else None,
        "tickers": tickers,
        "years": years,
        "unit_hint": unit_hint,
        "doc_type": doc_type,
        "answer_shape": answer_shape,
        "multi_year": len(years) > 1,
        "multi_company": len(tickers) > 1,
    }


# -------- Stats rendering --------


STATS_CSS = """
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 1000px; margin: 24px auto; padding: 0 20px; color: #1f2328; }
h1 { font-size: 20px; }
h2 { font-size: 16px; margin-top: 28px; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }
table { border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #d0d7de; padding: 4px 12px; text-align: left; font-size: 13px; }
th { background: #f6f8fa; }
td.num { text-align: right; font-family: monospace; }
.bar { display: inline-block; height: 10px; background: #0969da; vertical-align: middle; margin-left: 6px; }
.sample { background: #f6f8fa; padding: 6px 10px; margin: 6px 0; border-radius: 4px; font-size: 13px; }
.sample b { color: #cf222e; }
code { background: #f6f8fa; padding: 1px 4px; border-radius: 3px; }
"""


def render_bar(count: int, total: int) -> str:
    width = int(round(200 * count / total)) if total else 0
    return f'<span class="bar" style="width:{width}px"></span>'


def render_counter_table(title: str, counter: Counter, total: int) -> str:
    rows = ["<tr><th>Giá trị</th><th>Số câu</th><th>Tỉ lệ</th><th>Biểu đồ</th></tr>"]
    for key, count in counter.most_common():
        pct = 100.0 * count / total if total else 0
        rows.append(
            f"<tr><td><code>{html.escape(str(key))}</code></td>"
            f"<td class='num'>{count}</td>"
            f"<td class='num'>{pct:.1f}%</td>"
            f"<td>{render_bar(count, total)}</td></tr>"
        )
    return f"<h2>{html.escape(title)}</h2><table>{''.join(rows)}</table>"


def render_stats(records: list[dict]) -> str:
    total = len(records)
    doc_type_counts = Counter(r["doc_type"] for r in records)
    unit_counts = Counter(r["unit_hint"] for r in records)
    shape_counts = Counter(r["answer_shape"] for r in records)
    multi_year_counts = Counter("có" if r["multi_year"] else "không" for r in records)
    multi_company_counts = Counter("có" if r["multi_company"] else "không" for r in records)
    ticker_unknown = sum(1 for r in records if r["ticker"] is None)
    year_none = sum(1 for r in records if not r["years"])

    top_tickers = Counter()
    for r in records:
        for t in r["tickers"]:
            top_tickers[t] += 1

    # Sample edge cases for review.
    ticker_none_samples = [r for r in records if r["ticker"] is None][:5]
    year_none_samples = [r for r in records if not r["years"]][:5]

    def render_sample(r: dict) -> str:
        return f'<div class="sample">#{r["id"]}: {html.escape(r["question"])}</div>'

    parts = [
        f"<!DOCTYPE html><html lang='vi'><head><meta charset='utf-8'>",
        f"<title>Thống kê câu hỏi ViFinQA</title><style>{STATS_CSS}</style></head><body>",
        f"<h1>Thống kê câu hỏi ViFinQA</h1>",
        f"<p>Tổng số câu hỏi: <b>{total:,}</b>. Ticker không nhận diện: "
        f"<b>{ticker_unknown}</b>. Câu không có năm: <b>{year_none}</b>.</p>",
        render_counter_table("Phân loại doc_type", doc_type_counts, total),
        render_counter_table("Đơn vị (unit_hint)", unit_counts, total),
        render_counter_table("Hình thức đáp án (answer_shape)", shape_counts, total),
        render_counter_table("Có nhiều năm?", multi_year_counts, total),
        render_counter_table("Có nhiều công ty?", multi_company_counts, total),
        f"<h2>Top 20 ticker xuất hiện nhiều nhất</h2>",
        "<table><tr><th>Ticker</th><th>Số câu</th></tr>"
        + "".join(
            f"<tr><td><code>{html.escape(t)}</code></td><td class='num'>{c}</td></tr>"
            for t, c in top_tickers.most_common(20)
        )
        + "</table>",
        f"<h2>Ví dụ câu không nhận diện được ticker ({ticker_unknown} câu)</h2>",
        "".join(render_sample(r) for r in ticker_none_samples) or "<p>—</p>",
        f"<h2>Ví dụ câu không có năm ({year_none} câu)</h2>",
        "".join(render_sample(r) for r in year_none_samples) or "<p>—</p>",
        "</body></html>",
    ]
    return "".join(parts)


def main() -> int:
    ENRICHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    valid, names = load_ticker_data()
    print(f"Loaded {len(valid)} valid tickers")
    name_index = build_name_index(names)
    print(f"Built {len(name_index)} name signatures")

    with QUESTIONS_PATH.open(encoding="utf-8") as fp:
        questions = [json.loads(line) for line in fp if line.strip()]
    print(f"Loaded {len(questions)} questions")

    enriched = [enrich(q, valid, name_index) for q in questions]

    with ENRICHED_PATH.open("w", encoding="utf-8") as fp:
        for r in enriched:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {ENRICHED_PATH}")

    STATS_PATH.write_text(render_stats(enriched), encoding="utf-8")
    print(f"Wrote {STATS_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
