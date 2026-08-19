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
