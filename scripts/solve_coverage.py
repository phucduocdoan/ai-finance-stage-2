"""Run solve on all questions, measure coverage bottlenecks.

Output categories:
  ANSWERED   — pipeline returned a numeric answer (no correctness check)
  NO_METRIC  — no metric keyword matched (likely note or unfamiliar phrasing)
  NO_CELL    — metric matched but parquet returned no cell (bank/CTCK/note table)
  OP_NA      — op classifier ran but op not implemented (diff/sum/avg/...)
  ERROR      — other error (missing years, div-by-zero, etc.)

Run:
  .venv_bge/bin/python scripts/solve_coverage.py [--samples 5]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

import pandas as pd

import _bootstrap  # noqa: F401

from finance_qa.paths import REPORTS_DIR
from solve import PARQUET, QUESTIONS, solve

OUT_MD = REPORTS_DIR / "solve_coverage.md"


def categorize(r: dict) -> str:
    if r["answer"] is not None:
        return "ANSWERED"
    err = r.get("error") or ""
    if not r["metrics"]:
        return "NO_METRIC"
    if "not implemented" in err:
        return "OP_NA"
    if "missing cells" in err or "no values retrieved" in err:
        return "NO_CELL"
    return "ERROR"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(PARQUET)
    print(f"Loaded parquet: {len(df):,} rows")

    records = [json.loads(l) for l in QUESTIONS.open(encoding="utf-8")]
    print(f"Loaded questions: {len(records):,}\n")

    cats: Counter = Counter()
    op_dist: Counter = Counter()
    op_by_cat: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list] = defaultdict(list)

    for r in records:
        res = solve(r, df)
        cat = categorize(res)
        cats[cat] += 1
        op_dist[res["op"]] += 1
        op_by_cat[cat][res["op"]] += 1
        if len(samples[cat]) < args.samples:
            samples[cat].append(res)

    # Print summary
    total = sum(cats.values())
    print(f"{'Category':<12} {'Count':>7} {'Pct':>7}")
    print("-" * 30)
    for cat in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"]:
        n = cats[cat]
        print(f"{cat:<12} {n:>7} {n/total*100:>6.1f}%")
    print(f"{'TOTAL':<12} {total:>7}\n")

    print("Op distribution (all):")
    for op, n in op_dist.most_common():
        print(f"  {op:<25} {n:>5}  ({n/total*100:.1f}%)")
    print()

    print("Op × Category:")
    ops_sorted = [op for op, _ in op_dist.most_common()]
    header = f"{'op':<25}" + "".join(f"{c:>10}" for c in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"])
    print(header)
    print("-" * len(header))
    for op in ops_sorted:
        row = f"{op:<25}"
        for cat in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"]:
            row += f"{op_by_cat[cat].get(op, 0):>10}"
        print(row)

    # Write markdown report
    md = ["# Solve coverage on all questions", ""]
    md.append(f"- Total questions: **{total:,}**")
    md.append(f"- Parquet rows: **{len(df):,}**")
    md.append("")
    md.append("## Outcome distribution")
    md.append("")
    md.append("| Category | Count | Pct |")
    md.append("|---|---:|---:|")
    for cat in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"]:
        n = cats[cat]
        md.append(f"| `{cat}` | {n:,} | {n/total*100:.1f}% |")
    md.append("")
    md.append("## Op × Category")
    md.append("")
    md.append("| op | ANSWERED | NO_METRIC | NO_CELL | OP_NA | ERROR |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for op in ops_sorted:
        row = f"| `{op}` "
        for cat in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"]:
            row += f"| {op_by_cat[cat].get(op, 0)} "
        md.append(row + "|")
    md.append("")

    md.append("## Sample questions per category")
    for cat in ["ANSWERED", "NO_METRIC", "NO_CELL", "OP_NA", "ERROR"]:
        md.append(f"\n### {cat} (showing {min(args.samples, len(samples[cat]))} of {cats[cat]})")
        md.append("")
        for s in samples[cat][: args.samples]:
            md.append(f"- **#{s['id']}** op=`{s['op']}` metrics={s['metrics']} answer={s['answer']}")
            md.append(f"  - Q: {s['question']}")
            if s.get("error"):
                md.append(f"  - err: `{s['error']}`")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport: {OUT_MD}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
