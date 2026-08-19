"""Plan a selection question as a fan-out over its axis, and pick the winner.

Why this exists, and it is measured. A selection question ("in the year KBC had
the highest D/E over 2016-2020, what was its interest coverage") needs one
expression to read ~4 rows across 5 tables, compose 5 ratios, argmax them, then
read a *second* quantity at the winner — written blind, in one call, with no
intermediate value ever shown back. Seven configurations have now been scored on
the 94-question gold set and that block has never risen above 3 of 34, while the
other 60 sit at 39-40. Nothing tried so far touched the reason.

It is not retrieval. Measured on `gold94_base1.jsonl`: 28 of the 31 questions
whose axis is legible have *every* element of that axis present in the submitted
`table_ids`. It is the prompt window — only 17 of 31 keep them after the
`[:codegen_max_tables_multi_year]` slice, and even the 17 that survive hand the
model a job one expression cannot hold. Fanning out gives each element its own
window and turns one impossible question into N instances of the shape the
system already answers at ~40/60, plus arithmetic that Python does.

The division of labour is the whole design, and it comes from the failure that
killed the program-of-thought run: given free-form space this model writes
narrative and invents numbers (`cfo_2017 = 1.234567e+13  # Placeholder`). So the
model writes only *text* — three sub-question templates and a handful of enum
fields — and never a number. Python enumerates the axis (from `expand_years`,
which cannot drop a year the way a decomposer can), applies the predicate,
takes the median, runs `max()`, and adds the offset.

This module is the half of that with no I/O and no LLM in it apart from
`aplan`: `axis_of` and `pick` are pure, so the selection arithmetic is testable
without a server. The fan-out itself lives in the `solve_selection` node.
"""
from __future__ import annotations

import ast
import re
from statistics import median
from typing import Literal, Mapping, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD

# The surface markers that name a selection. A lower bound and evidence rather
# than a classifier (see `CONTEXT.md`), which is exactly why they are used only
# as a *trigger*: a question they miss keeps the current path unchanged, and the
# blast radius stays at the 31 of 94 that match.
MARKERS = (
    "cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất",
    "nhiều nhất", "ít nhất", "trung vị", "vượt",
)

_YEAR_IN_ID = re.compile(r"_(20\d\d)_")
_YEAR_IN_TEXT = re.compile(r"\b(20[01]\d|202[0-4])\b")
_RANGE = re.compile(r"(20\d\d)\s*[-–]\s*(20\d\d)")


class SelectionPlan(BaseModel):
    """The five-stage pipeline, as fields a model fills with text.

    Every question in the gold block reduces to: score each element of an axis,
    optionally drop elements failing a predicate, take the best one, optionally
    step one period forward, and read the answer there. Only the templates are
    generated; each remaining field is an enum or a literal Python compares.
    """

    rank_metric: str = Field(
        description="Câu hỏi tính chỉ tiêu dùng để XẾP HẠNG, cho MỘT phần tử. "
                    "Dùng chỗ trống {ticker} và {year}. "
                    "Ví dụ: 'Tỷ số nợ phải trả trên vốn chủ sở hữu của {ticker} năm {year} là bao nhiêu lần?'"
    )
    rank_op: Literal["max", "min"] = Field(
        default="max", description="Chọn phần tử có chỉ tiêu xếp hạng lớn nhất (max) hay nhỏ nhất (min)."
    )
    answer_metric: str = Field(
        description="Câu hỏi tính ĐÁP ÁN cuối cùng, tại phần tử đã chọn. Cùng dạng chỗ trống. "
                    "Nếu đáp án chính là chỉ tiêu xếp hạng thì chép lại y hệt rank_metric."
    )
    filter_metric: str = Field(
        default="",
        description="Chỉ điền khi câu hỏi loại bớt phần tử trước khi xếp hạng "
                    "('chỉ tính các năm có lợi nhuận sau thuế dương'). Để trống nếu không có.",
    )
    filter_op: Literal["", ">", "<", ">=", "<="] = Field(
        default="", description="Toán tử so sánh của điều kiện lọc."
    )
    filter_threshold: str = Field(
        default="",
        description="Ngưỡng lọc: một con số ('0', '10'), hoặc đúng chữ 'median' khi "
                    "ngưỡng là trung vị của chính chuỗi giá trị đó.",
    )
    offset: int = Field(
        default=0,
        description="1 khi câu hỏi đọc đáp án ở kỳ NGAY SAU phần tử được chọn "
                    "('vào năm sau năm có...', 'cuối năm kế tiếp'). Ngược lại 0.",
    )


