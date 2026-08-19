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

from typing import Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import table_context
from finance_qa.modules.solve.common.lookup import render_hits, search_rows
from finance_qa.modules.solve.common.metric_hints import render_metric_hints
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution
from finance_qa.modules.solve.facts.table_profile import table_profile_context

# Completion budget. A well-formed reply is ~110 tokens (measured over 4 questions),
# so this is pure headroom. It is NOT a fix for truncation: see STRUCTURED_METHOD.
MAX_TOKENS = 1024

# ONE expression, and measured: letting the model write a program is much worse.
# `tools.python_exec.run_query` already executes statements that assign `answer`,
# so allowing it costs only the prompt lines below ("a single pandas expression",
# "no assignments") — which is what makes the result worth recording rather than
# re-attempting. On the 94-question gold set it scored 34 against 42/42 for two
# baseline runs whose own churn is 2 questions.
#
# The model does take the affordance: 44 of 94 queries came back as programs, 38
# of them carrying comments. It is what it writes in them that fails. Reproduced
# on q381, the program is a narrative rather than a computation — it opens with
# `cfo_2017 = 1.234567e+13  # Placeholder, need to find actual CFO`, invents a
# value per year, then reasons in comments about which table each real number
# would come from. `enable_thinking` returns an empty reply on this server (see
# `config.codegen_thinking`), and a program is the only free-form channel left, so
# the model spends it thinking instead of computing. Two consequences: fabricated
# numbers reach the executor, and the verbosity overruns MAX_TOKENS: 4 questions
# came back with an empty pandas_query, and 16 ended at answer=0.0 against 5/6 in
# the two baselines.
#
# The damage is not where the mechanism was aimed. The 34-question selection class
# stayed at 3 (baselines 2 and 3); every point lost came from the other 60, which
# fell 40/39 -> 31. Permission to loop is not what that class is missing, and this
# is measured, not inferred. A statement-form query would also need
# `units.scale_expression` to stop wrapping queries in `(...)` — a SyntaxError on a
# program, which `execute.aexecute` reports as `scale_failed` and answers with the
# unconverted raw cell.

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


def build_prompt(
    question: str,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    *,
    grids: bool = True,
    metric: str = "",
    use_metric_hints: bool = False,
    use_table_profiles: bool = False,
) -> str:
    """Question + every evidence table, as a full grid or as a header only."""
    blocks = []
    for var in names:
        if var not in frames:
            continue
        table_id = names[var]
        block = table_context(var, table_id, frames[var], grid=grids)
        if use_table_profiles:
            block += "\n\n" + _safe_table_profile(table_id, frames[var])
        blocks.append(block)
    hints = render_metric_hints(question, metric) if use_metric_hints else ""
    head = f"Câu hỏi: {question}"
    if hints:
        head += f"\n\n{hints}"
    return head + "\n\n" + "\n\n".join(blocks)


def _safe_table_profile(table_id: str, df: pd.DataFrame) -> str:
    """Profile rendering must not turn an answer attempt into a prompt failure."""
    try:
        return table_profile_context(table_id, df)
    except Exception as exc:  # noqa: BLE001 - profile is advisory prompt context
        return f"Bản đồ bảng: không tạo được ({type(exc).__name__}: {exc})"


class FindRows(BaseModel):
    """Tìm hàng theo NHÃN trong mọi bảng của báo cáo liên quan, kể cả bảng chưa hiện ra.

    Dùng khi bảng đang thấy không có dòng câu hỏi cần, hoặc khi phải chắc mình lấy
    dòng TỔNG chứ không phải một dòng thành phần. Bảng nào có hàng khớp sẽ được gán
    thêm một biến dfN dùng được ngay trong biểu thức.
    """

    label: str = Field(description="Tên chỉ tiêu cần tìm, viết như trong câu hỏi. Bỏ dấu cũng khớp.")
    ticker: str = Field(default="", description="Chỉ tìm trong bảng của mã CK này, ví dụ HPG.")
    year: int = Field(default=0, description="Chỉ tìm trong báo cáo của năm này.")
    statement_type: str = Field(
        default="",
        description="balance_sheet | income_statement | cash_flow | equity_change | note",
    )


