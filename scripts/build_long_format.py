"""Build long-format parquet from BS/IS/CF tables.

One row per (report_id, statement_type, mã_số, period). Numeric values only.

Run:
  .venv_bge/bin/python scripts/build_long_format.py [--limit N]

Output:
  data/derived/long_format.parquet
  artifacts/reports/long_format_stats.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter

import pandas as pd

import _bootstrap  # noqa: F401

from finance_qa.paths import (
    DATA_DIR,
    LONG_FORMAT_PATH,
    REPORTS_DIR,
    TABLE_METADATA_V1_PATH,
)


OUTPUT_DIR = DATA_DIR
METADATA_PATH = TABLE_METADATA_V1_PATH
PARQUET_PATH = LONG_FORMAT_PATH
STATS_PATH = REPORTS_DIR / "long_format_stats.md"

TARGET_TYPES = {"balance_sheet", "income_statement", "cash_flow"}
MA_SO_RE = re.compile(r"^\d{2,4}$")
REPORT_RE = re.compile(r"^(.+?)_financial_statements_(\d{4})_(separate|consolidated)$")


def parse_report_id(rid: str) -> tuple[str | None, int | None, str | None]:
    m = REPORT_RE.match(rid)
    if not m:
        return None, None, None
    return m.group(1), int(m.group(2)), m.group(3)


def parse_number(s: str | None) -> float | None:
    """Parse Vietnamese-formatted number. Dots = thousands sep, comma = decimal.

    Handles:
      "1.071.561.008.455" → 1071561008455
      "(162.105.381)"     → -162105381
      "-", "", "_"        → None
      "1.234,56"          → 1234.56
    """
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "-", "_", ".", "N/A", "n/a"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    s = s.replace(" ", "").replace("\xa0", "")
    if "," in s:
        int_part, _, dec_part = s.rpartition(",")
        int_part = int_part.replace(".", "")
        cleaned = f"{int_part}.{dec_part}" if int_part else dec_part
    else:
        cleaned = s.replace(".", "")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if neg else val


def load_targets(limit: int | None) -> list[dict]:
    """Load metadata rows for BS/IS/CF with Mã số column."""
    out: list[dict] = []
    with METADATA_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            if rec.get("statement_type") not in TARGET_TYPES:
                continue
            if not rec.get("has_ma_so_column"):
                continue
            out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


def detect_columns(cols: list[str]) -> tuple[str, str | None, str | None, list[str]]:
    """Return (label_col, ma_so_col, thuyet_minh_col, period_cols)."""
    label_col = cols[0]
    ma_so_col: str | None = None
    tm_col: str | None = None
    for c in cols:
        cn = c.strip().lower()
        if ma_so_col is None and ("mã số" in cn or "ma so" in cn):
            ma_so_col = c
        elif tm_col is None and ("thuyết minh" in cn or "thuyet minh" in cn or cn == "tm"):
            tm_col = c
    used = {label_col}
    if ma_so_col:
        used.add(ma_so_col)
    if tm_col:
        used.add(tm_col)
    period_cols = [c for c in cols if c not in used and c.strip()]
    return label_col, ma_so_col, tm_col, period_cols


def process_table(meta: dict, records: list[dict], skipped: Counter) -> int:
    csv_path = OUTPUT_DIR / meta["csv_path"]
    if not csv_path.exists():
        skipped["csv_missing"] += 1
        return 0

    ticker, year, doc_type = parse_report_id(meta["report_id"])
    if ticker is None:
        skipped["bad_report_id"] += 1
        return 0

    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception:
        skipped["csv_read_error"] += 1
        return 0

    if df.empty or len(df.columns) < 3:
        skipped["too_few_cols"] += 1
        return 0

    label_col, ma_so_col, tm_col, period_cols = detect_columns(list(df.columns))
    if not ma_so_col or not period_cols:
        skipped["cols_undetected"] += 1
        return 0

    stmt_type = meta["statement_type"]
    stmt_subtype = meta.get("statement_subtype")
    report_id = meta["report_id"]
    table_pos = meta["table_pos"]

    emitted = 0
    for _, row in df.iterrows():
        ma_so = str(row[ma_so_col]).strip()
        if not MA_SO_RE.match(ma_so):
            continue
        label = str(row[label_col]).strip()
        note_id = str(row[tm_col]).strip() if tm_col else ""
        for pcol in period_cols:
            val = parse_number(row[pcol])
            if val is None:
                continue
            records.append({
                "report_id": report_id,
                "ticker": ticker,
                "year": year,
                "doc_type": doc_type,
                "statement_type": stmt_type,
                "statement_subtype": stmt_subtype,
                "table_pos": table_pos,
                "ma_so": ma_so,
                "label": label,
                "note_id": note_id or None,
                "period": pcol.strip(),
                "value": val,
            })
            emitted += 1
    return emitted


def write_stats(df: pd.DataFrame, n_tables: int, skipped: Counter, elapsed: float) -> None:
    lines = ["# Long-format build stats", ""]
    lines.append(f"- Tables processed: **{n_tables:,}**")
    lines.append(f"- Rows emitted: **{len(df):,}**")
    lines.append(f"- Unique reports: **{df['report_id'].nunique():,}**")
    lines.append(f"- Unique tickers: **{df['ticker'].nunique():,}**")
    lines.append(f"- Years: **{df['year'].min()}–{df['year'].max()}**")
    lines.append(f"- Time: **{elapsed:.1f}s**")
    lines.append("")
    lines.append("## Rows per statement_type")
    lines.append("")
    lines.append("| statement_type | rows |")
    lines.append("|---|---:|")
    for st, n in df["statement_type"].value_counts().items():
        lines.append(f"| `{st}` | {n:,} |")
    lines.append("")
    if skipped:
        lines.append("## Skipped tables")
        lines.append("")
        lines.append("| reason | count |")
        lines.append("|---|---:|")
        for k, v in skipped.most_common():
            lines.append(f"| `{k}` | {v:,} |")
        lines.append("")
    STATS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Debug: cap number of tables")
    args = ap.parse_args()

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    print(f"Loading targets from {METADATA_PATH.name}...")
    targets = load_targets(args.limit)
    print(f"  {len(targets):,} target tables (BS+IS+CF with Mã số)")

    records: list[dict] = []
    skipped: Counter = Counter()
    for i, meta in enumerate(targets, 1):
        process_table(meta, records, skipped)
        if i % 500 == 0:
            print(f"  [{i:,}/{len(targets):,}] rows so far: {len(records):,}")

    if not records:
        print("No records emitted. Aborting.", file=sys.stderr)
        return 1

    df = pd.DataFrame.from_records(records)
    print(f"\nTotal rows: {len(df):,}")

    df.to_parquet(PARQUET_PATH, index=False, compression="snappy")
    print(f"Wrote {PARQUET_PATH} ({PARQUET_PATH.stat().st_size / 1e6:.1f} MB)")

    elapsed = time.perf_counter() - t0
    write_stats(df, len(targets), skipped, elapsed)
    print(f"Stats: {STATS_PATH}")
    print(f"Done in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
