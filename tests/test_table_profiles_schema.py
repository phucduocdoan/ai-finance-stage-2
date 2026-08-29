"""Offline tests for shared table-linking schema primitives."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.solvers.table_linking import (  # noqa: E402
    RawCellRef,
    RawGroupCandidate,
    RawLinkRequest,
    RawScopeSlot,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


request = RawLinkRequest(
    operation="ratio",
    slots=[RawScopeSlot(ticker="ACB", year=2019)],
    target_unit="percent",
)
check("scope slot exposes stable key", request.slots[0].key == "ACB:2019")

group = RawGroupCandidate(
    id="g1",
    slot_key="ACB:2019",
    ticker="ACB",
    year=2019,
    label="Cho vay khách hàng dưới 1 năm",
    semantic_role="lt_1y",
    source_unit="million_vnd",
    cells=[
        RawCellRef(
            table_id="ACB_financial_statements_2019_separate|97",
            row_position=8,
            column="Quá hạn",
            value=1353057.0,
            source_unit="million_vnd",
        ),
        RawCellRef(
            table_id="ACB_financial_statements_2019_separate|97",
            row_position=8,
            column="Trong hạn",
            value=576520.0,
            source_unit="million_vnd",
        ),
    ],
)
check("group candidate sums physical cell values", group.value == 1929577.0)
check(
    "group candidate renders deterministic pandas sum",
    group.query({"ACB_financial_statements_2019_separate|97": "df1"})
    == "(df1.iloc[8]['Quá hạn'] + df1.iloc[8]['Trong hạn'])",
)

print("tất cả PASS")
