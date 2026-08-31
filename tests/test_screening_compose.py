"""Regression tests for the screening composer, no LLM.

`compose` (`modules/solve/codegen/screening.py`) turns a `ScreeningSolution` into
the one pandas expression the competition re-runs. Every composed query here goes
through `run_query` (`modules.tools.python_exec`), the same executor
`execute.aexecute` calls in production, rather than a bare `eval`: the composed
string has to survive that sandbox's AST rewriting and its globals/locals split,
and it is exactly that split which ruled out `.pipe(lambda s: ...)` as the
composition shape (see `_S_TOKEN` in screening.py).

Script style like the rest of `tests/`, not pytest: `check` raises on failure so
`python tests/test_screening_compose.py` exits non-zero.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "dev"))

from finance_qa.modules.solve.codegen.screening import compose  # noqa: E402
from finance_qa.modules.solve.common.screening import (  # noqa: E402
    is_screening as is_screening_src,
)
from finance_qa.modules.solve.common.solution import (  # noqa: E402
    ScreeningSolution,
    SeriesPart,
)
from finance_qa.modules.tools.python_exec import run_query  # noqa: E402

from gate_screening_class import is_screening as is_screening_gate  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def rejects(name: str, build: Callable[[], ScreeningSolution]) -> None:
    """A plan must be refused, whether pydantic or `compose` is the one refusing.

    Takes a thunk rather than a solution because some of these no longer survive
    construction: `selector` has `min_length=1`, so the empty case raises a
    `ValidationError` at the call site. That is still a `ValueError` subclass, so
    both refusals land here and the test does not care which layer caught it.
    """
    try:
        query = compose(build())
    except ValueError:
        check(name, True)
        return
    check(f"{name} (composed {query!r} instead of raising)", False)


def close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


# Three companies, revenue at row 0 and profit at row 1 of each one's own frame.
REVENUE = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}
PROFIT = {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}
FRAMES = {
    f"df{i}": pd.DataFrame({"2023": [REVENUE[t], PROFIT[t]]})
    for i, t in enumerate(["AAA", "BBB", "CCC"], start=1)
}
VAR_OF = {"AAA": "df1", "BBB": "df2", "CCC": "df3"}

# Required on `ScreeningSolution` and irrelevant to composition: the model has to
# fill them (see the class docstring), the composer never reads them.
BASE = {
    "table_variable": "df1",
    "target_row": "Doanh thu",
    "target_column": "2023",
    "source_unit": "vnd",
    "target_unit": "vnd",
}

SELECTOR = [SeriesPart(label=t, expr=f'{VAR_OF[t]}.iloc[0]["2023"]') for t in REVENUE]
ANSWER = [SeriesPart(label=t, expr=f'{VAR_OF[t]}.iloc[1]["2023"]') for t in REVENUE]


def run(solution: ScreeningSolution) -> float:
    return run_query(compose(solution), dict(FRAMES))


# -- the four shapes ----------------------------------------------------------
# One machine, four condition/reduce combinations. That is the whole claim being
# tested: no shape needs a field of its own.

check(
    "gộp thẳng, không có điều kiện: trung bình doanh thu cả nhóm",
    close(
        run(ScreeningSolution(**BASE, selector=SELECTOR, condition="", answer=[], reduce="mean")),
        sum(REVENUE.values()) / 3,
    ),
)

check(
    "lọc theo điều kiện tuyệt đối: đếm công ty có doanh thu > 15 (BBB, CCC)",
    run(ScreeningSolution(**BASE, selector=SELECTOR, condition="s > 15", answer=[], reduce="count")) == 2,
)

# Median revenue is BBB's 20, so only CCC clears it and the reported number is
# CCC's own profit. A composer that filtered the answer series by its own values
# instead of the selector's would return 3.0 here too, so the reduce is `mean`
# over the survivors and the selector/answer rows are deliberately not parallel
# in magnitude.
check(
    "lọc theo mốc của nhóm: trên trung vị doanh thu rồi lấy lợi nhuận",
    close(
        run(ScreeningSolution(
            **BASE, selector=SELECTOR, condition="s > s.median()", answer=ANSWER, reduce="mean",
        )),
        PROFIT["CCC"],
    ),
)

check(
    "chọn max rồi hỏi chỉ số khác: lợi nhuận của công ty doanh thu cao nhất",
    close(
        run(ScreeningSolution(
            **BASE, selector=SELECTOR, condition="s == s.max()", answer=ANSWER, reduce="first",
        )),
        PROFIT["CCC"],
    ),
)

check(
    "chọn min: lợi nhuận của công ty doanh thu thấp nhất",
    close(
        run(ScreeningSolution(
            **BASE, selector=SELECTOR, condition="s == s.min()", answer=ANSWER, reduce="first",
        )),
        PROFIT["AAA"],
    ),
)

# -- validation rejects a malformed plan --------------------------------------

rejects(
    "selector rỗng bị từ chối",
    lambda: ScreeningSolution(**BASE, selector=[], condition="", answer=[], reduce="mean"),
)

rejects(
    "nhãn selector trùng bị từ chối",
    lambda: ScreeningSolution(
        **BASE,
        selector=[
            SeriesPart(label="AAA", expr='df1.iloc[0]["2023"]'),
            SeriesPart(label="AAA", expr='df2.iloc[0]["2023"]'),
        ],
        condition="", answer=[], reduce="mean",
    ),
)

rejects(
    "answer lệch tập nhãn với selector bị từ chối",
    lambda: ScreeningSolution(
        **BASE,
        selector=SELECTOR,
        condition="s > 0",
        answer=[
            SeriesPart(label="AAA", expr='df1.iloc[1]["2023"]'),
            SeriesPart(label="ZZZ", expr='df2.iloc[1]["2023"]'),
        ],
        reduce="mean",
    ),
)

for bad_expr in (
    'df1.iloc[0]["2023"]; df2.iloc[0]["2023"]',
    'df1.__class__.iloc[0]["2023"]',
    'x = df1.iloc[0]["2023"]',
    "",
):
    rejects(
        f"expr hỏng bị từ chối: {bad_expr!r}",
        lambda bad_expr=bad_expr: ScreeningSolution(
            **BASE,
            selector=[
                SeriesPart(label="AAA", expr=bad_expr),
                SeriesPart(label="BBB", expr='df2.iloc[0]["2023"]'),
            ],
            condition="", answer=[], reduce="mean",
        ),
    )

# `and`/`or` are rejected on purpose rather than rewritten: the condition indexes
# a Series, where Python's boolean operators raise, so `&`/`|` is the only form
# that works and a silent rewrite would hide a model that does not know that.
for bad_condition in (
    "revenue > 15",
    "s > 0 and s < 100",
    "__import__('os')",
    "s > 0; s < 100",
    "s == '30'",
    "s = 5",
):
    rejects(
        f"condition hỏng bị từ chối: {bad_condition!r}",
        lambda bad_condition=bad_condition: ScreeningSolution(
            **BASE, selector=SELECTOR, condition=bad_condition, answer=[], reduce="mean",
        ),
    )

check(
    "điều kiện ghép bằng & vẫn chạy: doanh thu trong khoảng (15, 25) là BBB",
    close(
        run(ScreeningSolution(
            **BASE, selector=SELECTOR, condition="(s > 15) & (s < 25)", answer=ANSWER, reduce="first",
        )),
        PROFIT["BBB"],
    ),
)

# -- labels that could break the composed string literal ----------------------

TRICKY = ScreeningSolution(
    **BASE,
    selector=[
        SeriesPart(label='Công ty "Sao Mai"', expr='df1.iloc[0]["2023"]'),
        SeriesPart(label="BBB", expr='df2.iloc[0]["2023"]'),
    ],
    condition="", answer=[], reduce="sum",
)
check(
    "nhãn có dấu nháy và tiếng Việt không phá vỡ biểu thức",
    close(run(TRICKY), REVENUE["AAA"] + REVENUE["BBB"]) and "Sao Mai" in compose(TRICKY),
)

# -- the schema leaves the model no cheap exit --------------------------------
# The bug this guards: with the fields inherited from `PandasSolution` keeping
# their defaults, `required` held `reduce` alone, and on q446 the model replied
# `{"reduce": "mean"}` and stopped. Every field but `pandas_query` (which the
# composer writes) has to stay required, so a default added later fails here
# rather than silently turning the solver back into plain codegen.

REQUIRED = set(ScreeningSolution.model_json_schema().get("required") or [])
check(
    "mọi field trừ pandas_query đều bắt buộc",
    REQUIRED == set(ScreeningSolution.model_fields) - {"pandas_query"},
)
check(
    "pandas_query không bắt buộc, composer điền nó",
    "pandas_query" not in REQUIRED,
)

# -- one detector, two import paths -------------------------------------------

for question in (
    "So sánh HPG, HSG và NKG",
    "Trong nhóm doanh nghiệp bất động sản, công ty nào có D/E cao nhất?",
    "Doanh thu của Vinamilk năm 2023 là bao nhiêu?",
):
    check(
        f"is_screening khớp qua cả hai đường import: {question[:40]!r}",
        is_screening_src(question) == is_screening_gate(question),
    )

print("tất cả PASS")