class ShowTable(BaseModel):
    """Hiện toàn bộ một bảng, khi cần nhìn các dòng xung quanh chứ không riêng một dòng."""

    table_id: str = Field(description="Mã bảng, dạng report_id|vị_trí, lấy từ kết quả find_rows.")


# The tool paragraph lives here rather than in CODEGEN_SYSTEM so a run with
# `codegen_tool_turns = 0` sends byte-identical prompts to the pre-tool baseline
# — that is what makes the A/B attributable to the tools and nothing else.
_TOOLS_SYSTEM = """

Ngoài các bảng ở trên, bạn còn tra được MỌI bảng khác của cùng báo cáo bằng công cụ:
- find_rows(label, ...): tìm hàng theo tên chỉ tiêu. Trả về nhãn đầy đủ, vị trí .iloc,
  giá trị từng cột, và biến dfN đã gán sẵn cho bảng chứa hàng đó.
- show_table(table_id): hiện cả bảng.

{scope}

Chỉ tin những dòng bạn thực sự nhìn thấy; đừng đoán một dòng không có trong lưới hay
trong kết quả find_rows.

Khi đã đủ dữ kiện, gọi PandasSolution để nộp câu trả lời. Được tra tối đa {turns} lượt."""

_SCOPE_WITH_GRIDS = """\
Ba bảng hiện sẵn chỉ là phần đầu của danh sách xếp hạng, không phải toàn bộ báo cáo.
Nếu không thấy đúng chỉ tiêu câu hỏi hỏi — hoặc thấy một dòng gần đúng và ngờ rằng có
dòng TỔNG bao trùm nó — hãy gọi find_rows trước khi trả lời."""

# Header-only prompt: the model is told outright that it has no rows yet, because a
# model shown a table header and no cells will otherwise answer from the header.
_SCOPE_HEADERS_ONLY = """\
Ở trên bạn CHƯA thấy dòng nào — chỉ có mô tả bảng, tên cột và đơn vị. Muốn biết giá trị
thì phải gọi find_rows để lấy đúng những dòng câu hỏi cần. Đó là cách làm mặc định ở đây:
tra trước, viết biểu thức sau. Danh sách bảng tra được rộng hơn nhiều so với vài bảng
được mô tả ở trên."""


def _bound_variable(names: Mapping[str, str], table_id: str) -> str:
    """Variable already bound to `table_id`, or the next free ``dfN``."""
    for var, tid in names.items():
        if tid == table_id:
            return var
    return f"df{len(names) + 1}"


def _run_tool(
    call: dict,
    shortlist: Sequence[str],
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    *,
    metric_lookup: bool = False,
) -> str:
    """Execute one tool call, binding any table it surfaces as a new dfN."""
    args = call.get("args") or {}
    if call["name"] == ShowTable.__name__:
        table_id = str(args.get("table_id") or "")
        if table_id not in shortlist:
            return f"Không có bảng {table_id} trong báo cáo liên quan."
        var = _bound_variable(names, table_id)
        frames[var], names[var] = load_frame(table_id), table_id
        return table_context(var, table_id, frames[var])

    hits = search_rows(
        shortlist,
        str(args.get("label") or ""),
        ticker=str(args.get("ticker") or "") or None,
        year=int(args.get("year") or 0) or None,
        statement_type=str(args.get("statement_type") or "") or None,
        expand_metrics=metric_lookup,
    )
    variables: dict[str, str] = {}
    for hit in hits:
        if hit.table_id not in variables:
            var = _bound_variable(names, hit.table_id)
            frames[var], names[var] = load_frame(hit.table_id), hit.table_id
            variables[hit.table_id] = var
    return render_hits(hits, variables)


