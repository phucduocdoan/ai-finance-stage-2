"""Structured LLM planner calls for raw-table linking."""
from __future__ import annotations

from typing import Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD
from finance_qa.modules.solve.solvers.raw_table_linking.request import _tokens
from finance_qa.modules.solve.solvers.raw_table_linking.render import (
    render_candidates,
    render_ratio_options,
    render_table_contexts,
)
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioDecision,
    RawRatioOption,
    RawRatioOptionDecision,
    RawSearchPlan,
    RawSemanticPlan,
    RawSlotSemanticConstraint,
)
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    RawCellCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


RAW_LINKER_SYSTEM = """\
Bạn chọn ô từ raw financial table candidates để executor Python tính toán.
Chỉ trả schema RawLinkerDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi candidate là một ô thật trong CSV.
- Chọn đúng một candidate cho mỗi required slot.
- Với operation=diff, thứ tự candidate_ids phải theo Required slots: slot 1 trừ slot 2.
- Với avg/sum, chọn đủ các slot được yêu cầu.
- Ưu tiên dòng tổng/Cộng khi câu hỏi hỏi tổng số dư/tổng giá trị.
- Nếu chọn được đủ candidate_ids tốt nhất cho các required slots thì supported=true.
- Dùng unsupported chỉ khi thiếu slot, thiếu ô đúng, đơn vị không cùng loại, hoặc candidates mơ hồ.
"""


RAW_RATIO_LINKER_SYSTEM = """\
Bạn chọn các ô numerator/denominator từ raw financial table candidates.
Chỉ trả schema RawRatioDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi candidate là một ô thật trong CSV.
- Mỗi slot_key phải có numerator_candidate_ids và denominator_candidate_ids.
- Một phía có thể gồm nhiều candidate_ids nếu câu hỏi cần cộng nhiều component.
- Nếu có sẵn dòng/cột tổng đúng semantic thì ưu tiên dùng tổng thay vì cộng component.
- Không bao giờ chọn đồng thời một dòng/cột tổng và các component đã tạo ra tổng đó trong cùng một phía.
- Không chọn dòng phát sinh trong năm/trả trong năm nếu câu hỏi hỏi số dư cuối năm.
- Với câu hỏi phần trăm, vẫn chọn raw money cells; executor sẽ nhân 100 sau khi chia.
- Nếu candidates không đủ để biểu diễn đầy đủ numerator/denominator cho mọi slot thì supported=false.
"""


RAW_RATIO_OPTION_SYSTEM = """\
Bạn chọn option numerator/denominator cho ratio tài chính.
Chỉ trả schema RawRatioOptionDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi slot_key phải chọn đúng một numerator_option_id và một denominator_option_id.
- Chỉ chọn option nằm trong đúng slot và đúng side.
- Numerator là phần được hỏi: ví dụ nợ ngắn hạn, dưới 1 năm, tài sản vô hình.
- Denominator là tổng/nền mẫu: ví dụ tổng dư nợ, tổng tài sản, tổng tài sản cố định.
- Nếu trong cùng slot có kind=cell với row label trực tiếp đúng phần được hỏi, ưu tiên nó hơn kind=group suy diễn từ nhiều cột.
- Nếu thiếu option đúng cho bất kỳ slot nào thì supported=false.
"""


RAW_SEMANTIC_SYSTEM = """\
Bạn tạo semantic constraints để chọn ô trong raw financial table candidates.
Chỉ trả schema RawSemanticPlan. Không chọn candidate_id, không viết pandas, không tự tính số.

Mỗi required slot cần một RawSlotSemanticConstraint cùng slot_key.
row_phrases là cụm phân biệt phải nằm ở row label của ô đúng.
context_phrases là cụm phân biệt table/note, như tiêu đề thuyết minh.
include_phrases chỉ dùng khi cụm có thể nằm ở row, column hoặc context.
Có thể dùng cụm tương đương xuất hiện trong candidates, không nhất thiết y
nguyên câu hỏi. Không đưa tên công ty, năm, đơn vị, hoặc từ tính toán vào các
phrase fields.
exclude_phrases dùng cho các khái niệm gần nhưng sai nếu candidates có chúng.
Nếu candidates không đủ để phân biệt ô đúng, supported=false.
"""


