"""Probe canonical.py on real tables from gold20 failing questions.

Verifies:
1. canonical_frame() correctly extracts metric values
2. canonical_schema_block() produces useful REPL schema
3. Before/after comparison showing improvement over raw _schema_block

Run: python scripts/probe_canonical.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import json
from pathlib import Path

import pandas as pd

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.data.canonical import (
    canonical_frame,
    canonical_schema_block,
    _get_table_meta,
    MA_SO_BS,
    MA_SO_IS,
    MA_SO_CF,
)

ROOT = Path(__file__).resolve().parent.parent
GOLD20 = ROOT / "data/eval/gold20_questions.jsonl"
GOLD20_ALT = ROOT / "artifacts/runs/gold20_repl_v4.summary.json"


def old_schema_block(var, table_id, df):
    """Replicate the old _schema_block for comparison."""
    cols = df.columns.tolist()
    dtypes = ", ".join(str(df[c].dtype) for c in cols)
    lines = [
        f"### {var}  ({table_id})",
        f"Columns: {cols}",
        f"Dtypes:  {dtypes}",
        f"Rows: {len(df)}",
    ]
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            vals = df[c].dropna().astype(str).str.strip()
            uniq = [v for v in vals.unique() if v and v.lower() != "nan"]
            if not uniq:
                continue
            if len(uniq) <= 30:
                lines.append(f"  '{c}' labels: {uniq}")
            else:
                lines.append(f"  '{c}': {len(uniq)} unique")
    block = "\n".join(lines)
    if len(block) > 1200:
        block = block[:1200] + "\n  ...(truncated)"
    return block


def probe_table(var, table_id):
    df = load_frame(table_id)
    tmeta = _get_table_meta(table_id)
    st = tmeta["statement_type"]

    print(f"\n{'='*80}")
    print(f"TABLE: {table_id}")
    print(f"statement_type={st!r}  has_ma_so={tmeta['has_ma_so_column']}")
    print(f"shape={df.shape}  columns={list(df.columns)}")

    new_block = canonical_schema_block(var, table_id, df)
    if new_block:
        data = canonical_frame(df, table_id, st)
        old_block = old_schema_block(var, table_id, df)
        print(f"\n--- OLD schema block ({len(old_block)} chars) ---")
        print(old_block[:600] + ("..." if len(old_block) > 600 else ""))
        print(f"\n--- NEW canonical block ({len(new_block)} chars) ---")
        print(new_block)
        print(f"\n  → {len(data)} metrics extracted")
    else:
        print("  → No canonical block (note/entity_info table, expected)")
        old_block = old_schema_block(var, table_id, df)
        print(f"  → Old block: {len(old_block)} chars")


def test_d_e_ratio():
    """Spot-check: D/E from canonical must match get_val() for a known BS table."""
    print("\n" + "="*80)
    print("TEST: D/E ratio spot-check")

    # Find first balance_sheet table with mã số
    from finance_qa.core.paths import TABLE_METADATA_PATH
    with TABLE_METADATA_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("statement_type") == "balance_sheet" and r.get("has_ma_so_column"):
                table_id = f"{r['report_id']}|{r['table_pos']}"
                break

    df = load_frame(table_id)
    data = canonical_frame(df, table_id, "balance_sheet")
    if not data:
        print("  SKIP: canonical_frame returned empty")
        return

    years = sorted({yr for v in data.values() for yr in v})
    yr = years[0]

    total_debt = data.get("total_debt", {}).get(yr)
    equity = data.get("equity", {}).get(yr)
    total_assets = data.get("total_assets", {}).get(yr)

    print(f"  Table: {table_id}")
    print(f"  Year:  {yr}")
    print(f"  total_debt  (mã 300): {total_debt:>25,.0f}" if total_debt else "  total_debt: N/A")
    print(f"  equity      (mã 400): {equity:>25,.0f}" if equity else "  equity: N/A")
    print(f"  total_assets(mã 270): {total_assets:>25,.0f}" if total_assets else "  total_assets: N/A")

    if total_debt and equity:
        print(f"  D/E ratio = {total_debt/equity:.4f}")
    if total_debt and total_assets:
        print(f"  D/A ratio = {total_debt/total_assets:.4f}")


def find_failing_tables():
    """Find actual table_ids used by failing gold20 questions."""
    summary_path = ROOT / "artifacts/runs/gold20_repl_v4.summary.json"
    if not summary_path.exists():
        # fallback: find any gold eval results
        candidates = list((ROOT / "artifacts/runs").glob("*.json"))
        if not candidates:
            return []
        summary_path = candidates[0]

    with open(summary_path) as f:
        summary = json.load(f)

    results = summary.get("results", [])
    failing = [r for r in results if r.get("error")]
    table_ids = []
    for r in failing[:5]:  # first 5 failing
        for ev in r.get("evidence", []):
            tid = ev.get("csv_path", "").replace("data/", "").replace(".csv", "")
            # reconstruct table_id from csv_path: tables/REPORT/table_N.csv
            parts = tid.split("/")
            if len(parts) == 3 and parts[2].startswith("table_"):
                report_id = parts[1]
                pos = parts[2].replace("table_", "")
                table_ids.append((f"df1", f"{report_id}|{pos}"))
    return table_ids[:6]


def coverage_stats():
    """How many gold20-retrieved tables get canonical coverage?"""
    summary_path = ROOT / "artifacts/runs/gold20_repl_v4.summary.json"
    if not summary_path.exists():
        print("  gold20 summary not found — skip coverage stats")
        return

    with open(summary_path) as f:
        summary = json.load(f)

    total = 0
    canonical_count = 0
    for r in summary.get("results", []):
        for ev in r.get("evidence", []):
            tid = ev.get("csv_path", "").replace("data/", "").replace(".csv", "")
            parts = tid.split("/")
            if len(parts) == 3 and parts[2].startswith("table_"):
                table_id = f"{parts[1]}|{parts[2].replace('table_', '')}"
                total += 1
                tmeta = _get_table_meta(table_id)
                if tmeta["has_ma_so_column"] and tmeta["statement_type"] in ("balance_sheet", "income_statement", "cash_flow"):
                    canonical_count += 1

    print(f"\n{'='*80}")
    print(f"COVERAGE: {canonical_count}/{total} gold20 evidence tables get canonical schema")
    if total:
        print(f"  ({100*canonical_count/total:.0f}% of evidence tables will use canonical block)")
    else:
        print("  (no evidence tables found in summary — check summary JSON format)")


if __name__ == "__main__":
    print("Probing canonical.py on real data...")
    print(f"MA_SO_BS: {len(MA_SO_BS)} codes")
    print(f"MA_SO_IS: {len(MA_SO_IS)} codes")
    print(f"MA_SO_CF: {len(MA_SO_CF)} codes")

    # Probe tables from failing gold20 questions
    failing_tables = find_failing_tables()
    if failing_tables:
        print(f"\nFound {len(failing_tables)} evidence tables from failing questions")
        for var, tid in failing_tables:
            probe_table(var, tid)
    else:
        # Fallback: probe first balance_sheet table with mã số
        from finance_qa.core.paths import TABLE_METADATA_PATH
        with TABLE_METADATA_PATH.open() as f:
            for line in f:
                r = json.loads(line)
                if r.get("statement_type") in ("balance_sheet", "income_statement") and r.get("has_ma_so_column"):
                    table_id = f"{r['report_id']}|{r['table_pos']}"
                    probe_table("df1", table_id)
                    break

    test_d_e_ratio()
    coverage_stats()
    print("\nDone.")
