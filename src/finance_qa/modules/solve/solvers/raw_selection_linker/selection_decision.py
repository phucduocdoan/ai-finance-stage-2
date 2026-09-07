"""Raw-table selection decision-making.

Turns candidates (plus optional row groups / semantic constraints) into a
validated `RawSelectionDecision`, either deterministically or via an LLM
planner call, and validates a decision against the request/candidates.
"""
from __future__ import annotations

import re
from typing import Literal, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, Unit
from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_candidates import (
    _is_flow_candidate,
    _is_total_candidate,
    _ranking_value,
    _same_selector_unit_kind,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_request import (
    SelectionAnswerKind,
    SelectionOrder,
)
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
    RawScopeSlot,
)


_SELECTED_SLOT_MARKER = re.compile(
    r"\b(?:tai|trong|vao)\s+(?:cuoi\s+)?nam\s+co\b|"
    r"\bnam\s+do\b|"
    r"\b(?:cong\s+ty|doanh\s+nghiep|ngan\s+hang)\s+co\b"
)


def _can_reuse_selector_as_answer(question: str, answer_kind: SelectionAnswerKind) -> bool:
    if answer_kind in {"selected_year", "selected_value"}:
        return True
    return not _SELECTED_SLOT_MARKER.search(_norm(question))


class RawSelectionSlotDecision(BaseModel):
    """LLM output for one selection slot."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    selector_candidate_id: str
    answer_candidate_id: str = ""
    reason: str = ""


class RawSelectionDecision(BaseModel):
    """LLM output over raw-table selection candidates."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when candidates cannot answer all slots.")
    operation: Literal["select"] = "select"
    rank_op: SelectionOrder
    answer_kind: SelectionAnswerKind
    slots: list[RawSelectionSlotDecision] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("slots", mode="before")
    @classmethod
    def _slots(cls, value):
        return value or []


RAW_SELECTION_SYSTEM = """\
Bạn chọn ô từ raw financial table candidates cho câu hỏi dạng chọn lớn nhất/nhỏ nhất.
Chỉ trả schema RawSelectionDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi candidate là một ô thật trong CSV.
- Mỗi required slot phải có đúng một selector_candidate_id: ô dùng để xếp hạng.
- Nếu đáp án cuối là chính giá trị dùng để xếp hạng, đặt answer_candidate_id bằng selector_candidate_id.
- Nếu câu hỏi hỏi một đại lượng khác tại slot thắng, chọn answer_candidate_id cho đại lượng đáp án đó trong cùng slot.
- Nếu câu hỏi chỉ hỏi "năm nào", đặt answer_kind=selected_year và có thể để answer_candidate_id rỗng.
- Candidate kind=group là tổng nhiều ô component đã được Python dựng sẵn; dùng group khi câu hỏi/search evidence cần tổng hợp nhiều dòng.
- rank_op phải đúng với câu hỏi: lớn/cao/nhiều nhất là max; thấp/nhỏ/ít nhất là min.
- Chỉ chọn candidate nằm trong đúng slot_key.
- Nếu thiếu slot, thiếu selector, thiếu answer, hoặc candidates mơ hồ thì supported=false.
"""


_SLOTS_RETRY_REMINDER = (
    "Nhắc lại: nếu supported=true thì slots KHÔNG được để rỗng — phải có đúng một "
    "RawSelectionSlotDecision cho mỗi slot_key trong request, kể cả khi câu hỏi chỉ cần một slot làm đáp án."
)


async def aplan_raw_selection(
    *,
    question: str,
    request: RawLinkRequest,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    candidates: Sequence[RawLinkedCandidate],
    planner_thinking: bool = False,
) -> RawSelectionDecision:
    user = (
        f"Câu hỏi: {question}\n"
        f"Expected rank_op: {order}\n"
        f"Expected answer_kind: {answer_kind}\n\n"
        f"{raw.render_candidates(request, candidates)}"
    )
    model = get_chat_model(
        thinking=planner_thinking,
        max_tokens=1024,
        temperature=0.0,
    ).with_structured_output(RawSelectionDecision, method=STRUCTURED_METHOD)

    # The model occasionally returns supported=true with an empty `slots` list even though
    # `RawSelectionSlotDecision` is schema-valid without one (Field(default_factory=list) makes
    # it optional). That's silently accepted by Pydantic and only surfaces later as an opaque
    # "slot mismatch" error in validate_decision, so catch it here and retry once with a reminder.
    system = RAW_SELECTION_SYSTEM
    for attempt in range(2):
        try:
            result = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        except Exception as exc:  # noqa: BLE001 - fallback is product behavior
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason=f"raw selection planner unavailable: {type(exc).__name__}: {exc}",
            )
        if result is None:
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason="raw selection planner returned no structured decision",
            )
        decision = result if isinstance(result, RawSelectionDecision) else RawSelectionDecision.model_validate(result)
        if not decision.supported or decision.slots:
            return decision
        system = RAW_SELECTION_SYSTEM + "\n" + _SLOTS_RETRY_REMINDER

    return RawSelectionDecision(
        supported=False,
        operation="select",
        rank_op=order,
        answer_kind=answer_kind,
        reason="raw selection planner returned supported=true with empty slots after retry",
    )


