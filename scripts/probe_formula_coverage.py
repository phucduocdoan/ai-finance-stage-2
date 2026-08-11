"""Probe: estimate how many questions formula solver can help.

No LLM calls — uses keyword patterns on question text + canonical coverage.

Usage:
  cd /home/ding/ai-finance-stage-2
  python scripts/probe_formula_coverage.py
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── Data loading ──────────────────────────────────────────────────────────────

def load_jsonl(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).open()]

def load_questions_meta() -> dict[int, dict]:
    return {int(r["id"]): r for r in load_jsonl(ROOT / "data/metadata/questions_enriched.jsonl")}

def load_frozen() -> dict[int, dict]:
    return {int(r["id"]): r for r in load_jsonl(ROOT / "artifacts/runs/regen_frozen_patched.jsonl")}

def load_table_meta() -> dict[str, dict]:
    """key: report_id|table_pos (1-indexed str)"""
    out = {}
    for r in load_jsonl(ROOT / "data/metadata/tables_metadata_v2.jsonl"):
        key = f"{r['report_id']}|{r['table_pos']}"
        out[key] = r
    return out

# ── Formula type patterns ─────────────────────────────────────────────────────

FORMULA_PATTERNS: list[tuple[str, str]] = [
    # (category_name, regex_pattern)
    ("ratio_de",    r"D/E|tỷ số nợ|hệ số nợ trên vốn|nợ[/\s]*vốn chủ"),
    ("ratio_roe",   r"\bROE\b|tỷ suất lợi nhuận.*vốn chủ|sinh lời.*vốn chủ"),
    ("ratio_roa",   r"\bROA\b|tỷ suất lợi nhuận.*tổng tài sản|sinh lời.*tài sản"),
    ("ratio_ros",   r"\bROS\b|biên lợi nhuận|tỷ suất lợi nhuận.*doanh thu"),
    ("ratio_liquidity", r"khả năng thanh toán|thanh toán hiện hành|thanh toán nhanh|thanh toán tức thời"),
    ("ratio_icr",   r"thanh toán lãi vay|ICR|interest coverage"),
    ("ratio_other", r"vòng quay|hệ số quay|tỷ lệ|tỷ suất|hệ số"),
    ("agg_sum",     r"tổng.*(?:\d{4}|\bX\b|\bnăm\b)|cộng dồn"),
    ("agg_avg",     r"trung bình|bình quân"),
    ("agg_growth",  r"tăng trưởng|tốc độ tăng|CAGR|tăng trưởng kép"),
    ("agg_minmax",  r"cao nhất|thấp nhất|lớn nhất|nhỏ nhất|tốt nhất|kém nhất"),
    ("agg_period",  r"giai đoạn \d{4}[-–]\d{4}"),
]

def detect_formula_type(question: str) -> str | None:
    q = question.lower()
    for cat, pat in FORMULA_PATTERNS:
        if re.search(pat, question, re.IGNORECASE):
            return cat
    return None

# ── Canonical coverage ────────────────────────────────────────────────────────

CANONICAL_TYPES = {"balance_sheet", "income_statement", "cash_flow"}

def has_canonical(table_ids: list[str], table_meta: dict) -> bool:
    for tid in table_ids:
        m = table_meta.get(tid, {})
        if m.get("has_ma_so_column") and m.get("statement_type") in CANONICAL_TYPES:
            return True
    return False

# ── Main analysis ─────────────────────────────────────────────────────────────

def main():
    qmeta   = load_questions_meta()
    frozen  = load_frozen()
    tmeta   = load_table_meta()

    # Segment questions
    planner_derived = []  # answer_shape != single_cell, used planner
    repl_zero       = []  # used repl, answer == 0.0

    for qid, r in frozen.items():
        q = qmeta.get(qid, {})
        shape = q.get("answer_shape", "")
        ans   = float(r.get("answer", 0) or 0)

        if r.get("planner") and not r.get("repl") and shape != "single_cell":
            planner_derived.append((qid, r, q))
        if r.get("repl") and ans == 0.0:
            repl_zero.append((qid, r, q))

    print(f"Segments: planner_derived={len(planner_derived)}, repl_zero={len(repl_zero)}")
    print()

    # ── Analysis per segment ──────────────────────────────────────────────────
    def analyse(name: str, rows: list[tuple]):
        print(f"{'='*60}")
        print(f"Segment: {name}  (n={len(rows)})")

        formula_type_counts: dict[str, int] = defaultdict(int)
        canonical_counts: dict[str, int]    = defaultdict(int)  # ftype → with canonical
        no_formula: list[tuple] = []

        for qid, r, q in rows:
            question   = r.get("question", q.get("question", ""))
            table_ids  = r.get("table_ids", [])
            ftype      = detect_formula_type(question)
            canonical  = has_canonical(table_ids, tmeta)

            if ftype:
                formula_type_counts[ftype] += 1
                if canonical:
                    canonical_counts[ftype] += 1
            else:
                no_formula.append((qid, question[:70]))

        total_formula   = sum(formula_type_counts.values())
        total_with_can  = sum(canonical_counts.values())

        print(f"  Formula-type detected:     {total_formula}/{len(rows)} ({100*total_formula/len(rows):.0f}%)")
        print(f"  Formula + canonical data:  {total_with_can}/{len(rows)} ({100*total_with_can/len(rows):.0f}%)")
        print()
        print(f"  {'Category':<20} {'count':>6}  {'w/canonical':>12}")
        print(f"  {'-'*20} {'------':>6}  {'------------':>12}")
        for ftype in sorted(formula_type_counts, key=lambda k: -formula_type_counts[k]):
            c = formula_type_counts[ftype]
            cc = canonical_counts.get(ftype, 0)
            print(f"  {ftype:<20} {c:>6}  {cc:>12}")

        print()
        print(f"  Non-formula samples (first 10):")
        for qid, q in no_formula[:10]:
            print(f"    Q{qid}: {q}")

        return total_formula, total_with_can

    pf, pc = analyse("planner_derived", planner_derived)
    print()
    rf, rc = analyse("repl_zero", repl_zero)

    # ── Score impact estimate ─────────────────────────────────────────────────
    print()
    print("="*60)
    print("Score impact estimate")
    print("  Assumptions:")
    print("    formula solver accuracy on formula+canonical: 70%")
    print("    formula solver accuracy on formula only (no canonical): 20%")
    print("    current planner_derived accuracy: ~5% → baseline correct: ~27")
    print("    current repl_zero accuracy: 0% → baseline correct: 0")
    print()

    TOTAL = 1012
    CURRENT_SCORE = 0.2628

    # planner_derived
    pd_formula_canonical = pc
    pd_formula_no_can    = pf - pc
    pd_baseline_correct  = round(len(planner_derived) * 0.05)
    pd_new_correct = round(pd_formula_canonical * 0.70 + pd_formula_no_can * 0.20)
    pd_gain = max(0, pd_new_correct - pd_baseline_correct)

    # repl_zero
    rz_formula_canonical = rc
    rz_formula_no_can    = rf - rc
    rz_new_correct = round(rz_formula_canonical * 0.70 + rz_formula_no_can * 0.20)
    rz_gain = rz_new_correct  # was 0

    total_gain = pd_gain + rz_gain
    new_score  = CURRENT_SCORE + total_gain / TOTAL

    print(f"  planner_derived: formula+canonical={pd_formula_canonical}, "
          f"formula_only={pd_formula_no_can}")
    print(f"    baseline correct: ~{pd_baseline_correct}")
    print(f"    formula solver correct: ~{pd_new_correct}")
    print(f"    net gain: +{pd_gain} câu")
    print()
    print(f"  repl_zero: formula+canonical={rz_formula_canonical}, "
          f"formula_only={rz_formula_no_can}")
    print(f"    formula solver correct: ~{rz_new_correct}")
    print(f"    net gain: +{rz_gain} câu")
    print()
    print(f"  Total gain: +{total_gain} câu")
    print(f"  Score estimate: {CURRENT_SCORE:.4f} → {new_score:.4f} "
          f"(+{new_score-CURRENT_SCORE:.4f})")
    print()
    print("  Note: assumes no regression on currently-correct questions.")


if __name__ == "__main__":
    main()
