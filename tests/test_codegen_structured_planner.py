"""Regression test for the planner's Pydantic structured-output path."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import finance_qa.modules.codegen.generator as generator
from finance_qa.modules.codegen.ir import OperationPlan


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


class FakeStructuredModel:
    def with_structured_output(self, schema):
        check("planner requests Pydantic structured output", schema is OperationPlan)
        return self

    async def ainvoke(self, messages):
        check("planner sends the rendered prompt", "CÁC BẢNG" in messages[0].content)
        return OperationPlan(
            bindings=[
                {
                    "id": "revenue_2023",
                    "variable": "df1",
                    "row_index": 0,
                    "column": "2023",
                    "source_unit": "vnd",
                    "meaning": "Doanh thu năm 2023",
                }
            ],
            formula="revenue_2023",
            output_unit="million_vnd",
            explanation="Tra một ô và đổi đơn vị bằng compiler.",
        )


async def fake_indicator(_question: str) -> str:
    return ""


originals = {
    "get_chat_model": generator.get_chat_model,
    "load_frame": generator.load_frame,
    "arewrite_to_indicator": generator.arewrite_to_indicator,
    "_get_meta": generator._get_meta,
}

try:
    generator.get_chat_model = lambda **_: FakeStructuredModel()
    generator.load_frame = lambda _tid: pd.DataFrame(
        {"Chỉ tiêu": ["Doanh thu"], "2023": [123_000_000.0]}
    )
    generator.arewrite_to_indicator = fake_indicator
    generator._get_meta = lambda _tid: {
        "caption": "",
        "period_cols": set(),
        "statement_type": "income_statement",
    }

    result = generator.generate(
        "Doanh thu năm 2023 là bao nhiêu triệu đồng?",
        ["AAA_financial_statements_2023_consolidated|1"],
        fallback=False,
    )
finally:
    for name, value in originals.items():
        setattr(generator, name, value)

check("structured plan compiles and executes", result["answer"] == 123.0)
check("generate marks planner success", result["planner"] is True and result["verified"] is True)
check("historical plan dict shape is preserved", result["plan"]["bindings"][0]["id"] == "revenue_2023")

print("tất cả PASS")
