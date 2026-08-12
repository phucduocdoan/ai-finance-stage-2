"""One LLM call: read the evidence grids, emit one pandas expression.

The model decides one thing and nothing else — which cells to read. It does not
choose a solver route, does not plan a multi-step program, and does not write unit
arithmetic (`execute.apply_units` does that from the unit detected in the grid).
Everything the old codegen package spent 3,900 lines on was scaffolding around a
model that had never been shown the table's contents.

The structured fields beyond `pandas_query` are a debug trace, not output. When an
answer is wrong they say *where*: a wrong `table_variable` is a retrieval failure, a
wrong `target_row`/`target_column` is a table-understanding failure, a right row
with a wrong number is a query failure. Without them every wrong answer looks the
same. They describe the *main* cell only — `table_variable` also selects the table
whose declared unit `apply_units` converts from, so it must be the table that
carries the answer's unit.
"""
from __future__ import annotations

from typing import Literal, Mapping

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.context import table_context

# Completion budget. A well-formed reply is ~110 tokens (measured over 4 questions),
# so this is pure headroom. It is NOT a fix for truncation: see STRUCTURED_METHOD.
MAX_TOKENS = 1024

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

CODEGEN_SYSTEM = """You answer Vietnamese financial questions by writing ONE pandas expression.

You are shown the question and the full contents of the evidence tables, each bound
to a variable (df1, df2, ...). The left-most number on each grid row is that row's
integer position.

Your tasks:
1. Find every cell the question needs. Most questions need one. A question that
   compares two companies, two years, or asks for a difference, a sum, a ratio or a
   growth rate needs several — and cells for two different companies are in two
   different tables.
2. Write a single pandas expression over those cells, returning ONE number.
3. Report the unit the value is printed in, and the unit the question asks for.
4. Report which table, row and column the main cell came from.

Constraints:
- Use only the variables shown (df1, df2, ...). `pd` is available. No imports, no
  file access, no assignments, no print.
- Not every table shown is relevant; several may cover the same company and year.
  Read from the ones whose rows actually carry the metric asked for, and ignore the
  rest. Do not force the answer out of one table when the question spans two.
- The expression may combine cells from several tables:
  `df1.iloc[12]["2023"] - df4.iloc[9]["2023"]` is a valid answer.
- The expression must evaluate to a single scalar, not a Series or DataFrame.
- Index rows by position with `.iloc[...]`, using the row numbers shown in the grid.
  Never use `.loc[...]` and never use `.str.contains(...)`: you can already see which
  row it is, and a lookup that matches two rows or zero rows fails at execution time.
  In particular `df1.loc["Lãi tiền gửi", "2018"]` is wrong — the row label text is
  not the index. Write `df1.iloc[7]["2018"]` with the position from the grid.
- A column name must be copied from the grid header CHARACTER FOR CHARACTER, even
  when extraction mangled it (`"...31tháng 12 năm 2024VND"`). Never append a year,
  a period or a unit to a column name that does not already contain it: most of
  these headers say `Số cuối năm` or `Tại ngày 31 tháng 12 năm` with no year, and
  `df1["Tại ngày 31 tháng 12 năm 2018"]` is a KeyError, not a fix.
- Which period each money column holds is given to you by the "Năm của từng cột
  số tiền" line under the table header, when the header itself does not say. Use
  that line to pick the column; do not guess from the column's position.
- Read the value AS PRINTED. Apply NO unit scaling, no `/1e6`, no `* 1000`. Report
  the units instead and the scaling is applied for you. A trailing factor of 1000 or
  more is removed from your query before it runs, so writing one only hides your
  intent — it cannot change the answer.
- Numeric columns are already numeric; do not call `.replace(",", "")` or
  `pd.to_numeric` on them. Wrap in `pd.to_numeric(..., errors="coerce")` only when
  the value sits in a text column.
- Percentages: if the table prints 12.5 for 12.5%, return 12.5 and set
  source_unit=percent.

source_unit is the unit the table DECLARES, copied from what it says — a banner row
"Triệu VND", a column name, or the "Đơn vị bảng khai báo" line in the context header.
It is not a description of how large the number is: a cell printed 4.263.610.960.357
with no declaration is source_unit=vnd, not trillion_vnd. Use "unknown" when the table
declares nothing, and "percent" or "ratio" when the value is not money at all — that
is the case where your answer decides whether any conversion happens.

Set target_unit to the unit the question asks for, or "unknown" if it does not say."""


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


def build_prompt(question: str, frames: Mapping[str, pd.DataFrame], names: Mapping[str, str]) -> str:
    """Question + full grid of every evidence table."""
    blocks = [
        table_context(var, names[var], frames[var])
        for var in names
        if var in frames
    ]
    return f"Câu hỏi: {question}\n\n" + "\n\n".join(blocks)


async def agenerate(
    question: str,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    *,
    thinking: bool = True,
) -> tuple[PandasSolution, str]:
    """Generate the solution for one question. Returns ``(solution, prompt)``.

    The prompt is returned so `execute` can reuse it verbatim for the repair call
    — the repair must see the same grids, or it will "fix" the query by guessing.
    """
    prompt = build_prompt(question, frames, names)
    result = await get_chat_model(thinking=thinking, max_tokens=MAX_TOKENS).with_structured_output(
        PandasSolution, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=CODEGEN_SYSTEM), HumanMessage(content=prompt)])
    if not isinstance(result, PandasSolution):
        result = PandasSolution.model_validate(result)
    return result, prompt


__all__ = [
    "CODEGEN_SYSTEM", "MAX_TOKENS", "STRUCTURED_METHOD", "PandasSolution", "Unit",
    "agenerate", "build_prompt",
]
