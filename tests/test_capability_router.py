"""Offline tests for the solve capability trace."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.capability_router import capability_trace  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def trace(state: dict) -> dict:
    return capability_trace(
        state,
        cell_locator=True,
        formula_facts=True,
        raw_table_linker=True,
        structured_facts=True,
        selection_decompose=True,
    )


Q_LOOKUP = "Vốn chủ sở hữu của FIT là bao nhiêu tỷ đồng vào ngày 31/12/2015?"
Q_ENTITY_DIFF = "Hiệu số vốn chủ sở hữu của công ty mẹ Tổng Công ty Khí Việt Nam - CTCP và công ty mẹ Tổng Công ty Điện lực Dầu khí Việt Nam tính đến ngày 31/12/2023 là bao nhiêu tỷ đồng?"
Q_NOTE_DIFF = "Tính chênh lệch quy mô dư nợ cho vay khách hàng nội địa của công ty mẹ Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh so với công ty mẹ Ngân hàng TMCP An Bình vào năm 2021 theo đơn vị triệu đồng."
Q_SELECTION = "Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, hệ số khả năng thanh toán lãi vay là bao nhiêu lần?"


lookup = trace({
    "question": Q_LOOKUP,
    "tickers": ["FIT"],
    "years": [2015],
    "doc_type": "unknown",
    "operation": "lookup",
    "answer_shape": "single_cell",
    "multi_year": False,
    "multi_company": False,
    "metric": "equity",
    "unit_hint": "tỷ đồng",
})
check("trace records capability routing basis", lookup["routing_basis"] == "capability")
check("lookup can attempt cell locator", lookup["decisions"]["cell_locator"]["attempt"])
check("lookup keeps codegen fallback enabled", lookup["decisions"]["codegen"]["attempt"])


entity_diff = trace({
    "question": Q_ENTITY_DIFF,
    "tickers": ["GAS", "POW"],
    "years": [2023],
    "doc_type": "separate",
    "operation": "multi_step",
    "answer_shape": "derived",
    "multi_year": False,
    "multi_company": True,
    "metric": "",
    "unit_hint": "tỷ đồng",
})
formula = entity_diff["decisions"]["formula_facts"]
check("main-statement entity diff is formula-capable", formula["attempt"])
check("entity diff is deterministic", formula["deterministic"])
check("entity diff records operation", formula["plan"]["operation"] == "diff")
check("entity diff preserves resolved ticker order", formula["plan"]["tickers"] == ["GAS", "POW"])


note_diff = trace({
    "question": Q_NOTE_DIFF,
    "tickers": ["HDB", "ABB"],
    "years": [2021],
    "doc_type": "separate",
    "operation": "multi_step",
    "answer_shape": "derived",
    "multi_year": False,
    "multi_company": True,
    "metric": "",
    "unit_hint": "triệu đồng",
})
check("note detail diff is blocked from formula facts", not note_diff["decisions"]["formula_facts"]["attempt"])
check("note detail diff can attempt raw table linker", note_diff["decisions"]["raw_table_linker"]["attempt"])
check("note detail diff still has codegen fallback", note_diff["decisions"]["codegen"]["attempt"])


selection = trace({
    "question": Q_SELECTION,
    "tickers": ["KBC"],
    "years": [2016, 2017, 2018, 2019, 2020],
    "doc_type": "consolidated",
    "operation": "multi_step",
    "answer_shape": "derived",
    "multi_year": True,
    "multi_company": False,
    "metric": "",
    "unit_hint": "lần",
})
check("selection text is blocked from formula facts", not selection["decisions"]["formula_facts"]["attempt"])
check("selection decompose finds a year axis", selection["decisions"]["selection_decompose"]["axis"] == "year")

print("tất cả PASS")
