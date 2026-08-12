"""Second look at a query that ran: is this the cell the question asked for?

The repair loop only fires on exceptions, so it never sees the largest failure
bucket. Measured on 73 gold questions: 34 right, ~34 that execute cleanly and
return the wrong cell, ~5 that throw. Repair addresses the 5.

This node addresses the 34. It is not a re-generation and not an agent: one call,
shown what the query *actually touched* rather than what the model claimed it
touched. That distinction is the point — `target_row` / `target_column` are the
model's own report, and on a wrong answer they are wrong too. Here the row labels
are read out of the dataframe by position, so the check has ground truth the
generator did not.

Neighbouring rows come along because the right row is usually adjacent to the one
picked: `Lợi nhuận sau thuế` sits under `Lợi nhuận trước thuế`, and a verdict of
"wrong row" is only actionable if the alternative is visible.
"""
from __future__ import annotations

import re
from typing import Mapping

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen import CODEGEN_SYSTEM, STRUCTURED_METHOD, PandasSolution
from finance_qa.modules.solve.context import meta_for

MAX_TOKENS = 512

# Same reason as execute.REPAIR_TEMPERATURE: the revise prompt differs from the
# generation prompt by one appended paragraph, and at 0 the model hands back the
# query it just wrote.
REVISE_TEMPERATURE = 0.3

# `df1.iloc[12]` and `df1.iloc[12, 3]`. Only positional access is matched because
# the codegen prompt forbids `.loc`; a query that slipped past that just yields no
# rows here and the verifier judges on the value alone.
_ILOC = re.compile(r"\b(df\d+)\.iloc\[\s*(\d+)")

# Rows shown either side of the one the query read.
_NEIGHBOURS = 2


def _row_line(df: pd.DataFrame, position: int, marker: str) -> str:
    cells = "; ".join(
        f"{col}={df.iat[position, i]}" for i, col in enumerate(map(str, df.columns))
    )
    return f"{marker} [{position}] {cells}"


def touched_rows(query: str, frames: Mapping[str, pd.DataFrame], names: Mapping[str, str]) -> str:
    """The rows the query indexed, in full, with their neighbours for contrast."""
    blocks: list[str] = []
    seen: set[tuple[str, int]] = set()
    for var, raw in _ILOC.findall(query):
        frame = frames.get(var)
        position = int(raw)
        if frame is None or position >= len(frame) or (var, position) in seen:
            continue
        seen.add((var, position))
        meta = meta_for(names.get(var, ""))
        head = (
            f"### {var} — {meta.get('company_name') or meta.get('ticker') or '?'} "
            f"({meta.get('ticker') or '?'}), báo cáo năm {meta.get('year') or '?'}, "
            f"{meta.get('statement_type') or meta.get('doc_type') or '?'}"
        )
        lo = max(0, position - _NEIGHBOURS)
        hi = min(len(frame), position + _NEIGHBOURS + 1)
        lines = [
            _row_line(frame, i, "-->" if i == position else "   ")
            for i in range(lo, hi)
        ]
        blocks.append(head + "\n" + "\n".join(lines))
    return "\n\n".join(blocks)


VERIFY_SYSTEM = """You check one finished answer to a Vietnamese financial question.

You are given the question, the full evidence tables, the pandas query that ran,
the number it produced, and the rows that query actually read — read out of the
dataframes by position, not reported by whoever wrote the query. The row marked
`-->` is the one it used, with its neighbours for contrast; the grids above are
the rest of what was available.

Answer one thing: does that cell answer that question?

Say it is wrong when:
- the row label is a different metric from the one asked for (a neighbouring row
  is the right one),
- the column is a different period from the one asked for,
- the table belongs to a different company or a different report year,
- the question asks for a difference, a sum, a ratio or a growth rate and the
  query returned a single raw cell,
- the question asks for a year, a count or a percentage and the number is plainly
  an amount of money (or the reverse).

Say it is right when the row, the column and the table all match the question,
even if you would have written the query differently. In particular:
- a `TỔNG CỘNG` / `TỔNG` row IS the right row when the question asks for a total,
  a sum or a whole category, even though the lines above it are more specific;
- do not reject a correct answer over its scale or its formatting: unit
  conversion is applied elsewhere and is not yours to judge;
- when the two readings are equally defensible, say it is right. A replacement is
  only worth making when you can point at the row that should have been used.

You are the second opinion, not the first: the query was written by someone
looking at these same tables. Default to accepting it.

When it is wrong, `reason` must name the row POSITION to use instead, taken from
the grid — "row 12 is Lợi nhuận trước thuế, the question asks for sau thuế, use
df1 row 13". Keep it to one sentence. When it is right, leave `reason` empty."""


