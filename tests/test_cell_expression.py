"""Offline tests for the pandas expression the fact solvers carry along.

Guards the fragile half of `facts/cellexpr.py`: a stray `float()` anywhere in
`facts/execute.py` silently drops the expression and the question goes back to
shipping a hardcoded answer, which the rules score as zero. These tests fail loudly
when that happens instead of letting it through to a submission.

    PYTHONPATH=src .venv_bge/bin/python tests/test_cell_expression.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.facts import execute as execute_mod
from finance_qa.modules.solve.facts.cellexpr import Num, expression


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


A = Num(10.0, 'df0.iloc[1]["2020"]')
B = Num(4.0, 'df1.iloc[2]["2020"]')
OPAQUE = Num(3.0, None)

# ── arithmetic keeps both the value and the expression ─────────────────────────
check("Num is a plain float to everything else", isinstance(A, float) and float(A) == 10.0)
check("addition", (A + B) == 14.0 and (A + B).expr == '(df0.iloc[1]["2020"] + df1.iloc[2]["2020"])')
check("subtraction", (A - B).expr == '(df0.iloc[1]["2020"] - df1.iloc[2]["2020"])')
check("division", (A / B) == 2.5 and (A / B).expr.endswith('/ df1.iloc[2]["2020"])'))
check("scaling by a plain float", (A * 1e-09).expr == '(df0.iloc[1]["2020"] * 1e-09)')
check("reflected operand", (1.0 - A).expr == '(1.0 - df0.iloc[1]["2020"])')
check("abs", abs(-A).expr == 'abs(-(df0.iloc[1]["2020"]))')
check("round", round(A / B, 2).expr.startswith("round("))
check("sum() starts from int 0 and survives", sum([A, B]).expr is not None)

# ── an unlocatable cell poisons everything it touches ──────────────────────────
check("opaque operand loses the expression", (A + OPAQUE).expr is None)
check("opaque operand keeps the value", (A + OPAQUE) == 13.0)
check("a poisoned chain stays poisoned", ((A + OPAQUE) * 2.0).expr is None)
check("plain constants are literals, not poison", expression(2.0) == "2.0")

# ── the executor's own arithmetic must not strip it ────────────────────────────
check("_divide keeps the expression", execute_mod._divide(A, B).expr is not None)
check("_scale ratio->percent keeps it", execute_mod._scale(A, "ratio", "percent").expr is not None)
check("_scale money keeps it", execute_mod._scale(A, "vnd", "billion_vnd").expr is not None)


class _Ctx:
    names = {"REP|5": "df0", "REP|6": "df1"}


check(
    "a live expression emits evidence for exactly the frames it reads",
    execute_mod._query_and_evidence(A, _Ctx())[1] == [
        {"variable": "df0", "csv_path": "data/REP_table_5.csv"}
    ],
)
check(
    "an opaque result falls back to the constant with no evidence",
    execute_mod._query_and_evidence(OPAQUE, _Ctx()) == ("3.0", []),
)

print("tất cả PASS")