PLAN_SYSTEM = """Bạn lập kế hoạch cho một câu hỏi tài chính dạng CHỌN LỌC: câu hỏi
so sánh một chỉ tiêu qua nhiều năm hoặc nhiều công ty, chọn ra một mốc, rồi hỏi
một đại lượng tại mốc đó.

Kế hoạch luôn chạy đúng năm chặng:
  1. tính `rank_metric` cho từng phần tử của trục
  2. nếu có `filter_metric`, loại các phần tử không thỏa điều kiện
  3. chọn phần tử theo `rank_op`
  4. cộng `offset` kỳ
  5. tính `answer_metric` tại phần tử đó

Bạn CHỈ viết chữ. Bạn không tính, không đoán số, không viết công thức pandas.
Mỗi template phải là một câu hỏi HOÀN CHỈNH, tự đứng được, hỏi về ĐÚNG MỘT phần
tử, và phải nêu rõ đơn vị nếu câu hỏi gốc có nêu. Chỗ trống chỉ dùng {ticker} và
{year}, viết đúng dạng đó.

Quan trọng nhất: một tỷ số phái sinh KHÔNG phải là một dòng trong báo cáo tài
chính. Không có bảng nào in ra dòng "Tỷ số D/E" hay "ROE". Nên template phải
VIẾT RÕ CÔNG THỨC bằng đúng tên các dòng như báo cáo in ra, thay vì gọi tên tỷ
số:

  SAI  : "Tỷ số D/E của {ticker} năm {year} là bao nhiêu lần?"
  ĐÚNG : "Lấy Nợ phải trả cuối năm {year} của {ticker} chia cho Vốn chủ sở hữu
          cuối năm {year}, bằng bao nhiêu lần?"

  SAI  : "ROE của {ticker} năm {year} là bao nhiêu phần trăm?"
  ĐÚNG : "Lấy Lợi nhuận sau thuế thu nhập doanh nghiệp năm {year} của {ticker}
          chia cho Vốn chủ sở hữu cuối năm {year}, nhân 100, bằng bao nhiêu
          phần trăm?"

Nếu chỉ tiêu vốn đã là một dòng có sẵn (doanh thu thuần, hàng tồn kho, chi phí
lãi vay) thì cứ hỏi thẳng dòng đó.

Nếu câu hỏi không khớp năm chặng trên, cứ điền phần khớp được — phần còn lại để
mặc định."""


def axis_of(
    question: str, years: Sequence[int], tickers: Sequence[str]
) -> tuple[str, list] | None:
    """The axis this question fans out over, or None to keep the current path.

    Years win over tickers when both are plural: "in 2016-2020, which of A and B"
    does not occur in the block, while a period question naming one company is
    most of it. `years` arrives already expanded by `expand_years`, so a range
    written as two endpoints is a full list here.

    Falls back to reading the years out of the question text when `understand`
    returned fewer than two, because the trigger must not depend on a field no
    downstream code has ever checked — `metric` sat unused in the state for the
    same reason and is still unmeasured.
    """
    if not any(marker in question.lower() for marker in MARKERS):
        return None
    resolved = sorted({int(y) for y in years if y})
    if len(resolved) < 2 or not _covers_span(question, resolved):
        resolved = sorted(years_in_text(question))
    if len(resolved) >= 2 and _covers_span(question, resolved):
        return "year", resolved
    seen = sorted({str(t).upper() for t in tickers if t})
    if len(seen) >= 2:
        return "ticker", seen
    return None


def _covers_span(question: str, years: Sequence[int]) -> bool:
    """Do `years` enumerate the period the question wrote as two endpoints?

    A period is only an axis once every year in it is listed. `expand_years`
    gives up past a 10-year span and `understand` can return an endpoint pair on
    its own, and either way fanning out over what survives would rank two years,
    pick one, and answer from it without ever recording that the years between
    were never looked at. No range in the text means nothing to cover.
    """
    span = _RANGE.search(question)
    if not span:
        return True
    first, last = int(span.group(1)), int(span.group(2))
    return first >= last or set(range(first, last + 1)) <= set(years)


def years_in_text(question: str) -> set[int]:
    """Years the question names, with a written range expanded."""
    span = _RANGE.search(question)
    if span:
        first, last = int(span.group(1)), int(span.group(2))
        if 0 < last - first <= 10:
            return set(range(first, last + 1))
    return {int(y) for y in _YEAR_IN_TEXT.findall(question)}


def year_of(table_id: str) -> int | None:
    match = _YEAR_IN_ID.search(table_id.rsplit("|", 1)[0])
    return int(match.group(1)) if match else None


def ticker_of(table_id: str) -> str:
    return table_id.split("_", 1)[0].upper()


def tables_for(table_ids: Sequence[str], axis: str, element) -> list[str]:
    """The submitted tables belonging to one element of the axis.

    Order is retrieval's own ranking, untouched: the point of the fan-out is that
    each element gets the *head* of its own ranking instead of competing with the
    other four for three slots.
    """
    key = year_of if axis == "year" else ticker_of
    want = int(element) if axis == "year" else str(element).upper()
    return [tid for tid in table_ids if key(tid) == want]


