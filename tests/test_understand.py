"""Regression tests for the structured understand node."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import finance_qa.agents.finance.understand as understand_mod
from finance_qa.agents.finance.understand import UnderstandIntent, make_understand
from finance_qa.pipelines.finance_qa import make_initial_state


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


class FakeStructuredModel:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        check("understand requests Pydantic structured output", schema is UnderstandIntent)
        return self

    def invoke(self, messages):
        check("understand sends system and human messages", len(messages) == 2)
        return self.result


cfg = SimpleNamespace(understand_thinking=False)
original_get_chat_model = understand_mod.get_chat_model

understand_mod.get_chat_model = lambda **_: FakeStructuredModel(
    UnderstandIntent(
        tickers=["BAD"],
        years=[2018, 2020],
        metric="roe",
        operation="compare",
        doc_type="unknown",
        multi_year=False,
        multi_company=False,
        unit_hint="lần",
        answer_shape="derived",
    )
)
state = make_initial_state(1, "Trong giai đoạn 2018-2020, HPG có ROE cao nhất năm nào?")
patch = make_understand(cfg)(state)
check("rule-resolved ticker overrides model guess", patch["tickers"] == ["HPG"])
check("year range is expanded after structured extraction", patch["years"] == [2018, 2019, 2020])
check("multi_year is inferred from expanded range", patch["multi_year"] is True)
check("semantic fields come from structured model", patch["operation"] == "compare" and patch["metric"] == "roe")

understand_mod.get_chat_model = lambda **_: FakeStructuredModel({"years": [2022], "operation": "lookup", "answer_shape": "single_cell"})
state = make_initial_state(2, "Doanh thu HPG năm 2022 là bao nhiêu?")
patch = make_understand(cfg)(state)
check("dict structured output is validated through Pydantic", patch["operation"] == "lookup")
check("Pydantic defaults fill omitted fields", patch["doc_type"] == "unknown" and patch["metric"] == "")

understand_mod.get_chat_model = original_get_chat_model

print("tất cả PASS")
