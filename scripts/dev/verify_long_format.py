"""Verify long_format.parquet against manually solved ground truth.

Test: given (ticker, year, doc_type, statement_type, ma_so, period_hint, expected),
lookup the parquet and check if any matching row equals expected (within 1 VND).

Run:
  .venv_bge/bin/python scripts/verify_long_format.py
"""

from __future__ import annotations

import pandas as pd

import _bootstrap  # noqa: F401

from finance_qa.core.paths import LONG_FORMAT_PATH


PARQUET = LONG_FORMAT_PATH

# (case_id, ticker, year, doc_type, statement_type, ma_so, period_hint, expected)
# period_hint: substring that must appear in period col; use "end"/"begin" for BS heuristic
CASES = [
    ("HBC 2016 IS mã 10 (DTT)",       "HBC", 2016, "consolidated", "income_statement", "10",  None,     10_766_205_824_099),
    ("HBC 2016 IS mã 60 (LNST)",      "HBC", 2016, "consolidated", "income_statement", "60",  None,        568_013_202_926),
    ("HBC 2016 IS mã 61 (LNST mẹ)",   "HBC", 2016, "consolidated", "income_statement", "61",  None,        567_045_986_811),
    ("NLG 2024 BS mã 312 cuối kỳ",    "NLG", 2024, "consolidated", "balance_sheet",    "312", "end",   3_023_679_812_978),
    ("NLG 2024 BS mã 312 đầu kỳ",     "NLG", 2024, "consolidated", "balance_sheet",    "312", "begin", 3_814_598_243_120),
    ("MCH 2021 BS mã 320 cuối kỳ",    "MCH", 2021, "consolidated", "balance_sheet",    "320", "end",   7_445_112_961_981),
    ("MCH 2023 BS mã 320 cuối kỳ",    "MCH", 2023, "consolidated", "balance_sheet",    "320", "end",   8_468_802_865_360),
]


def _classify_period(period: str, year: int) -> str:
    """Rough guess whether a period column is end-of-year or beginning-of-year.

    BS reports two cols: "Số cuối năm" / "Số đầu năm" or "31/12/YYYY" / "1/1/YYYY".
    Header text is raw OCR — try both keyword and date matching.
    """
    p = period.lower()
    if "cuối" in p or "31/12" in p or "31.12" in p or f"31/12/{year}" in p:
        return "end"
    if "đầu" in p or "1/1" in p or "01/01" in p or f"1/1/{year}" in p:
        return "begin"
    # date containing str(year) → end; str(year-1) → begin
    if str(year) in p and str(year - 1) not in p:
        return "end"
    if str(year - 1) in p and str(year) not in p:
        return "begin"
    return "unknown"


def check_case(df: pd.DataFrame, case) -> dict:
    cid, ticker, year, doc_type, stmt, ma_so, period_hint, expected = case
    sub = df[
        (df.ticker == ticker)
        & (df.year == year)
        & (df.doc_type == doc_type)
        & (df.statement_type == stmt)
        & (df.ma_so == ma_so)
    ]
    result = {"case": cid, "n_rows": len(sub), "expected": expected}
    if sub.empty:
        result["status"] = "MISS"
        result["actual"] = None
        return result

    if period_hint in ("end", "begin"):
        sub = sub.assign(_kind=sub.period.map(lambda p: _classify_period(p, year)))
        matches = sub[sub._kind == period_hint]
        if matches.empty:
            result["status"] = "AMBIG"
            result["actual"] = sub[["period", "value"]].to_dict("records")
            return result
        sub = matches

    values = sub.value.tolist()
    if any(abs(v - expected) < 1.0 for v in values):
        result["status"] = "PASS"
        result["actual"] = expected
    else:
        result["status"] = "FAIL"
        result["actual"] = sub[["period", "value"]].to_dict("records")
    return result


def main() -> int:
    print(f"Loading {PARQUET.name}...")
    df = pd.read_parquet(PARQUET)
    print(f"  {len(df):,} rows loaded\n")

    results = [check_case(df, c) for c in CASES]

    print(f"{'case':<38}{'status':<8}{'rows':>6}")
    print("-" * 60)
    for r in results:
        print(f"{r['case']:<38}{r['status']:<8}{r['n_rows']:>6}")

    n_pass = sum(1 for r in results if r["status"] == "PASS")
    print(f"\n{n_pass}/{len(results)} passed")

    for r in results:
        if r["status"] not in ("PASS",):
            print(f"\n[{r['status']}] {r['case']}")
            print(f"  expected: {r['expected']:,}")
            print(f"  found:    {r['actual']}")

    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
