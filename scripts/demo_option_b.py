"""Concrete walkthrough of Option B (materialize long-format fact table → reason).

Shows the two core artifacts for Q396:
  1. materialize node output  — the tidy fact table (deterministic, from get_v)
  2. reason node output       — plain pandas over the CLEAN table → answer

Run:
    PYTHONPATH=src .venv_bge/bin/python scripts/demo_option_b.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

import pandas as pd

from eval_gold import get_v_signed

BS, IS, CF = "balance_sheet", "income_statement", "cash_flow"

# CORE_MASO: fixed ~15-code panel covering every ratio in the gold set.
#   (statement, mã_số, human label)
CORE_MASO = [
    (IS, 10, "Doanh thu thuần"),
    (IS, 11, "Giá vốn hàng bán"),
    (IS, 20, "Lợi nhuận gộp"),
    (IS, 30, "LN thuần HĐKD"),
    (IS, 23, "Chi phí lãi vay"),
    (IS, 50, "LN trước thuế"),
    (IS, 60, "LN sau thuế (NPAT)"),
    (CF, 20, "Lưu chuyển tiền thuần HĐKD (CFO)"),
    (BS, 100, "Tài sản ngắn hạn"),
    (BS, 140, "Hàng tồn kho"),
    (BS, 220, "Tài sản cố định thuần"),
    (BS, 270, "Tổng tài sản"),
    (BS, 300, "Nợ phải trả"),
    (BS, 310, "Nợ ngắn hạn"),
    (BS, 400, "Vốn chủ sở hữu"),
]


def materialize(tickers: list[str], years: list[int]) -> pd.DataFrame:
    """NODE: materialize — deterministic. Fan get_v over (ticker × year × CORE_MASO)."""
    rows = []
    for tk in tickers:
        for yr in years:
            for stype, maso, label in CORE_MASO:
                rows.append({
                    "ticker": tk, "year": yr, "stmt": stype,
                    "ma_so": maso, "label": label,
                    "value": get_v_signed(tk, yr, stype, maso),
                })
    return pd.DataFrame(rows)


def reason_q396(facts: pd.DataFrame) -> float | None:
    """NODE: reason — the ONLY thing the LLM writes. Plain pandas over the clean table.

    Q396: among ASM/DBC/MSN/OGC (2024) with CFO>0 AND NPAT>0, the firm with the
    highest CFO/NPAT — what is its quick ratio (CA-Inv)/CL?
    """
    def cell(tk, ma):
        v = facts[(facts.ticker == tk) & (facts.ma_so == ma)]["value"]
        return v.iloc[0] if len(v) and pd.notna(v.iloc[0]) else None

    best_tk, best_ratio = None, None
    for tk in facts.ticker.unique():
        cfo, npat = cell(tk, 20), cell(tk, 60)          # note: ma_so 20 = CFO here (stmt=cash_flow)
        # disambiguate the two ma_so==20 rows by statement:
        cfo = facts[(facts.ticker == tk) & (facts.stmt == CF) & (facts.ma_so == 20)]["value"]
        cfo = cfo.iloc[0] if len(cfo) else None
        if cfo is None or npat is None or cfo <= 0 or npat <= 0:
            continue                                     # qualification filter (signed!)
        ratio = cfo / npat
        if best_ratio is None or ratio > best_ratio:
            best_ratio, best_tk = ratio, tk
    if best_tk is None:
        return None
    ca, inv, cl = cell(best_tk, 100), cell(best_tk, 140), cell(best_tk, 310)
    return (ca - inv) / cl


def validate(answer: float | None, facts: pd.DataFrame, n_expected: int) -> str:
    """NODE: validate — deterministic guardrails before accepting."""
    if answer is None:
        return "FAIL: no answer produced"
    if not pd.notna(answer):
        return "FAIL: non-finite"
    # completeness: every scoped firm must have its qualifying cells (else silent-skew, R2)
    have = facts[(facts.stmt == CF) & (facts.ma_so == 20)]["value"].notna().sum()
    if have < n_expected:
        return f"WARN: only {have}/{n_expected} firms have CFO — median/rank may skew (R2)"
    return "PASS"


if __name__ == "__main__":
    # scope node (LLM, tiny) would output this from the question text:
    tickers, years = ["ASM", "DBC", "MSN", "OGC"], [2024]

    facts = materialize(tickers, years)
    print("=== materialize node output (tidy fact table) ===")
    print(facts.to_string(index=False))

    ans = reason_q396(facts)
    print("\n=== reason node output ===")
    print(f"answer (MSN quick ratio) = {ans}")
    print(f"gold = 0.728678   → {'MATCH' if ans and abs(ans-0.728678)<1e-3 else 'MISS'}")

    print("\n=== validate node output ===")
    print(validate(ans, facts, n_expected=4))
