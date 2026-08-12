"""Build numeric long-format derived data from BS/IS/CF tables."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from finance_qa.core.paths import DATA_DIR, LONG_FORMAT_PATH, REPORTS_DIR, TABLE_METADATA_PATH


TARGET_TYPES = {"balance_sheet", "income_statement", "cash_flow"}
MA_SO_RE = re.compile(r"^\d{2,4}$")
REPORT_RE = re.compile(r"^(.+?)_financial_statements_(\d{4})_(separate|consolidated)$")


@dataclass(frozen=True)
class LongFormatPaths:
    output_dir: Path = DATA_DIR
    metadata_path: Path = TABLE_METADATA_PATH
    parquet_path: Path = LONG_FORMAT_PATH
    stats_path: Path = REPORTS_DIR / "long_format_stats.md"


def parse_report_id(rid: str) -> tuple[str | None, int | None, str | None]:
    m = REPORT_RE.match(rid)
    if not m:
        return None, None, None
    return m.group(1), int(m.group(2)), m.group(3)


def parse_number(s: str | None) -> float | None:
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


def detect_columns(cols: list[str]) -> tuple[str, str | None, str | None, list[str]]:
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


class LongFormatBuilder:
    """Build one row per numeric statement value for deterministic metric access."""

    def __init__(self, paths: LongFormatPaths | None = None) -> None:
        self.paths = paths or LongFormatPaths()

    def load_targets(self, limit: int | None = None) -> list[dict]:
        out: list[dict] = []
        with self.paths.metadata_path.open(encoding="utf-8") as fp:
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

    def process_table(self, meta: dict, records: list[dict], skipped: Counter) -> int:
        csv_path = self.paths.output_dir / meta["csv_path"]
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
                records.append(
                    {
                        "report_id": meta["report_id"],
                        "ticker": ticker,
                        "year": year,
                        "doc_type": doc_type,
                        "statement_type": meta["statement_type"],
                        "statement_subtype": meta.get("statement_subtype"),
                        "table_pos": meta["table_pos"],
                        "ma_so": ma_so,
                        "label": label,
                        "note_id": note_id or None,
                        "period": pcol.strip(),
                        "value": val,
                    }
                )
                emitted += 1
        return emitted

    def write_stats(self, df: pd.DataFrame, n_tables: int, skipped: Counter, elapsed: float) -> None:
        lines = ["# Long-format build stats", ""]
        lines.append(f"- Tables processed: **{n_tables:,}**")
        lines.append(f"- Rows emitted: **{len(df):,}**")
        lines.append(f"- Unique reports: **{df['report_id'].nunique():,}**")
        lines.append(f"- Unique tickers: **{df['ticker'].nunique():,}**")
        lines.append(f"- Years: **{df['year'].min()}-{df['year'].max()}**")
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
            for key, value in skipped.most_common():
                lines.append(f"| `{key}` | {value:,} |")
            lines.append("")
        self.paths.stats_path.write_text("\n".join(lines), encoding="utf-8")

    def run(self, limit: int | None = None) -> int:
        self.paths.parquet_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.stats_path.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        print(f"Loading targets from {self.paths.metadata_path.name}...")
        targets = self.load_targets(limit)
        print(f"  {len(targets):,} target tables (BS+IS+CF with Mã số)")

        records: list[dict] = []
        skipped: Counter = Counter()
        for i, meta in enumerate(targets, 1):
            self.process_table(meta, records, skipped)
            if i % 500 == 0:
                print(f"  [{i:,}/{len(targets):,}] rows so far: {len(records):,}")

        if not records:
            print("No records emitted. Aborting.", file=sys.stderr)
            return 1

        df = pd.DataFrame.from_records(records)
        print(f"\nTotal rows: {len(df):,}")
        df.to_parquet(self.paths.parquet_path, index=False, compression="snappy")
        print(f"Wrote {self.paths.parquet_path} ({self.paths.parquet_path.stat().st_size / 1e6:.1f} MB)")

        elapsed = time.perf_counter() - t0
        self.write_stats(df, len(targets), skipped, elapsed)
        print(f"Stats: {self.paths.stats_path}")
        print(f"Done in {elapsed:.1f}s")
        return 0

    async def arun(self, limit: int | None = None) -> int:
        return await asyncio.to_thread(self.run, limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Debug: cap number of tables")
    args = parser.parse_args(argv)
    return LongFormatBuilder().run(limit=args.limit)
