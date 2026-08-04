"""Rule-based solver: question → lookup long_format.parquet → answer.

Prototype only, no LLM. Handles L1-L3 shapes on main BS/IS/CF (has Mã số).
Skips notes, banks, CTCK (not in parquet).

Run:
  .venv_bge/bin/python scripts/solve.py [--ids 674,605,582,656,904]
"""

from __future__ import annotations

import argparse
import json
import re

import pandas as pd

import _bootstrap  # noqa: F401

from finance_qa.paths import LONG_FORMAT_PATH, QUESTION_METADATA_PATH


PARQUET = LONG_FORMAT_PATH
QUESTIONS = QUESTION_METADATA_PATH

# Ordered: longer/more-specific keys FIRST so shorter substrings don't win.
# Each entry: (regex pattern, statement_type, ma_so, canonical_label)
METRIC_MAP: list[tuple[str, str, str, str]] = [
    # IS — order matters, more specific first
    (r"lợi\s*nhuận\s*sau\s*thuế.*(công\s*ty\s*mẹ|cổ\s*đông)", "income_statement", "61", "LNST của cty mẹ"),
    (r"lợi\s*nhuận\s*(sau\s*thuế|ròng)",                       "income_statement", "60", "LNST"),
    (r"lợi\s*nhuận\s*trước\s*thuế",                            "income_statement", "50", "LNTT"),
    (r"lợi\s*nhuận\s*(gộp|thô)",                               "income_statement", "20", "Lợi nhuận gộp"),
    (r"lợi\s*nhuận\s*thuần\s*từ",                              "income_statement", "30", "LN thuần HĐKD"),
    (r"doanh\s*thu\s*(hoạt\s*động\s*)?tài\s*chính",            "income_statement", "21", "Doanh thu tài chính"),
    (r"chi\s*phí\s*(lãi\s*vay|đi\s*vay)",                      "income_statement", "23", "Chi phí lãi vay"),
    (r"chi\s*phí\s*tài\s*chính",                               "income_statement", "22", "Chi phí tài chính"),
    (r"chi\s*phí\s*bán\s*hàng",                                "income_statement", "25", "Chi phí bán hàng"),
    (r"chi\s*phí\s*quản\s*lý",                                 "income_statement", "26", "Chi phí QLDN"),
    (r"giá\s*vốn\s*hàng\s*bán",                                "income_statement", "11", "Giá vốn"),
    (r"doanh\s*thu\s*thuần",                                   "income_statement", "10", "DTT"),

    # BS
    (r"tổng\s*(cộng\s*)?tài\s*sản",                            "balance_sheet",    "270", "Tổng tài sản"),
    (r"tài\s*sản\s*ngắn\s*hạn",                                "balance_sheet",    "100", "TS ngắn hạn"),
    (r"tài\s*sản\s*dài\s*hạn",                                 "balance_sheet",    "200", "TS dài hạn"),
    (r"tài\s*sản\s*cố\s*định",                                 "balance_sheet",    "220", "TSCĐ"),
    (r"tương\s*đương\s*tiền",                                  "balance_sheet",    "112", "Tương đương tiền"),
    (r"người\s*mua\s*trả\s*tiền\s*trước\s*(ngắn\s*hạn)?",      "balance_sheet",    "312", "Người mua trả tiền trước NH"),
    (r"phải\s*thu\s*khách\s*hàng",                             "balance_sheet",    "131", "Phải thu KH"),
    (r"hàng\s*tồn\s*kho",                                      "balance_sheet",    "141", "Hàng tồn kho"),
    (r"vay\s*(và\s*nợ\s*thuê\s*tài\s*chính\s*)?ngắn\s*hạn",    "balance_sheet",    "320", "Vay NH"),
    (r"vay\s*(và\s*nợ\s*thuê\s*tài\s*chính\s*)?dài\s*hạn",     "balance_sheet",    "338", "Vay DH"),
    (r"nợ\s*ngắn\s*hạn",                                       "balance_sheet",    "310", "Nợ NH"),
    (r"nợ\s*dài\s*hạn",                                        "balance_sheet",    "330", "Nợ DH"),
    (r"nợ\s*phải\s*trả",                                       "balance_sheet",    "300", "Nợ phải trả"),
    (r"vốn\s*chủ\s*sở\s*hữu",                                  "balance_sheet",    "400", "VCSH"),
]

# Ticker resolution overrides (name → correct ticker) when enrichment gave a substring match.
TICKER_OVERRIDES = {
    "viễn thông fpt": "FOX",
    "fpt telecom": "FOX",
}