class Verdict(BaseModel):
    """The check's result."""

    correct: bool = Field(
        default=True,
        description="True if the cell read answers the question asked.",
    )
    reason: str = Field(
        default="",
        description="If not correct: which part is wrong and what to use instead, one sentence.",
    )


def build_prompt(
    codegen_prompt: str,
    query: str,
    answer: float,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    unit_hint: str = "",
) -> str:
    """The generator's own prompt, plus what came out of it.

    The generator's prompt verbatim, not a summary of it. A first version showed
    the read row and two neighbours either side and nothing else, which left the
    check with strictly *less* context than the query it was judging: it could not
    see that a `TỔNG CỘNG` row twenty lines down was the aggregate the question
    asked for, so it argued for whichever line item was next to it and was
    believed. That version replaced 27 of 73 queries and fixed 1 while breaking 3.
    """
    rows = touched_rows(query, frames, names) or "(không xác định được hàng nào đã đọc)"
    asked = f"\nĐơn vị câu hỏi yêu cầu: {unit_hint}" if unit_hint else ""
    return (
        f"{codegen_prompt}{asked}\n\n"
        f"--- Truy vấn đã chạy trên các bảng trên ---\n{query}\n\n"
        f"Kết quả: {answer}\n\n"
        f"Các hàng truy vấn đã đọc (`-->` là hàng nó dùng):\n{rows}"
    )


async def averify(
    codegen_prompt: str,
    query: str,
    answer: float,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    *,
    unit_hint: str = "",
    thinking: bool = False,
) -> tuple[Verdict, str]:
    """One check call. Returns ``(verdict, prompt)``."""
    prompt = build_prompt(codegen_prompt, query, answer, frames, names, unit_hint)
    result = await get_chat_model(thinking=thinking, max_tokens=MAX_TOKENS).with_structured_output(
        Verdict, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=VERIFY_SYSTEM), HumanMessage(content=prompt)])
    if not isinstance(result, Verdict):
        result = Verdict.model_validate(result)
    return result, prompt


REVISE_SYSTEM = CODEGEN_SYSTEM + """

Your previous query ran without error but read the wrong cell. A reviewer that
could see the rows you actually read says what is wrong with it. Write the query
again, addressing exactly that objection and nothing else. The row positions you
need are in the grids above; the objection names them relative to the row you
used."""


async def arevise(prompt: str, query: str, reason: str) -> PandasSolution:
    """One more query, given the reviewer's objection."""
    user = (
        f"{prompt}\n\n"
        f"Truy vấn trước đó:\n{query}\n\n"
        f"Người kiểm tra nói:\n{reason}"
    )
    model = get_chat_model(thinking=False, max_tokens=1024, temperature=REVISE_TEMPERATURE)
    result = await model.with_structured_output(
        PandasSolution, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=REVISE_SYSTEM), HumanMessage(content=user)])
    if not isinstance(result, PandasSolution):
        result = PandasSolution.model_validate(result)
    return result


__all__ = [
    "MAX_TOKENS", "REVISE_SYSTEM", "REVISE_TEMPERATURE", "VERIFY_SYSTEM", "Verdict",
    "arevise", "averify", "build_prompt", "touched_rows",
]