RAW_SEARCH_SYSTEM = """\
Bạn chuyển câu hỏi tài chính thành cụm tìm kiếm để tìm row trong raw tables.
Chỉ trả schema RawSearchPlan. Không chọn candidate_id, không viết pandas,
không tự tính số.

row_phrases: cụm có khả năng xuất hiện ở row label hoặc fragment phân biệt
trong row label của ô đúng. Ưu tiên copy đúng wording từ real table snippets.
context_phrases: cụm nhận diện note/table nếu cần.
include_phrases: cụm có thể nằm ở row, column hoặc context.
exclude_phrases: cụm gần nghĩa nhưng sai cần loại.
requires_component_sum=true chỉ khi đáp án phải cộng nhiều dòng/cell component
trong cùng slot; false nếu row_phrases chỉ là các cách gọi/synonym của cùng một
metric.
Các snippets chỉ hiển thị labels/context, không hiển thị numeric values; không
được unsupported chỉ vì chưa thấy giá trị số.
Phrase fields sẽ áp cho mọi required slot, nên không đưa tên công ty, ticker,
năm, đơn vị, mã form, hoặc từ tính toán vào phrase fields.
Nếu snippets không cho đủ bằng chứng semantic về row/context, supported=false.
"""


async def aplan_raw_table_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
    chat_model_factory=get_chat_model,
    structured_method=STRUCTURED_METHOD,
    render_candidates_func=render_candidates,
) -> RawLinkerDecision:
    user = f"Câu hỏi: {question}\n\n{render_candidates_func(request, candidates)}"
    try:
        result = await chat_model_factory(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawLinkerDecision,
            method=structured_method,
        ).ainvoke([SystemMessage(content=RAW_LINKER_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason=f"planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason="planner returned no structured decision",
        )
    return result if isinstance(result, RawLinkerDecision) else RawLinkerDecision.model_validate(result)


async def aplan_raw_ratio_options(
    *,
    question: str,
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
    planner_thinking: bool = False,
    chat_model_factory=get_chat_model,
    structured_method=STRUCTURED_METHOD,
    render_ratio_options_func=render_ratio_options,
) -> RawRatioOptionDecision:
    user = f"Câu hỏi: {question}\n\n{render_ratio_options_func(request, options)}"
    try:
        result = await chat_model_factory(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawRatioOptionDecision,
            method=structured_method,
        ).ainvoke([SystemMessage(content=RAW_RATIO_OPTION_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason=f"ratio option planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason="ratio option planner returned no structured decision",
        )
    return result if isinstance(result, RawRatioOptionDecision) else RawRatioOptionDecision.model_validate(result)


async def aplan_raw_ratio_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    planner_thinking: bool = False,
    chat_model_factory=get_chat_model,
    structured_method=STRUCTURED_METHOD,
    render_candidates_func=render_candidates,
) -> RawRatioDecision:
    aggregate = "average of per-slot ratios" if request.ratio_aggregate == "avg" else "single ratio per slot"
    user = (
        f"Câu hỏi: {question}\n"
        f"Ratio aggregate: {aggregate}\n\n"
        f"{render_candidates_func(request, candidates)}"
    )
    try:
        result = await chat_model_factory(
            thinking=planner_thinking,
            max_tokens=1024,
            temperature=0.0,
        ).with_structured_output(
            RawRatioDecision,
            method=structured_method,
        ).ainvoke([SystemMessage(content=RAW_RATIO_LINKER_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawRatioDecision(
            supported=False,
            operation="ratio",
            reason=f"ratio planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawRatioDecision(supported=False, operation="ratio", reason="ratio planner returned no structured decision")
    return result if isinstance(result, RawRatioDecision) else RawRatioDecision.model_validate(result)


async def aplan_raw_search(
    *,
    question: str,
    request: RawLinkRequest,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    planner_thinking: bool = False,
    chat_model_factory=get_chat_model,
    structured_method=STRUCTURED_METHOD,
    render_table_contexts_func=render_table_contexts,
) -> RawSearchPlan:
    slots = ", ".join(slot.key for slot in request.slots)
    table_context_limit = 24 if len(request.slots) <= 2 else 12
    table_contexts = render_table_contexts_func(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=table_context_limit,
    )
    user = (
        f"Câu hỏi: {question}\n"
        f"Operation: {request.operation}\n"
        f"Required slots: {slots}\n"
        f"Question tokens without identity: "
        f"{' '.join(token for token in request.query_tokens if token not in set(request.identity_tokens))}\n\n"
        f"{table_contexts}"
    )
    try:
        result = await chat_model_factory(
            thinking=planner_thinking,
            max_tokens=512,
            temperature=0.0,
        ).with_structured_output(
            RawSearchPlan,
            method=structured_method,
        ).ainvoke([SystemMessage(content=RAW_SEARCH_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawSearchPlan(
            supported=False,
            reason=f"search planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawSearchPlan(supported=False, reason="search planner returned no structured plan")
    return result if isinstance(result, RawSearchPlan) else RawSearchPlan.model_validate(result)


def request_with_search_plan(
    request: RawLinkRequest,
    plan: RawSearchPlan | None,
    *,
    normalizer=_norm,
    tokenizer=_tokens,
) -> RawLinkRequest:
    if plan is None or not plan.supported:
        return request
    expansion = " ".join([
        *plan.row_phrases,
        *plan.context_phrases,
        *plan.include_phrases,
    ])
    if not expansion.strip():
        return request
    expanded_text = f"{request.query_norm} {normalizer(expansion)}"
    return request.model_copy(update={
        "query_norm": normalizer(expanded_text),
        "query_tokens": tokenizer(expanded_text),
        "target_unit": plan.target_unit if plan.target_unit != "unknown" else request.target_unit,
        "wants_total": request.wants_total or plan.prefer_total_row,
    })


def semantic_plan_from_search_plan(request: RawLinkRequest, plan: RawSearchPlan) -> RawSemanticPlan:
    if not plan.supported:
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            target_unit=request.target_unit,
            reason=plan.reason or "search planner marked unsupported",
        )
    return RawSemanticPlan(
        supported=True,
        operation=request.operation,
        target_unit=plan.target_unit if plan.target_unit != "unknown" else request.target_unit,
        confidence=plan.confidence,
        reason=plan.reason,
        slots=[
            RawSlotSemanticConstraint(
                slot_key=slot.key,
                row_phrases=plan.row_phrases,
                context_phrases=plan.context_phrases,
                include_phrases=plan.include_phrases,
                exclude_phrases=plan.exclude_phrases,
                prefer_total_row=plan.prefer_total_row,
                requires_component_sum=plan.requires_component_sum,
            )
            for slot in request.slots
        ],
    )


async def aplan_raw_semantics(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
    chat_model_factory=get_chat_model,
    structured_method=STRUCTURED_METHOD,
    render_candidates_func=render_candidates,
) -> RawSemanticPlan:
    user = f"Câu hỏi: {question}\n\n{render_candidates_func(request, candidates)}"
    try:
        result = await chat_model_factory(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawSemanticPlan,
            method=structured_method,
        ).ainvoke([SystemMessage(content=RAW_SEMANTIC_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            reason=f"semantic planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            reason="semantic planner returned no structured plan",
        )
    return result if isinstance(result, RawSemanticPlan) else RawSemanticPlan.model_validate(result)


__all__ = [
    "RAW_LINKER_SYSTEM",
    "RAW_RATIO_LINKER_SYSTEM",
    "RAW_RATIO_OPTION_SYSTEM",
    "RAW_SEARCH_SYSTEM",
    "RAW_SEMANTIC_SYSTEM",
    "aplan_raw_ratio_linker",
    "aplan_raw_ratio_options",
    "aplan_raw_search",
    "aplan_raw_semantics",
    "aplan_raw_table_linker",
    "request_with_search_plan",
    "semantic_plan_from_search_plan",
]
