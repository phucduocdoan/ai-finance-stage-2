"""The contract every solver submits to: a pandas expression plus its unit.

`Unit`, `PandasSolution` and `STRUCTURED_METHOD` describe *what* a solver asks the
model to return, not how any particular solver assembles the prompt around it.
`codegen` is one caller among several — cell_locator, raw_table_linker,
raw_selection_linker, formula_facts and decompose all submit a `PandasSolution`
too — so the contract lives here, in a module none of them owns, rather than in
codegen's.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Tool-calling, not the langchain default. The default (`response_format` with a
# strict json_schema) is broken on the vLLM server we talk to: the grammar lets the
# model emit unbounded whitespace inside a string, and it does — measured on qid1 it
# wrote `{"table_variable": "df1", "target_row":` then 3,900 spaces until the budget
# ran out. That killed 26 of 75 questions in the first measured run, and raising the
# budget cannot help (4096 loops exactly like 1536).
#
# Tool-calling answers the same prompt in ~110 tokens and still enforces the `Unit`
# enum. Plain json_object mode also terminates, but it is unconstrained, so the model
# invents units outside `Unit` ("triệu VND", "tỷ đồng") that fail validation.
STRUCTURED_METHOD = "function_calling"

# Mirrors units.UNITS; kept as a Literal so structured output rejects a unit the
# converter has no factor for. tests/test_solve_units.py asserts they agree.
Unit = Literal[
    "vnd", "thousand_vnd", "million_vnd", "billion_vnd", "hundred_billion_vnd",
    "trillion_vnd", "percent", "ratio", "count", "share", "year", "unknown",
]


class PandasSolution(BaseModel):
    """The model's plan and its query."""

    table_variable: str = Field(
        default="",
        description="Variable of the main table read, e.g. df1. When the expression reads "
        "several tables, name the one whose declared unit applies to the answer.",
    )
    target_row: str = Field(default="", description="Label text of the main row read, copied from the grid.")
    target_column: str = Field(default="", description="Name of the main column read, copied from the grid.")
    source_unit: Unit = Field(default="unknown", description="Unit the value is printed in.")
    target_unit: Unit = Field(default="unknown", description="Unit the question asks for.")
    pandas_query: str = Field(default="", description="Single pandas expression returning one number.")


class SeriesPart(BaseModel):
    """One company's cell for a screening question's per-company series."""

    label: str = Field(
        description="Company name or ticker, exactly as it should key the series. "
        "The same label set is reused across `selector` and `answer`.",
    )
    expr: str = Field(
        description="Pandas expression reading the ONE cell for this ONE company, e.g. "
        "df3.iloc[12][\"2023\"]. Never a slice, never a whole row or column.",
    )


class ScreeningSolution(PandasSolution):
    """Filter-then-aggregate over several companies: build a value per company,
    test a condition, then reduce the survivors to one number.

    Unlike `PandasSolution`, the model does not write `pandas_query` directly —
    `modules.solve.codegen.screening.compose` builds it from the fields below, so
    a filter predicate has somewhere to live instead of being folded into a single
    expression that adds or multiplies straight across every company.

    EVERY field except `pandas_query` is required, and that is not a style choice.
    Inheriting `PandasSolution`'s defaults left all of them optional, so the
    JSON schema's `required` list held `reduce` alone and the grammar let the
    model stop as soon as it was written. Measured on q446 (6 tables, 6,479 input
    tokens): the reply was `{"reduce": "mean"}` and nothing else, 31 output
    tokens, `finish_reason` "stop" rather than a truncation. It was not a token
    budget, 4096 produced the same empty answer, and a toy 3-table prompt filled
    every field at 1024. The cheapest legal exit is the one a model takes on a
    hard prompt, so the schema has to make the useful answer the only legal one.
    Re-declaring the five inherited fields is what puts them in `required`;
    `table_variable`, `target_column` and `target_row` are not decoration either,
    `execute.apply_units` reads all three to detect the declared source unit.
    """

    table_variable: str = Field(
        description="Variable of the main table read, e.g. df1. With several tables in play, "
        "name the one whose declared unit applies to the answer.",
    )
    target_row: str = Field(description="Label text of the main row read, copied from the grid.")
    target_column: str = Field(description="Name of the main column read, copied from the grid.")
    source_unit: Unit = Field(description="Unit the value is printed in.")
    target_unit: Unit = Field(description="Unit the question asks for.")
    selector: list[SeriesPart] = Field(
        min_length=1,
        description="One entry per company for the metric the condition tests. Must cover "
        "EVERY company the question asks about whose value you can read.",
    )
    condition: str = Field(
        description="Predicate over the per-company series, written as `s`, e.g. `s > 0` or "
        "`s > s.median()` or `s == s.max()`. Empty string means no filter: every company in "
        "`selector` is kept.",
    )
    answer: list[SeriesPart] = Field(
        description="One entry per company for the metric actually reported, when it differs "
        "from the metric `selector`/`condition` test (e.g. pick the company with the highest "
        "revenue, then report ITS profit margin). Must use the SAME set of labels as "
        "`selector`. Empty list when the reported metric is `selector`'s own.",
    )
    reduce: Literal["mean", "sum", "count", "max", "min", "median", "first"] = Field(
        description="How the surviving companies collapse to one number. Use \"first\" only "
        "when `condition` already narrows the group to the single winner (e.g. `s == s.max()`).",
    )