async def agenerate(
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    *,
    thinking: bool = True,
    shortlist: Sequence[str] = (),
    tool_turns: int = 0,
    show_grids: bool = True,
    metric: str = "",
    use_metric_hints: bool = False,
    metric_lookup: bool = False,
    use_table_profiles: bool = False,
) -> tuple[PandasSolution, str, list[dict]]:
    """Generate the solution for one question. Returns ``(solution, prompt, calls)``.

    `calls` is the arguments of every lookup the model made, recorded so a run can
    be asked *whether the model used the tool at all* and what it searched for —
    without it, a flat score moves you no closer to knowing why.

    `frames` and `names` are mutated in place: a table a tool surfaces is bound to
    a new ``dfN`` there, so the caller's evidence list and the executor both see
    the variable the query is allowed to reference.

    The prompt is returned so `execute` can reuse it for the repair call — the
    repair must see the same grids, or it will "fix" the query by guessing. When
    tools ran, their output is appended to it for the same reason.

    With `tool_turns = 0` this is one structured call and nothing else, which is
    the pre-tool behaviour exactly.
    """
    # Hiding the grids only makes sense when there is a way to get the cells back.
    grids = show_grids or tool_turns <= 0 or not shortlist
    prompt = build_prompt(
        question, frames, names,
        grids=grids,
        metric=metric,
        use_metric_hints=use_metric_hints,
        use_table_profiles=use_table_profiles,
    )
    if tool_turns <= 0 or not shortlist:
        result = await get_chat_model(thinking=thinking, max_tokens=MAX_TOKENS).with_structured_output(
            PandasSolution, method=STRUCTURED_METHOD
        ).ainvoke([SystemMessage(content=CODEGEN_SYSTEM), HumanMessage(content=prompt)])
        if not isinstance(result, PandasSolution):
            result = PandasSolution.model_validate(result)
        return result, prompt, []

    model = get_chat_model(thinking=thinking, max_tokens=MAX_TOKENS)
    tools = [FindRows, ShowTable, PandasSolution]
    system = CODEGEN_SYSTEM + _TOOLS_SYSTEM.format(
        turns=tool_turns,
        scope=_SCOPE_WITH_GRIDS if grids else _SCOPE_HEADERS_ONLY,
    )
    messages: list = [SystemMessage(content=system), HumanMessage(content=prompt)]
    transcript: list[str] = []
    calls_made: list[dict] = []

    for turn in range(tool_turns + 1):
        # The last turn cannot be another lookup, so the answer is forced rather
        # than requested: an unforced model that keeps searching returns nothing.
        last = turn == tool_turns
        bound = model.bind_tools(
            tools, tool_choice=PandasSolution.__name__ if last else None
        )
        reply = await bound.ainvoke(messages)
        calls = list(getattr(reply, "tool_calls", None) or [])
        submit = next((c for c in calls if c["name"] == PandasSolution.__name__), None)
        if submit is not None:
            solution = PandasSolution.model_validate(submit.get("args") or {})
            return solution, "\n\n".join([prompt, *transcript]), calls_made
        if not calls:
            # No tool call and no answer. One nudge, then the forced turn.
            messages += [reply, HumanMessage(content="Hãy gọi find_rows hoặc nộp PandasSolution.")]
            continue
        messages.append(reply)
        for call in calls:
            try:
                output = _run_tool(
                    call, shortlist, frames, names,
                    metric_lookup=metric_lookup,
                )
            except Exception as exc:  # noqa: BLE001 - a failed lookup is not a failed question
                output = f"Lỗi khi tra cứu: {exc}"
            calls_made.append({"name": call["name"], "args": call.get("args") or {}})
            transcript.append(f"### {call['name']}({call.get('args')})\n{output}")
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))

    return PandasSolution(), "\n\n".join([prompt, *transcript]), calls_made


__all__ = [
    "CODEGEN_SYSTEM", "MAX_TOKENS", "FindRows", "ShowTable", "agenerate", "build_prompt",
]