class RawSelectionError(Exception):
    """Unsupported or ambiguous raw-table selection plan."""


def decision_from_row_groups(
    request: RawLinkRequest,
    groups: Sequence[RawGroupCandidate],
    *,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    question: str,
    target_unit: Unit = "unknown",
    min_top_gap: float = 0.04,
) -> RawSelectionDecision:
    """Build a deterministic decision when component-row groups are unambiguous."""
    if not groups:
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="no row groups",
        )
    if not _can_reuse_selector_as_answer(question, answer_kind):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="row groups cannot answer a different selected-slot metric",
        )

    selected: list[RawGroupCandidate] = []
    for slot in request.slots:
        slot_groups = [group for group in groups if group.slot_key == slot.key]
        if not slot_groups:
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason=f"missing row group for {slot.key}",
            )
        slot_groups.sort(key=lambda group: (-group.score, -len(group.cells), group.label))
        if len(slot_groups) > 1 and slot_groups[0].score - slot_groups[1].score < min_top_gap:
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason=f"ambiguous row groups for {slot.key}",
            )
        selected.append(slot_groups[0])

    return RawSelectionDecision(
        supported=True,
        operation="select",
        rank_op=order,
        answer_kind=answer_kind,
        slots=[
            RawSelectionSlotDecision(
                slot_key=slot.key,
                selector_candidate_id=group.id,
                answer_candidate_id="" if answer_kind == "selected_year" else group.id,
                reason="top component-row group selected deterministically",
            )
            for slot, group in zip(request.slots, selected)
        ],
        target_unit="year" if answer_kind == "selected_year" else target_unit,
        confidence=min(group.score for group in selected),
        reason="deterministic component-row groups selected",
    )


def decision_from_flow_top_candidates(
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    *,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    question: str,
    target_unit: Unit = "unknown",
    min_score: float = 0.78,
) -> RawSelectionDecision:
    """Use top flow-column candidates for in-year movement/payable selection."""
    if not raw._FLOW_QUESTION.search(request.query_norm):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="not an in-year flow selection",
        )
    if not _can_reuse_selector_as_answer(question, answer_kind):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="flow top candidates cannot answer a different selected-slot metric",
        )

    selected: list[RawCellCandidate] = []
    for slot in request.slots:
        slot_candidates = sorted(
            [candidate for candidate in candidates if candidate.slot_key == slot.key],
            key=lambda candidate: (
                -candidate.score,
                -candidate.column_score,
                -candidate.row_score,
                -candidate.table_score,
                candidate.table_id,
                candidate.row_position,
            ),
        )
        if not slot_candidates:
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason=f"missing flow candidates for {slot.key}",
            )
        top = slot_candidates[0]
        if top.score < min_score or not _is_flow_candidate(top):
            return RawSelectionDecision(
                supported=False,
                operation="select",
                rank_op=order,
                answer_kind=answer_kind,
                reason=f"top candidate is not a clear flow cell for {slot.key}",
            )
        selected.append(top)

    if not _same_selector_unit_kind(selected):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="flow top candidates have mixed unit kinds",
        )

    return RawSelectionDecision(
        supported=True,
        operation="select",
        rank_op=order,
        answer_kind=answer_kind,
        slots=[
            RawSelectionSlotDecision(
                slot_key=slot.key,
                selector_candidate_id=candidate.id,
                answer_candidate_id="" if answer_kind == "selected_year" else candidate.id,
                reason="top in-year flow candidate selected deterministically",
            )
            for slot, candidate in zip(request.slots, selected)
        ],
        target_unit="year" if answer_kind == "selected_year" else target_unit,
        confidence=min(candidate.score for candidate in selected),
        reason="deterministic top in-year flow candidates selected",
    )


