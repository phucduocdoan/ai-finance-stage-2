"""Screening questions: filter-then-aggregate over several companies.

`codegen.agenerate` asks the model for ONE pandas expression, and a filter
predicate has nowhere to live in that shape — the model folds every company
straight into the expression (`df1.iloc[3]["2023"] + df2.iloc[5]["2023"] + ...`),
which is why the screening class scores 4/29 on the clean eval while the rest
of a run scores 45/90 (`agents/finance/config.py:screening_solver`). This module
gives the predicate a place to live: the model fills a `ScreeningSolution`
(one value per company, a condition over them, an optional second metric, a
reduction), and `compose` turns that into the single pandas expression the
competition actually re-runs.

The model never writes `pandas_query` here. `compose` does, deterministically,
so validation of the pieces (unique labels, a condition built only from safe
tokens, no assignment/semicolon smuggled into a per-company `expr`) happens
once in Python instead of being hoped for in a free-form string.
"""
from __future__ import annotations

import ast
import json
import re
from typing import Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen.codegen import (
    CODEGEN_SYSTEM,
    MAX_TOKENS,
    FindRows,
    ShowTable,
    _SCOPE_HEADERS_ONLY,
    _SCOPE_WITH_GRIDS,
    _TOOLS_SYSTEM,
    _agenerate_with_tools,
    _run_tool,
    build_prompt,
)
from finance_qa.modules.solve.common.solution import (
    STRUCTURED_METHOD,
    PandasSolution,
    ScreeningSolution,
    SeriesPart,
)

