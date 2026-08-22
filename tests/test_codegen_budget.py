"""Regression tests for the table ordering and budget codegen is handed.

No frames, no metadata, no LLM: `codegen_budget` and the two round-robins are
pure functions over table-id strings, and every bug they had was a string bug.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.agents.finance.graph import codegen_budget  # noqa: E402
from finance_qa.agents.finance.utils import (  # noqa: E402
    slot_round_robin,
    year_round_robin,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def tid(ticker: str, year: int, pos: int, kind: str = "consolidated") -> str:
    return f"{ticker}_financial_statements_{year}_{kind}|{pos}"


# Explicit, not `FinanceAgentConfig()`: the shipped default for the multi-company
# ceiling is a judgement call that has already changed once, and these tests are about
# the routing arithmetic, not about which number won that argument. Pinning it here
# keeps a default change from turning into a red test that says nothing.
CFG = replace(FinanceAgentConfig(), codegen_max_tables_multi_company=12)


def tickers_of(table_ids: list[str]) -> list[str]:
    return [t.split("_", 1)[0] for t in table_ids]


# -- slot_round_robin ---------------------------------------------------------

check("empty list survives", slot_round_robin([]) == [])

single = [tid("ACB", 2020, p) for p in (1, 2, 3)]
check("one company one year is returned unchanged", slot_round_robin(single) == single)

# The shape that lost OGC on q392: one id in the corpus writes the year before
# the report kind, so a `_financial_statements_<year>` pattern misses it.
odd = [
    tid("MCH", 2024, 11),
    "MCH_2024_financial_statement_explanations_1|1",
    tid("QNS", 2024, 10),
    tid("OGC", 2024, 7),
]
check(
    "an off-shape id does not claim a slot of its own",
    tickers_of(slot_round_robin(odd)[:3]) == ["MCH", "QNS", "OGC"],
)

# The shape that lost MSN on q608: the pool carries every year in the expanded
# range, so a flat (ticker, year) interleave let one company own the budget.
crowded = [
    tid("MML", y, 1) for y in (2018, 2023, 2022, 2019, 2020, 2021)
] + [tid("MSN", y, 2) for y in (2018, 2023)]
check(
    "every company appears before any company appears twice",
    tickers_of(slot_round_robin(crowded)[:2]) == ["MML", "MSN"],
)
check(
    "year order inside a company is preserved",
    [t for t in slot_round_robin(crowded) if t.startswith("MML")]
    == [tid("MML", y, 1) for y in (2018, 2023, 2022, 2019, 2020, 2021)],
)

check(
    "nothing is dropped or duplicated",
    sorted(slot_round_robin(crowded)) == sorted(crowded),
)

# -- year_round_robin is untouched by sharing `_interleave` -------------------

years = [tid("ACB", 2020, 1), tid("ACB", 2020, 2), tid("ACB", 2021, 3)]
check(
    "year_round_robin still interleaves years, best first",
    year_round_robin(years) == [tid("ACB", 2020, 1), tid("ACB", 2021, 3), tid("ACB", 2020, 2)],
)

# -- codegen_budget routing --------------------------------------------------

one_company = {"table_ids": single, "tickers": ["ACB"], "years": [2020]}
check(
    "a single-company question keeps the narrow budget and the ranking",
    codegen_budget(one_company, CFG) == (single, CFG.codegen_max_tables),
)

period = {"table_ids": years, "tickers": ["ACB"], "years": [2020, 2021], "multi_year": True}
check(
    "a period question gets the multi-year budget",
    codegen_budget(period, CFG)[1] == CFG.codegen_max_tables_multi_year,
)

screen = {
    "table_ids": crowded,
    "tickers": ["MML", "MSN"],
    "years": [2018, 2023],
    "multi_year": True,
}
ordered, budget = codegen_budget(screen, CFG)
check("a screening question is sized by (ticker x year) slots", budget == 4)
check(
    "company breadth beats year depth when both are asked for",
    set(tickers_of(ordered[:budget])) == {"MML", "MSN"},
)

wide = {"table_ids": crowded, "tickers": list("ABCDEFGHIJ"), "years": [2023, 2024]}
check(
    "the budget is capped rather than growing with the ticker count",
    codegen_budget(wide, CFG)[1] == CFG.codegen_max_tables_multi_company,
)

narrow_pair = {"table_ids": crowded, "tickers": ["MML", "MSN"], "years": []}
check(
    "two companies and no year never go below the base budget",
    codegen_budget(narrow_pair, CFG)[1] == CFG.codegen_max_tables,
)

# The shipped default sets the ceiling equal to the base budget, which turns the
# widening off and leaves only the re-ordering. That combination is the one running in
# production, so it gets its own check rather than being inferred from the two above.
NO_WIDEN = replace(
    FinanceAgentConfig(),
    codegen_max_tables_multi_company=FinanceAgentConfig().codegen_max_tables,
)
ordered_narrow, budget_narrow = codegen_budget(screen, NO_WIDEN)
check(
    "with the ceiling at the base budget no extra table is loaded",
    budget_narrow == NO_WIDEN.codegen_max_tables,
)
check(
    "...but the head is still interleaved, so both companies fit in three slots",
    set(tickers_of(ordered_narrow[:budget_narrow])) == {"MML", "MSN"},
)

# -- the screening override lifts the ceiling, and only when asked to ---------
# `screening_solver` raises the ceiling to 12 for a screening-shaped question,
# because the widening was measured flat on its own (coverage 310/310, score
# 4/38) and only pairs with somewhere to put a filter. Both halves of that need a
# check: the flag alone must change nothing, and the question shape alone must
# change nothing either.

SCREENING_ON = replace(NO_WIDEN, screening_solver=True)
many = {"table_ids": crowded, "tickers": list("ABCDEFGHIJ"), "years": [2023]}
screening_question = "So sánh HPG, HSG và NKG năm 2023"

check(
    "flag on plus a screening question loads a table per ticker (10 of them)",
    codegen_budget({**many, "question": screening_question}, SCREENING_ON)[1] == 10,
)
check(
    "the lifted ceiling still caps: 8 tickers x 2 years wants 16, gets 12",
    codegen_budget(
        {"table_ids": crowded, "tickers": list("ABCDEFGH"), "years": [2023, 2024],
         "question": screening_question},
        SCREENING_ON,
    )[1] == 12,
)
check(
    "flag on but a single-company question keeps the shipped ceiling",
    codegen_budget(
        {**many, "question": "Doanh thu của Vinamilk năm 2023 là bao nhiêu?"}, SCREENING_ON
    )[1] == NO_WIDEN.codegen_max_tables,
)
check(
    "a screening question with the flag off keeps the shipped ceiling",
    codegen_budget({**many, "question": screening_question}, NO_WIDEN)[1]
    == NO_WIDEN.codegen_max_tables,
)
check(
    "no question text is not a crash, it is just not screening",
    codegen_budget(many, SCREENING_ON)[1] == NO_WIDEN.codegen_max_tables,
)

print("tất cả PASS")