def resolve_ticker(rec: dict) -> str:
    q = rec["question"].lower()
    for phrase, tk in TICKER_OVERRIDES.items():
        if phrase in q:
            return tk
    return rec["ticker"]


def match_metric(text: str) -> tuple[str, str, str] | None:
    """Return (statement_type, ma_so, canonical_label) for first metric matched."""
    for pat, st, ms, lbl in METRIC_MAP:
        if re.search(pat, text, re.IGNORECASE):
            return st, ms, lbl
    return None


def match_metrics_all(text: str) -> list[tuple[str, str, str]]:
    """All non-overlapping metric hits, ordered by position in text."""
    hits = []
    seen_ma = set()
    for pat, st, ms, lbl in METRIC_MAP:
        m = re.search(pat, text, re.IGNORECASE)
        if m and ms not in seen_ma:
            hits.append((m.start(), st, ms, lbl))
            seen_ma.add(ms)
    hits.sort()
    return [(st, ms, lbl) for _, st, ms, lbl in hits]


def classify_op(question: str, rec: dict) -> str:
    q = question.lower()
    if re.search(r"năm\s*nào.*(lớn\s*nhất|cao\s*nhất|nhiều\s*nhất)", q):
        return "argmax"
    if re.search(r"năm\s*nào.*(nhỏ\s*nhất|thấp\s*nhất|ít\s*nhất)", q):
        return "argmin"
    if re.search(r"tăng\s*trưởng|tăng.*bao\s*nhiêu\s*%|tăng.*so\s*với|giảm.*so\s*với|thay\s*đổi", q):
        return "growth"
    if re.search(r"tỷ\s*(suất|trọng|lệ).*trên", q):
        return "ratio"
    if re.search(r"tỷ\s*suất\s*(lợi\s*nhuận|ln)", q):
        return "ratio_profit_margin"
    if re.search(r"chênh\s*lệch|khác\s*biệt", q):
        return "diff"
    if re.search(r"trung\s*bình", q):
        return "avg"
    if re.search(r"tổng.*giai\s*đoạn|tổng.*từ\s*\d{4}\s*đến\s*\d{4}", q):
        return "sum"
    return "lookup"


def classify_period(period: str, year: int) -> str:
    p = period.lower()
    if "cuối" in p or "31/12" in p or "31.12" in p:
        return "end"
    if "đầu" in p or "1/1" in p or "01/01" in p or "đầu năm" in p:
        return "begin"
    if str(year) in p and str(year - 1) not in p:
        return "end"
    if str(year - 1) in p and str(year) not in p:
        return "begin"
    return "unknown"


def get_value(df: pd.DataFrame, ticker: str, year: int, doc_type: str,
              stmt: str, ma_so: str, want_period: str = "end") -> tuple[float | None, list]:
    """Return (value, evidence_rows). want_period ∈ {end, begin}."""
    sub = df[
        (df.ticker == ticker) & (df.year == year) & (df.doc_type == doc_type)
        & (df.statement_type == stmt) & (df.ma_so == ma_so)
    ]
    if sub.empty:
        return None, []
    sub = sub.assign(_kind=sub.period.map(lambda p: classify_period(p, year)))
    matches = sub[sub._kind == want_period]
    if matches.empty:
        # IS/CF often have no meaningful begin/end distinction, fall back to any row
        matches = sub
    row = matches.iloc[0]
    return float(row.value), [{
        "report_id": row.report_id, "table_pos": int(row.table_pos),
        "ma_so": row.ma_so, "label": row.label, "period": row.period, "value": float(row.value),
    }]