# Same task-list swap as `codegen.CODEGEN_SYSTEM`, everything else verbatim:
# `.iloc` only, column names copied character for character, the "Năm của từng
# cột số tiền" line, read-as-printed with no manual scaling, source_unit as
# declared. Those rules apply per-company here (each `SeriesPart.expr` is one
# cell), so keeping them unchanged is what makes `compose`'s output as
# trustworthy as a plain codegen query.
SCREENING_SYSTEM = """You answer Vietnamese financial questions about a GROUP of companies by
building one value per company, testing a condition over the group, and reducing
the survivors to ONE number.

You are shown the question and the full contents of the evidence tables, each bound
to a variable (df1, df2, ...). The left-most number on each grid row is that row's
integer position.

Your tasks:
1. Find the cell for EVERY company the question asks about, for the metric the
   condition tests (or, if there is no condition, the metric being aggregated).
   Put one `SeriesPart` per company in `selector`: `label` is the company name or
   ticker, `expr` reads exactly ONE cell for that ONE company, e.g.
   `df3.iloc[12]["2023"]`. Every company whose value you can actually read must
   appear in `selector`; never invent a cell for a company whose table is not
   there.
2. State `condition`, a predicate over the per-company series `s` built from
   step 1. Four shapes cover what you will see:
   - no filter at all, just aggregate the whole group: leave `condition` empty.
   - an absolute threshold on each company's own value: `s > 0`.
   - a benchmark relative to the group itself: `s > s.median()`.
   - pick the top or bottom company, then report a DIFFERENT metric there:
     `s == s.max()` paired with `reduce="first"`.
3. If the metric actually reported differs from the one `selector`/`condition`
   test, put one `SeriesPart` per company for that second metric in `answer`,
   using the SAME set of labels as `selector`. Leave `answer` empty when the
   reported metric is `selector`'s own.
4. Set `reduce` to how the surviving companies collapse to one number: mean,
   sum, count, max, min, median, or first (the single selected company, when
   `condition` already narrows the group to one).
5. Report which table, row and column the main cell came from.

Constraints:
- Use only the variables shown (df1, df2, ...). `pd` is available. No imports, no
  file access, no assignments, no print.
- Not every table shown is relevant; several may cover the same company and year.
  Read from the ones whose rows actually carry the metric asked for, and ignore the
  rest.
- Each `expr` must read exactly one cell and evaluate to a single scalar, not a
  Series or DataFrame:
  `df1.iloc[12]["2023"]` is a valid `expr`. `df1["2023"]` or `df1.iloc[12]` is not.
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

_REDUCE_CALLS = {
    "mean": "mean()", "sum": "sum()", "count": "count()", "max": "max()",
    "min": "min()", "median": "median()", "first": "iloc[0]",
}

# `expr` (per-company cell reads): reject the same smuggling surface as a
# multi-statement pandas_query would allow. `=` is checked separately so a
# comparison inside a boolean cell read (rare, but not our business to forbid)
# does not trip the "no assignment" rule.
_CMP_OPS = re.compile(r"==|!=|<=|>=")


def _validate_expr(expr: str, field: str) -> None:
    if not expr.strip():
        raise ValueError(f"{field}.expr rỗng")
    if ";" in expr or "\n" in expr:
        raise ValueError(f"{field}.expr chứa ';' hoặc xuống dòng: {expr!r}")
    if "__" in expr:
        raise ValueError(f"{field}.expr chứa '__': {expr!r}")
    if "=" in _CMP_OPS.sub("", expr):
        raise ValueError(f"{field}.expr chứa '=' không phải phép so sánh: {expr!r}")


# `condition` allowlist: identifiers limited to `s` plus these method names,
# arithmetic/comparison/bitwise operators, and numeric constants. Bitwise `&`/`|`
# rather than `and`/`or`, because the condition ends up indexing a pandas Series
# (`s[cond]`), and Series do not support Python's boolean operators.
_COND_METHODS = {"median", "mean", "max", "min", "sum", "abs", "quantile", "std"}
_COND_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.BitAnd, ast.BitOr)
_COND_CMPOPS = (ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq)
_COND_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _validate_condition(condition: str) -> None:
    if not condition:
        return
    for bad in ("__", "import", "lambda", '"', "'", ";"):
        if bad in condition:
            raise ValueError(f"condition chứa cụm không cho phép ({bad!r}): {condition!r}")
    if "s" not in _COND_NAME.findall(condition):
        raise ValueError(f"condition phải chứa biến s: {condition!r}")
    if "=" in _CMP_OPS.sub("", condition):
        raise ValueError(f"condition chứa '=' không phải phép so sánh: {condition!r}")
    try:
        tree = ast.parse(condition, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"condition không phải biểu thức hợp lệ: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id != "s":
                raise ValueError(f"condition dùng tên không cho phép: {node.id!r}")
        elif isinstance(node, ast.Attribute):
            if node.attr not in _COND_METHODS:
                raise ValueError(f"condition gọi phương thức không cho phép: {node.attr!r}")
        elif isinstance(node, ast.Call):
            for arg in node.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float))):
                    raise ValueError("condition: đối số hàm phải là số")
            if node.keywords:
                raise ValueError("condition không cho phép keyword argument")
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _COND_BINOPS):
                raise ValueError("condition dùng toán tử không cho phép")
        elif isinstance(node, ast.Compare):
            if any(not isinstance(op, _COND_CMPOPS) for op in node.ops):
                raise ValueError("condition dùng toán tử so sánh không cho phép")
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd)):
                raise ValueError("condition dùng toán tử một ngôi không cho phép")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("condition chỉ được chứa số")
        elif isinstance(node, (ast.Expression, ast.Load, ast.operator, ast.cmpop, ast.unaryop)):
            # `ast.walk` also yields the operator markers (`Gt`, `BitAnd`, `USub`, ...)
            # as their own nodes; the parent Compare/BinOp/UnaryOp branches above
            # already checked which operator it is, so a bare marker is not itself
            # a second thing to validate.
            continue
        else:
            raise ValueError(f"condition chứa cấu trúc không cho phép: {type(node).__name__}")


def _validate(solution: ScreeningSolution) -> None:
    if not solution.selector:
        raise ValueError("selector rỗng")
    labels = [part.label for part in solution.selector]
    if len(set(labels)) != len(labels):
        raise ValueError(f"selector có nhãn trùng: {labels}")
    for part in solution.selector:
        _validate_expr(part.expr, "selector")
    if solution.answer:
        answer_labels = [part.label for part in solution.answer]
        if len(set(answer_labels)) != len(answer_labels):
            raise ValueError(f"answer có nhãn trùng: {answer_labels}")
        if set(answer_labels) != set(labels):
            raise ValueError(
                f"answer phải cùng tập nhãn với selector: "
                f"{sorted(answer_labels)} != {sorted(labels)}"
            )
        for part in solution.answer:
            _validate_expr(part.expr, "answer")
    _validate_condition(solution.condition)


def _series_literal(parts: Sequence[SeriesPart]) -> str:
    """`pd.Series({...})`, labels quoted with `json.dumps` so a label carrying a
    quote (or a non-ASCII company name) cannot break out of the dict literal."""
    items = ", ".join(f"{json.dumps(part.label)}: {part.expr}" for part in parts)
    return f"pd.Series({{{items}}})"


# Textual substitution, not `.pipe(lambda s: ...)`: `run_query` evaluates the
# composed string with `eval(code, SAFE_GLOBALS, namespace)`, and `namespace`
# (where df1, df2, ... live) is passed as *locals*, not *globals*. A lambda's
# free variables resolve through LOAD_GLOBAL, which only sees `SAFE_GLOBALS` —
# so `pd.Series({...}).pipe(lambda s: pd.Series({"AAA": df1...})[...])` throws
# `NameError: name 'df1' is not defined` from inside the lambda body, even
# though the identical literal works one level up. Substituting the selector
# literal for every standalone `s` token keeps the whole thing one expression
# with no nested function scope, so every dfN reference stays in the frame
# that actually has them bound.
_S_TOKEN = re.compile(r"\bs\b")


def compose(solution: ScreeningSolution) -> str:
    """Build the ONE pandas expression the competition re-runs from a `ScreeningSolution`.

    Raises `ValueError` naming what was wrong when the plan cannot be composed —
    the caller (`agents.finance.graph.make_generate_pandas`) records that message
    rather than crashing the question.
    """
    _validate(solution)
    base = _series_literal(solution.selector)
    reduce_call = _REDUCE_CALLS[solution.reduce]
    if not solution.condition and not solution.answer:
        return f"{base}.{reduce_call}"
    ans = _series_literal(solution.answer) if solution.answer else base
    # `s[COND]` boolean-indexes the selector series by the condition, so
    # `.index` is exactly the surviving companies' labels — empty `condition`
    # keeps everyone. `_S_TOKEN` then replaces every standalone `s` (the
    # indexing target and every `s` inside COND alike) with the selector
    # literal itself; the answer series is looked up at those same labels.
    indexer = f"s[{solution.condition}]" if solution.condition else "s"
    survivors = _S_TOKEN.sub(f"({base})", indexer)
    return f"({ans})[({survivors}).index].{reduce_call}"


# Same reasoning as `codegen._TOOLS_SYSTEM`/`_bound_variable`/`_run_tool`/
# `_agenerate_with_tools`: reused verbatim rather than copied, so the tool loop
# (find_rows / show_table / submit) behaves identically to the plain codegen path
# and only the submit schema and system prompt differ.
async def agenerate_screening(
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    *,
    thinking: bool = True,
    shortlist: Sequence[str] = (),
    tool_turns: int = 0,
    show_grids: bool = True,
) -> tuple[PandasSolution, str, list[dict]]:
    """Generate a screening solution. Returns ``(solution, prompt, calls)``, with
    `pandas_query` already set to `compose(solution)` — mirrors `codegen.agenerate`'s
    contract exactly, so the caller's handling (repair, unit application, evidence
    bookkeeping) needs no screening-specific branch downstream of this call.

    A `ValueError` from `compose` propagates rather than being swallowed here: the
    caller already has a generic except-and-record around the plain codegen path,
    and this is the same failure shape (a malformed model answer), so it reuses
    that handling instead of a second one.
    """
    grids = show_grids or tool_turns <= 0 or not shortlist
    prompt = build_prompt(question, frames, names, grids=grids)
    if tool_turns <= 0 or not shortlist:
        result = await get_chat_model(thinking=thinking, max_tokens=MAX_TOKENS).with_structured_output(
            ScreeningSolution, method=STRUCTURED_METHOD
        ).ainvoke([SystemMessage(content=SCREENING_SYSTEM), HumanMessage(content=prompt)])
        if not isinstance(result, ScreeningSolution):
            result = ScreeningSolution.model_validate(result)
        result.pandas_query = compose(result)
        return result, prompt, []

    tools = [FindRows, ShowTable, ScreeningSolution]
    system = SCREENING_SYSTEM + _TOOLS_SYSTEM.format(
        turns=tool_turns,
        scope=_SCOPE_WITH_GRIDS if grids else _SCOPE_HEADERS_ONLY,
        submit=ScreeningSolution.__name__,
    )

    def _parse_submit(args: dict) -> ScreeningSolution:
        solution = ScreeningSolution.model_validate(args)
        solution.pandas_query = compose(solution)
        return solution

    # Out of turns with no submit. `ScreeningSolution` cannot express "nothing" any
    # more (every field is required and `selector` needs one entry), so the empty
    # answer is the base `PandasSolution()` codegen returns in the same spot.
    return await _agenerate_with_tools(
        prompt, system, tools, ScreeningSolution.__name__,
        parse_submit=_parse_submit,
        run_tool=lambda call: _run_tool(call, shortlist, frames, names),
        thinking=thinking,
        tool_turns=tool_turns,
        nudge="Hãy gọi find_rows hoặc nộp ScreeningSolution.",
        empty_result=PandasSolution(),
    )


__all__ = ["SCREENING_SYSTEM", "agenerate_screening", "compose"]