def sub_question(template: str, axis: str, element, other: str = "") -> str:
    """Fill one template. Returns "" when the model wrote an unusable one.

    Both placeholders are filled, not just the axis one: on a year axis the
    company is a constant the question already named, and blanking it produced
    sub-questions reading "hệ số khả năng thanh toán lãi vay của  năm 2018" —
    which asks the model to pick a company out of whatever tables it was handed.
    """
    values = {"ticker": str(other), "year": str(other)}
    values["year" if axis == "year" else "ticker"] = str(element)
    try:
        text = template.format(**values)
    except (KeyError, IndexError, ValueError):
        return ""
    return text.strip()


def degenerate_query(query: str) -> bool:
    """Is this a query that divides an expression by itself?

    The shape a sub-question takes when the model cannot find its second row: on
    q363 four of five years came back `df1.iloc[19]["Số cuối năm"] /
    df1.iloc[19]["Số cuối năm"]`, and 1.0 then beat every genuine D/E in the
    series. It is not a value that failed to arrive — `aexecute` reports success —
    so it has to be recognised for what it is before `max()` sees it.
    """
    try:
        tree = ast.parse(query.strip(), mode="eval").body
    except SyntaxError:
        return False
    return (
        isinstance(tree, ast.BinOp)
        and isinstance(tree.op, ast.Div)
        and ast.dump(tree.left) == ast.dump(tree.right)
    )


_COMPARE = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def pick(
    plan: SelectionPlan,
    axis: str,
    ranks: Mapping[object, float | None],
    filters: Mapping[object, float | None] | None = None,
) -> tuple[object | None, dict]:
    """Apply stages 2-4. Returns ``(winner, trace)``; winner is None to fall back.

    Elements whose ranking metric did not produce a number are dropped rather
    than scored as 0.0 — on q381 ("the year HPG had the *lowest* CFO/LNST") a
    spurious zero wins `min` outright and nothing downstream can tell. Two
    elements must survive that drop, because a choice between one candidate is
    not the question that was asked; a *filter* narrowing the field to one is,
    and is allowed.

    The trace is returned rather than logged because the submitted query carries
    only stage 5: without the intermediates in `diag`, a flat score cannot say
    whether the plan, the ranking or the final read was the thing that missed.
    """
    live = [key for key, value in ranks.items() if value is not None]
    trace: dict = {
        "ranks": {str(k): ranks[k] for k in ranks},
        "dropped": [str(k) for k in ranks if ranks[k] is None],
    }
    if len(live) < 2:
        trace["reason"] = "dưới 2 phần tử có giá trị xếp hạng"
        return None, trace

    if plan.filter_metric and plan.filter_op in _COMPARE:
        scored = {k: v for k, v in (filters or {}).items() if k in live and v is not None}
        trace["filters"] = {str(k): v for k, v in scored.items()}
        if not scored:
            trace["reason"] = "điều kiện lọc không tính được cho phần tử nào"
            return None, trace
        if plan.filter_threshold.strip().lower() == "median":
            threshold = median(scored.values())
        else:
            try:
                threshold = float(plan.filter_threshold.replace(",", "."))
            except ValueError:
                trace["reason"] = f"ngưỡng lọc không đọc được: {plan.filter_threshold!r}"
                return None, trace
        trace["threshold"] = threshold
        compare = _COMPARE[plan.filter_op]
        live = [k for k in live if k in scored and compare(scored[k], threshold)]
        trace["survivors"] = [str(k) for k in live]
        if not live:
            trace["reason"] = "không phần tử nào qua điều kiện lọc"
            return None, trace

    chooser = max if plan.rank_op == "max" else min
    winner = chooser(live, key=lambda k: ranks[k])
    trace["winner"] = str(winner)

    if plan.offset and axis == "year":
        winner = int(winner) + plan.offset
        trace["winner_after_offset"] = str(winner)
    return winner, trace


async def aplan(question: str, axis: str, elements: Sequence) -> SelectionPlan:
    """One structured call. The model fills the fields; it computes nothing."""
    listed = ", ".join(str(e) for e in elements)
    user = (
        f"Câu hỏi: {question}\n\n"
        f"Trục fan-out: {'năm' if axis == 'year' else 'mã chứng khoán'}\n"
        f"Các phần tử: {listed}\n\n"
        "Viết kế hoạch cho câu hỏi này."
    )
    model = get_chat_model(thinking=False, max_tokens=1024, temperature=0.0)
    result = await model.with_structured_output(
        SelectionPlan, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=PLAN_SYSTEM), HumanMessage(content=user)])
    if not isinstance(result, SelectionPlan):
        result = SelectionPlan.model_validate(result)
    return result


__all__ = [
    "MARKERS", "PLAN_SYSTEM", "SelectionPlan", "aplan", "axis_of",
    "degenerate_query", "pick",
    "sub_question", "tables_for", "ticker_of", "year_of", "years_in_text",
]