def validate_decision(
    request: RawLinkRequest,
    decision: RawSelectionDecision,
    candidates: Sequence[RawLinkedCandidate],
    *,
    expected_order: SelectionOrder,
    expected_answer_kind: SelectionAnswerKind,
    allow_total_row_selector: bool | None = None,
    min_candidate_score: float = 0.18,
) -> tuple[list[tuple[RawScopeSlot, RawLinkedCandidate, RawLinkedCandidate | None]], RawLinkedCandidate]:
    if not decision.supported:
        raise RawSelectionError(decision.reason or "raw selection planner marked unsupported")
    if decision.operation != "select":
        raise RawSelectionError(f"operation mismatch: {decision.operation} != select")
    if decision.rank_op != expected_order:
        raise RawSelectionError(f"rank_op mismatch: {decision.rank_op} != {expected_order}")
    if decision.answer_kind != expected_answer_kind:
        raise RawSelectionError(
            f"answer_kind mismatch: {decision.answer_kind} != {expected_answer_kind}"
        )

    slot_order = [slot.key for slot in request.slots]
    decision_slots = [slot.slot_key for slot in decision.slots]
    if decision_slots != slot_order:
        raise RawSelectionError(f"slot mismatch: {decision_slots} != {slot_order}")

    by_id = {candidate.id: candidate for candidate in candidates}
    allow_total_rows = request.wants_total if allow_total_row_selector is None else allow_total_row_selector
    selected: list[tuple[RawScopeSlot, RawLinkedCandidate, RawLinkedCandidate | None]] = []
    selectors: list[RawLinkedCandidate] = []
    for slot, slot_decision in zip(request.slots, decision.slots):
        selector = by_id.get(slot_decision.selector_candidate_id)
        if selector is None:
            raise RawSelectionError(f"unknown selector candidate id {slot_decision.selector_candidate_id}")
        if selector.slot_key != slot.key:
            raise RawSelectionError(
                f"selector {selector.id} belongs to {selector.slot_key}, not {slot.key}"
            )
        if _is_total_candidate(selector) and not allow_total_rows:
            raise RawSelectionError("selector total row not allowed for this plan")
        if selector.score < min_candidate_score:
            raise RawSelectionError("selected selector score below threshold")

        answer: RawLinkedCandidate | None = None
        if decision.answer_kind in {"selected_value", "answer_value"}:
            answer_id = slot_decision.answer_candidate_id or slot_decision.selector_candidate_id
            answer = by_id.get(answer_id)
            if answer is None:
                raise RawSelectionError(f"unknown answer candidate id {answer_id}")
            if answer.slot_key != slot.key:
                raise RawSelectionError(
                    f"answer {answer.id} belongs to {answer.slot_key}, not {slot.key}"
                )
            if answer.score < min_candidate_score:
                raise RawSelectionError("selected answer score below threshold")
        selected.append((slot, selector, answer))
        selectors.append(selector)

    if not _same_selector_unit_kind(selectors):
        raise RawSelectionError("selector candidates have mixed unit kinds")

    ranked = [
        (_ranking_value(selector), slot, selector, answer)
        for slot, selector, answer in selected
    ]
    ranked.sort(key=lambda item: item[0], reverse=decision.rank_op == "max")
    winner_value = ranked[0][0]
    if len(ranked) > 1 and ranked[1][0] == winner_value:
        raise RawSelectionError("selection tie is ambiguous")
    return selected, ranked[0][2]


def decision_from_semantic_plan(
    request: RawLinkRequest,
    plan: raw.RawSemanticPlan,
    candidates: Sequence[RawLinkedCandidate],
    *,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    question: str,
) -> RawSelectionDecision:
    """Use raw linker's semantic constraints when selector and answer are one cell."""
    if not _can_reuse_selector_as_answer(question, answer_kind):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            reason="question appears to ask a different answer metric at the selected slot",
        )
    linked = raw.decision_from_semantic_plan(request, plan, candidates)
    if not linked.supported:
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            target_unit=linked.target_unit,
            reason=linked.reason or "semantic constraints did not select candidates",
        )
    slot_keys = [slot.key for slot in request.slots]
    if len(linked.candidate_ids) != len(slot_keys):
        return RawSelectionDecision(
            supported=False,
            operation="select",
            rank_op=order,
            answer_kind=answer_kind,
            target_unit=linked.target_unit,
            reason="semantic decision did not cover every slot",
        )
    return RawSelectionDecision(
        supported=True,
        operation="select",
        rank_op=order,
        answer_kind=answer_kind,
        slots=[
            RawSelectionSlotDecision(
                slot_key=slot_key,
                selector_candidate_id=candidate_id,
                answer_candidate_id="" if answer_kind == "selected_year" else candidate_id,
                reason="semantic constraints matched this slot",
            )
            for slot_key, candidate_id in zip(slot_keys, linked.candidate_ids)
        ],
        target_unit="year" if answer_kind == "selected_year" else linked.target_unit,
        confidence=linked.confidence,
        reason=linked.reason or "semantic constraints matched raw selection candidates",
    )