def solve(rec: dict, df: pd.DataFrame) -> dict:
    q = rec["question"]
    ticker = resolve_ticker(rec)
    years = rec["years"]
    doc_type = rec.get("doc_type") or "consolidated"
    op = classify_op(q, rec)
    metrics = match_metrics_all(q)

    result = {
        "id": rec["id"], "question": q, "ticker": ticker, "years": years,
        "doc_type": doc_type, "op": op, "metrics": [m[2] for m in metrics],
        "answer": None, "evidence": [], "error": None,
    }

    if not metrics:
        result["error"] = "no metric matched"
        return result

    try:
        if op == "lookup":
            stmt, ms, _ = metrics[0]
            v, ev = get_value(df, ticker, years[0], doc_type, stmt, ms)
            result["answer"] = v
            result["evidence"] = ev

        elif op == "growth":
            stmt, ms, _ = metrics[0]
            if len(years) == 2 and years[1] - years[0] == 1:
                # 1 report — end vs begin of year Y
                y = years[1]
                v_end, e1 = get_value(df, ticker, y, doc_type, stmt, ms, "end")
                v_beg, e2 = get_value(df, ticker, y, doc_type, stmt, ms, "begin")
            elif len(years) == 2:
                # 2 reports
                v_beg, e2 = get_value(df, ticker, years[0], doc_type, stmt, ms, "end")
                v_end, e1 = get_value(df, ticker, years[1], doc_type, stmt, ms, "end")
            else:
                result["error"] = f"growth expected 2 years, got {years}"
                return result
            if v_end is None or v_beg is None or v_beg == 0:
                result["error"] = f"missing cells: end={v_end}, beg={v_beg}"
                return result
            result["answer"] = (v_end - v_beg) / v_beg * 100
            result["evidence"] = e1 + e2

        elif op in ("ratio", "ratio_profit_margin"):
            # Need 2 metrics; ratio_profit_margin uses (LNST, DTT) default if only 1 metric found
            if op == "ratio_profit_margin" and len(metrics) < 2:
                # "tỷ suất lợi nhuận ròng" → LNST / DTT
                num_st, num_ms = "income_statement", "60"
                den_st, den_ms = "income_statement", "10"
            elif len(metrics) >= 2:
                num_st, num_ms, _ = metrics[0]
                den_st, den_ms, _ = metrics[1]
            else:
                result["error"] = f"ratio needs 2 metrics, got 1"
                return result
            y = years[0]
            v_num, e1 = get_value(df, ticker, y, doc_type, num_st, num_ms)
            v_den, e2 = get_value(df, ticker, y, doc_type, den_st, den_ms)
            if v_num is None or v_den is None or v_den == 0:
                result["error"] = f"missing cells: num={v_num}, den={v_den}"
                return result
            result["answer"] = v_num / v_den * 100
            result["evidence"] = e1 + e2

        elif op == "argmax":
            stmt, ms, _ = metrics[0]
            vals = []
            evs = []
            for y in years:
                v, e = get_value(df, ticker, y, doc_type, stmt, ms)
                vals.append((y, v))
                evs.extend(e)
            valid = [(y, v) for y, v in vals if v is not None]
            if not valid:
                result["error"] = "no values retrieved"
                return result
            result["answer"] = max(valid, key=lambda x: x[1])[0]
            result["evidence"] = evs

        else:
            result["error"] = f"op {op} not implemented in prototype"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


GROUND_TRUTH = {
    674: 5.28,      # % (LNST/DTT)
    605: -20.73,    # %
    582: 13.75,     # %
    656: None,      # ratio, compute expected from parquet
    904: 2024,      # year
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="674,605,582,656,904")
    args = ap.parse_args()
    target_ids = {int(x) for x in args.ids.split(",")}

    df = pd.read_parquet(PARQUET)

    records = []
    with QUESTIONS.open(encoding="utf-8") as fp:
        for line in fp:
            r = json.loads(line)
            if r["id"] in target_ids:
                records.append(r)

    print(f"Testing {len(records)} questions\n")
    results = [solve(r, df) for r in records]

    for r in results:
        gt = GROUND_TRUTH.get(r["id"])
        gt_str = f"{gt}" if gt is not None else "?"
        ans = r["answer"]
        if ans is None:
            status = "MISS"
        elif gt is None:
            status = "?"
        elif isinstance(gt, int) and ans == gt:
            status = "PASS"
        elif isinstance(gt, float) and abs(ans - gt) < 0.5:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"#{r['id']:>4} [{status:<4}] op={r['op']:<8} metrics={r['metrics']}")
        print(f"       Q: {r['question'][:90]}")
        print(f"       answer={ans}  expected={gt_str}  err={r['error']}")
        for ev in r["evidence"]:
            print(f"       ev: {ev['report_id']}|t{ev['table_pos']} ma={ev['ma_so']} p={ev['period'][:30]!r} v={ev['value']:,.0f}")
        print()

    n_pass = sum(1 for r in results if r["answer"] is not None
                 and GROUND_TRUTH.get(r["id"]) is not None
                 and (r["answer"] == GROUND_TRUTH[r["id"]]
                      or (isinstance(GROUND_TRUTH[r["id"]], float) and abs(r["answer"] - GROUND_TRUTH[r["id"]]) < 0.5)))
    total_scored = sum(1 for r in results if GROUND_TRUTH.get(r["id"]) is not None)
    print(f"{n_pass}/{total_scored} passed (of scored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
