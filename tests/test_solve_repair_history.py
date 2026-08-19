"""Checks that the repair loop remembers what it already tried.

`_arepair` used to build a fresh two-message prompt on every attempt, so attempt 2
never saw attempt 1's query and re-emitted it. These checks run the real loop with
a stubbed repair call, so they assert on what the repair call is *handed* — which
is the thing that was missing — without touching the LLM.

  .venv_bge/bin/python tests/test_solve_repair_history.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pandas as pd

from finance_qa.modules.solve.codegen import execute as ex
from finance_qa.modules.solve.common.solution import PandasSolution

fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        fails.append(name)


# ── _attempts_block: what the model is shown ────────────────────────────────
DUMP = "ValueError: query returned non-finite nan\ndf1: 12 hàng x 4 cột; chỉ có các cột ['A']"

one = ex._attempts_block([("df1.iloc[3]['2018']", DUMP)])
check("một lần thử: có query", "df1.iloc[3]['2018']" in one)
check("một lần thử: có dòng lỗi đầu", "query returned non-finite nan" in one)
check("một lần thử: lần cuối in ĐẦY ĐỦ (còn dump cột)", "chỉ có các cột" in one)
check("một lần thử: có chỉ thị cấm lặp", "Đừng nộp lại" in one)

three = ex._attempts_block([
    ("df1.iloc[3]['2018']", DUMP),
    ("df1.iloc[4]['2018']", DUMP),
    ("df2.iloc[9]['2019']", DUMP),
])
check("ba lần thử: đủ cả 3 query",
      all(q in three for q in ("df1.iloc[3]", "df1.iloc[4]", "df2.iloc[9]")))
check("ba lần thử: chỉ lần cuối mang dump cột (không lặp 3 lần)",
      three.count("chỉ có các cột") == 1)
check("ba lần thử: các lần trước vẫn còn dòng lỗi đầu",
      three.count("query returned non-finite nan") == 3)

empty = ex._attempts_block([("", "Truy vấn rỗng — hãy viết một biểu thức pandas.")])
check("query rỗng vẫn render được", "(rỗng)" in empty)


# ── the loop: does the 2nd repair see the 1st attempt? ──────────────────────
FRAMES = {"df1": pd.DataFrame({"2018": ["x", "y"]})}   # text column: arithmetic fails

QUERIES = ["float(df1.iloc[0]['2018'])", "float(df1.iloc[1]['2018'])", "float(df1.iloc[0]['9999'])"]


def run_loop(history: bool) -> list[tuple[str, list]]:
    """Run arun_with_repair with a stub repair; return what each call was handed."""
    seen: list[tuple[str, list]] = []
    step = {"n": 0}

    async def fake_arepair(prompt, attempts, *, history):
        # Record the rendered user text the real call would send, plus the raw list.
        rendered = ex._attempts_block(attempts) if history else attempts[-1][0]
        seen.append((rendered, [q for q, _ in attempts]))
        step["n"] += 1
        return PandasSolution(pandas_query=QUERIES[min(step["n"], len(QUERIES) - 1)])

    real, ex._arepair = ex._arepair, fake_arepair
    try:
        asyncio.run(ex.arun_with_repair(
            PandasSolution(pandas_query=QUERIES[0]), "PROMPT", FRAMES,
            max_repairs=2, repair_history=history,
        ))
    finally:
        ex._arepair = real
    return seen


on = run_loop(history=True)
check("history=True: repair được gọi 2 lần (max_repairs=2)", len(on) == 2)
check("history=True: lần sửa 1 thấy 1 query đã thử", len(on[0][1]) == 1)
check("history=True: lần sửa 2 thấy CẢ HAI query đã thử", len(on[1][1]) == 2)
check("history=True: lần sửa 2 nhìn thấy query của lần 1",
      QUERIES[0] in on[1][0] and QUERIES[1] in on[1][0])

off = run_loop(history=False)
check("history=False: vẫn gọi repair 2 lần", len(off) == 2)
check("history=False: lần sửa 2 CHỈ thấy query gần nhất (bug cũ được giữ nguyên)",
      QUERIES[0] not in off[1][0] and QUERIES[1] in off[1][0])

check("hai nhánh dùng temperature khác nhau",
      ex.REPAIR_TEMPERATURE == 0.3 and ex.HISTORY_TEMPERATURE == 0.0)

print()
print(f"{len(fails)} FAIL" if fails else "tất cả PASS")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
