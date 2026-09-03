"""Raw-table selection over bounded cell candidates.

This capability covers selection questions whose facts live outside the
structured main-statement catalog: choose the year/company with the largest or
smallest raw-table metric, then return either that year/company's value or the
selected year. The model only chooses candidate ids from a bounded list; Python
validates scope/unit evidence and performs the argmax/argmin.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.common.intent import (
    FILTER_MARKER as _FILTER_MARKER,
    MAX_MARKER as _MAX_MARKER,
    MIN_MARKER as _MIN_MARKER,
    TICKER_ANSWER_MARKER as _TICKER_ANSWER,
    YEAR_ANSWER_MARKER as _YEAR_ANSWER,
    norm as _norm,
)
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution, Unit
from finance_qa.modules.solve.common.units import MONEY_SCALE, unit_from_hint
from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.cell_locator import period_intent, value_transform
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
    RawScopeSlot,
)
from finance_qa.modules.tools.python_exec import run_query


SelectionAxis = Literal["year", "ticker"]
SelectionOrder = Literal["max", "min"]
SelectionAnswerKind = Literal["selected_value", "answer_value", "selected_year"]

_COMPONENT_SUM_REASON = re.compile(
    r"\b(?:tong\s+hop|cong\s+(?:cac|nhieu)|thanh\s+phan|component)\b"
)
_NON_COMPONENT_PHRASE = re.compile(
    r"^(?:so\s+(?:cuoi|dau)\s+(?:nam|ky)|nguyen\s+gia|gia\s+tri\s+con\s+lai|"
    r"gia\s+tri\s+hao\s+mon\s+luy\s+ke|hao\s+mon\s+luy\s+ke)$"
)
_SELECTED_SLOT_MARKER = re.compile(
    r"\b(?:tai|trong|vao)\s+(?:cuoi\s+)?nam\s+co\b|"
    r"\bnam\s+do\b|"
    r"\b(?:cong\s+ty|doanh\s+nghiep|ngan\s+hang)\s+co\b"
)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b")
_VERBAL_RANGE = re.compile(r"\btu\s+nam\s+((?:19|20)\d{2}).{0,30}?\bden\s+nam\s+((?:19|20)\d{2})\b")


def _target_unit(state: Mapping[str, Any], question: str, answer_kind: str) -> Unit:
    unit = unit_from_hint(question) or unit_from_hint(str(state.get("unit_hint") or ""))
    if unit:
        return unit  # type: ignore[return-value]
    if answer_kind == "selected_year":
        return "year"
    return "unknown"


def _selection_order(question: str) -> tuple[SelectionOrder | None, str]:
    norm = _norm(question)
    max_match = _MAX_MARKER.search(norm)
    min_match = _MIN_MARKER.search(norm)
    if not max_match and not min_match:
        return None, "no max/min selection marker"
    if max_match and (not min_match or max_match.start() <= min_match.start()):
        return "max", ""
    return "min", ""


def _axis(tickers: Sequence[str], years: Sequence[int]) -> tuple[SelectionAxis | None, str]:
    if len(tickers) == 1 and len(years) >= 2:
        return "year", ""
    if len(tickers) >= 2 and len(years) == 1:
        return "ticker", ""
    if len(tickers) >= 2 and len(years) >= 2:
        return None, "multi-axis raw selection is not supported"
    return None, "selection needs one varying axis"


def _years_from_question(question: str) -> list[int]:
    match = _RANGE.search(question) or _VERBAL_RANGE.search(_norm(question))
    if match:
        first, last = int(match.group(1)), int(match.group(2))
        if first <= last and last - first <= 10:
            return list(range(first, last + 1))
    return sorted({int(year) for year in _YEAR.findall(question)})


def _answer_kind(question: str, axis: SelectionAxis, target_hint: str | None) -> tuple[SelectionAnswerKind | None, str]:
    norm = _norm(question)
    if axis == "ticker" and _TICKER_ANSWER.search(norm):
        return None, "selected ticker answer is not numeric"
    if axis == "year" and _YEAR_ANSWER.search(norm) and not target_hint:
        return "selected_year", ""
    if target_hint:
        return "answer_value", ""
    return "selected_value", ""


def _can_reuse_selector_as_answer(question: str, answer_kind: SelectionAnswerKind) -> bool:
    if answer_kind in {"selected_year", "selected_value"}:
        return True
    return not _SELECTED_SLOT_MARKER.search(_norm(question))


def build_request(
    state: Mapping[str, Any],
) -> tuple[RawLinkRequest | None, SelectionAxis | None, SelectionOrder | None, SelectionAnswerKind | None, str]:
    """Build a raw-table selection request, or a fail-closed reason."""
    question = str(state.get("question") or "")
    if _FILTER_MARKER.search(_norm(question)):
        return None, None, None, None, "conditional filter is outside raw_selection_linker"

    order, reason = _selection_order(question)
    if not order:
        return None, None, None, None, reason

    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    state_years = sorted({int(y) for y in (state.get("years") or []) if y})
    text_years = _years_from_question(question)
    years = text_years if len(text_years) >= 2 else state_years
    axis, reason = _axis(tickers, years)
    if not axis:
        return None, None, None, None, reason

    target_hint = unit_from_hint(question) or unit_from_hint(str(state.get("unit_hint") or ""))
    answer_kind, reason = _answer_kind(question, axis, target_hint)
    if not answer_kind:
        return None, None, None, None, reason

    slots = (
        [RawScopeSlot(ticker=tickers[0], year=year) for year in years]
        if axis == "year"
        else [RawScopeSlot(ticker=ticker, year=years[0]) for ticker in tickers]
    )
    if len(slots) > 8:
        return None, None, None, None, "too many raw selection slots"

    doc_type = str(state.get("doc_type") or "unknown")
    if doc_type not in {"consolidated", "separate"}:
        doc_type = "unknown"
    request = RawLinkRequest(
        operation="select",
        slots=slots,
        doc_type=doc_type,  # type: ignore[arg-type]
        period=period_intent(question),
        value_transform=value_transform(question, [question]),
        target_unit=_target_unit(state, question, answer_kind),
        query_norm=raw._norm(question),
        query_tokens=raw._tokens(question),
        identity_tokens=raw._scope_identity_tokens(slots, doc_type),
        wants_total=raw._wants_total(question),
    )
    return request, axis, order, answer_kind, ""


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


def _candidate_first_cell(candidate: RawLinkedCandidate) -> tuple[str, int, str]:
    if isinstance(candidate, RawGroupCandidate):
        first = candidate.cells[0]
        return first.table_id, first.row_position, first.column
    return candidate.table_id, candidate.row_position, candidate.column


def _is_total_candidate(candidate: RawLinkedCandidate) -> bool:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.semantic_role == "total"
    return candidate.is_total_row


def _ranking_value(candidate: RawLinkedCandidate) -> float:
    if candidate.source_unit in MONEY_SCALE:
        return candidate.value * MONEY_SCALE[candidate.source_unit]
    return candidate.value


def _same_selector_unit_kind(candidates: Sequence[RawLinkedCandidate]) -> bool:
    return len({raw._unit_kind(candidate.source_unit) for candidate in candidates}) <= 1


def _phrase_match_score(phrase: str, row_label: str) -> float:
    phrase_norm = raw._norm(phrase)
    row_norm = raw._norm(row_label)
    if not phrase_norm or not row_norm:
        return 0.0
    if phrase_norm in row_norm or row_norm in phrase_norm:
        return 1.0
    return raw._semantic_score(
        raw._tokens(phrase), phrase_norm, row_label, partial_query=True
    )


def _component_phrases(search_plan: raw.RawSearchPlan, request: RawLinkRequest | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    identity_tokens = set(request.identity_tokens) if request else set()
    context_norms = {raw._norm(phrase) for phrase in search_plan.context_phrases}
    for phrase in [*search_plan.row_phrases, *search_plan.include_phrases]:
        norm = raw._norm(phrase)
        tokens = set(raw._tokens(phrase))
        if not norm or norm in seen or len(tokens) < 2:
            continue
        if norm in context_norms or _NON_COMPONENT_PHRASE.fullmatch(norm):
            continue
        if request and (raw._YEAR.search(norm) or tokens <= identity_tokens):
            continue
        seen.add(norm)
        out.append(phrase)
    return out


def _requires_component_sum(search_plan: raw.RawSearchPlan, request: RawLinkRequest | None = None) -> bool:
    phrase_sets = [set(raw._tokens(phrase)) for phrase in _component_phrases(search_plan, request)]
    phrase_sets = [tokens for tokens in phrase_sets if len(tokens) >= 2]
    clusters: list[set[str]] = []
    for tokens in phrase_sets:
        for cluster in clusters:
            overlap = len(tokens & cluster) / max(1, len(tokens | cluster))
            if overlap >= 0.5:
                cluster.update(tokens)
                break
        else:
            clusters.append(set(tokens))
    return bool(
        getattr(search_plan, "requires_component_sum", False)
        or _COMPONENT_SUM_REASON.search(_norm(search_plan.reason))
        or (len(phrase_sets) >= 4 and len(clusters) >= 3)
    )


def _exclude_phrase_hits(label: str, table_context: str, exclude_phrases: Sequence[str]) -> int:
    text_norm = raw._norm(f"{label} {table_context}")
    return sum(1 for phrase in exclude_phrases if raw._phrase_matches(text_norm, phrase))


def _row_phrase_group_candidates(
    request: RawLinkRequest,
    search_plan: raw.RawSearchPlan | None,
    candidates: Sequence[raw.RawCellCandidate],
    *,
    start_id: int = 1,
    min_component_score: float = 0.5,
    max_groups_per_slot: int = 6,
) -> tuple[list[RawGroupCandidate], dict[str, Any]]:
    """Build component-row sum candidates from search-plan row phrases."""
    if not search_plan or not search_plan.supported or search_plan.prefer_total_row:
        return [], {"group_candidate_count": 0, "groups_per_slot": {}, "reason": "no component-row search plan"}
    if not _requires_component_sum(search_plan, request):
        return [], {"group_candidate_count": 0, "groups_per_slot": {}, "reason": "search plan does not require component sum"}
    phrases = _component_phrases(search_plan, request)
    if len(phrases) < 2:
        return [], {"group_candidate_count": 0, "groups_per_slot": {}, "reason": "not enough row phrases"}

    groups: list[RawGroupCandidate] = []
    per_slot: dict[str, int] = {}
    for slot in request.slots:
        by_table: dict[str, dict[str, tuple[raw.RawCellCandidate, str, float]]] = {}
        for candidate in candidates:
            if candidate.slot_key != slot.key or candidate.is_total_row or candidate.score < 0.18:
                continue
            # Section ancestors complete a leaf that says nothing on its own, but a
            # match they carry alone is weaker evidence than the row's own label.
            scored = [
                (
                    phrase,
                    max(
                        _phrase_match_score(phrase, candidate.row_label),
                        _phrase_match_score(phrase, candidate.row_path_text) - 0.14,
                    ),
                )
                for phrase in phrases
            ]
            phrase, phrase_score = max(scored, key=lambda item: item[1])
            if phrase_score < min_component_score:
                continue
            table_rows = by_table.setdefault(candidate.table_id, {})
            row_key = raw._norm(candidate.row_path_text)
            current = table_rows.get(row_key)
            if current is None or (candidate.score, candidate.column_score) > (
                current[0].score,
                current[0].column_score,
            ):
                table_rows[row_key] = (candidate, raw._norm(phrase), phrase_score)

        slot_groups: list[RawGroupCandidate] = []
        for table_id, row_map in by_table.items():
            components = [item[0] for item in row_map.values()]
            if len(components) < 2:
                continue
            if len(phrases) >= 4 and len(components) < 3:
                continue
            units = {component.source_unit for component in components}
            if len(units) > 1:
                continue
            matched_phrases = {item[1] for item in row_map.values()}
            coverage = len(matched_phrases) / max(1, len(phrases))
            avg_score = sum(component.score for component in components) / len(components)
            label = " + ".join(component.row_label for component in components)
            exclude_penalty = min(
                0.24,
                0.08 * _exclude_phrase_hits(label, components[0].table_context, search_plan.exclude_phrases),
            )
            score = max(
                0.0,
                min(1.0, avg_score * 0.72 + coverage * 0.24 + min(len(components), 4) * 0.01)
                - exclude_penalty,
            )
            slot_groups.append(
                RawGroupCandidate(
                    id=f"g_tmp_{slot.key}_{len(slot_groups) + 1}",
                    slot_key=slot.key,
                    ticker=slot.ticker,
                    year=slot.year,
                    label=label,
                    cells=[component.ref() for component in components],
                    semantic_role="component_sum",
                    source_unit=components[0].source_unit,
                    score=round(score, 3),
                    table_context=components[0].table_context,
                )
            )
        slot_groups.sort(
            key=lambda group: (
                -group.score,
                -len(group.cells),
                ",".join(group.table_ids),
                group.label,
            )
        )
        kept = slot_groups[:max_groups_per_slot]
        per_slot[slot.key] = len(kept)
        groups.extend(kept)

    compact = [
        group.model_copy(update={"id": f"g{start_id + index}"})
        for index, group in enumerate(groups)
    ]
    return compact, {
        "group_candidate_count": len(compact),
        "groups_per_slot": per_slot,
        "row_phrases": phrases,
    }


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


def _is_flow_candidate(candidate: RawLinkedCandidate) -> bool:
    if isinstance(candidate, RawGroupCandidate):
        return False
    return bool(raw._FLOW_COL.search(raw._norm(candidate.column)))


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


def year_selection_query(
    ranking: Sequence[tuple[float, Any, RawLinkedCandidate, RawLinkedCandidate | None]],
    table_to_var: Mapping[str, str],
    transform: str,
    order: str,
    frames: Mapping[str, pd.DataFrame],
    winning_year: int,
) -> str | None:
    """The year question answered by comparing the years, not by naming the winner.

    This used to emit `(<winning cell>) * 0 + <year>`. Re-executing that does
    reproduce the year, which was the point, but `* 0` annihilates the only cell
    it reads, so what ships is the answer stored as a constant -- which the rules
    score as zero, and which no "is this a constant?" check can see, because the
    expression does reference a frame.

    The comparison is already here: `ranking` holds every slot's selector, the
    same ones `_ranking_value` ordered. Emitting it keeps the year data-dependent,
    since changing a cell changes which tuple wins.

    Returns None whenever the rewrite would not be a year selection -- fewer than
    two years, two candidates on one year, an order that is neither max nor min --
    and whenever the rebuilt query does not run or lands on a different year than
    the ranking did. The caller then keeps the old shape. That check is what makes
    this incapable of moving an answer.
    """
    if order not in {"max", "min"}:
        return None
    by_year: dict[int, RawLinkedCandidate] = {}
    for _, slot, selector, _answer in ranking:
        year = getattr(slot, "year", None)
        if not isinstance(year, int) or year in by_year:
            return None
        by_year[year] = selector
    if len(by_year) < 2 or winning_year not in by_year:
        return None

    # Rendering the *losing* years is new work: the old shape only ever rendered the
    # winner. So this has to be inside the same try as the execution check -- a loser
    # that `_candidate_query` cannot render must cost the caller its old shape, not
    # its whole solve, or the solver would fall through to codegen on questions it
    # used to answer.
    try:
        terms = ", ".join(
            f"(float({raw._candidate_query(by_year[year], table_to_var, transform)}), {year})"
            for year in sorted(by_year)
        )
        query = f"{order}([{terms}])[1]"
        if int(run_query(query, dict(frames))) != winning_year:
            return None
    except Exception:  # noqa: BLE001 - a rewrite that will not build or run is refused
        return None
    return query


def build_solution(
    request: RawLinkRequest,
    decision: RawSelectionDecision,
    candidates: Sequence[RawLinkedCandidate],
    *,
    expected_order: SelectionOrder,
    expected_answer_kind: SelectionAnswerKind,
    allow_total_row_selector: bool | None = None,
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawLinkedCandidate], RawScopeSlot]:
    selected, _ = validate_decision(
        request,
        decision,
        candidates,
        expected_order=expected_order,
        expected_answer_kind=expected_answer_kind,
        allow_total_row_selector=allow_total_row_selector,
    )
    ranking = [
        (_ranking_value(selector), slot, selector, answer)
        for slot, selector, answer in selected
    ]
    ranking.sort(key=lambda item: item[0], reverse=decision.rank_op == "max")
    _, winning_slot, winning_selector, winning_answer = ranking[0]

    chosen: list[RawLinkedCandidate] = []
    query_candidate = winning_answer or winning_selector
    for _, selector, answer in ((slot, selector, answer) for slot, selector, answer in selected):
        chosen.append(selector)
        if answer is not None:
            chosen.append(answer)
    chosen = list({candidate.id: candidate for candidate in chosen}.values())

    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        for table_id in raw._candidate_table_ids(candidate):
            if table_id in table_to_var:
                continue
            var = f"df{len(table_to_var) + 1}"
            table_to_var[table_id] = var
            names[var] = table_id
            frames[var] = raw.load_frame(table_id)

    expr = raw._candidate_query(query_candidate, table_to_var, request.value_transform)
    if decision.answer_kind == "selected_year":
        expr = year_selection_query(
            ranking,
            table_to_var,
            request.value_transform,
            decision.rank_op,
            frames,
            winning_slot.year,
        ) or f"({expr}) * 0 + {winning_slot.year}"

    first_table_id, first_row, first_column = _candidate_first_cell(query_candidate)
    solution = PandasSolution(
        table_variable=table_to_var[first_table_id],
        target_row=str(first_row),
        target_column=first_column,
        source_unit="year" if decision.answer_kind == "selected_year" else query_candidate.source_unit,
        target_unit=(
            "year"
            if decision.answer_kind == "selected_year"
            else decision.target_unit
            if decision.target_unit != "unknown"
            else request.target_unit
        ),
        pandas_query=expr,
    )
    return solution, frames, names, chosen, winning_slot


@dataclass
class _SelectionExpansion:
    """Candidates after search-plan expansion and component-row-group augmentation."""

    search_plan: raw.RawSearchPlan | None
    request: RawLinkRequest
    candidates: Sequence[RawLinkedCandidate]
    row_groups: list[RawGroupCandidate]
    solution_candidates: list[RawLinkedCandidate]
    solution_cand_diag: dict[str, Any]


async def _expand_selection_with_search_plan(
    state: Mapping[str, Any],
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    cand_diag: dict[str, Any],
    *,
    planner_thinking: bool,
) -> _SelectionExpansion:
    search_plan = await raw.aplan_raw_search(
        question=str(state.get("question") or ""),
        request=request,
        table_ids=list(state.get("table_ids") or []),
        shortlist=list(state.get("shortlist") or []),
        planner_thinking=planner_thinking,
    )
    expanded_request = raw.request_with_search_plan(request, search_plan)
    expanded_candidates, expanded_cand_diag = (
        (candidates, cand_diag)
        if expanded_request == request
        else raw.build_candidates(
            expanded_request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            limit_per_slot=32,
        )
    )
    row_groups, row_group_diag = _row_phrase_group_candidates(
        expanded_request,
        search_plan if search_plan and search_plan.supported else None,
        expanded_candidates,
    )
    solution_candidates: list[RawLinkedCandidate] = [*expanded_candidates, *row_groups]
    solution_cand_diag = {
        **expanded_cand_diag,
        "candidate_count": len(solution_candidates),
        "row_group_summary": row_group_diag,
    }
    return _SelectionExpansion(
        search_plan=search_plan,
        request=expanded_request,
        candidates=expanded_candidates,
        row_groups=row_groups,
        solution_candidates=solution_candidates,
        solution_cand_diag=solution_cand_diag,
    )


@dataclass
class _SelectionDecisionResult:
    """Outcome of the row-group / flow / semantic / planner decision cascade."""

    semantic_plan: raw.RawSemanticPlan | None
    semantic_decision: RawSelectionDecision | None
    group_decision: RawSelectionDecision
    flow_decision: RawSelectionDecision
    decision_source: str
    decision: RawSelectionDecision


async def _selection_decision_cascade(
    state: Mapping[str, Any],
    request: RawLinkRequest,
    expansion: _SelectionExpansion,
    *,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    planner_thinking: bool,
) -> _SelectionDecisionResult:
    solution_request = expansion.request
    search_plan = expansion.search_plan
    question = str(state.get("question") or "")

    semantic_plan = (
        raw.semantic_plan_from_search_plan(solution_request, search_plan)
        if search_plan and search_plan.supported
        else None
    )
    semantic_decision = (
        decision_from_semantic_plan(
            solution_request,
            semantic_plan,
            expansion.candidates,
            order=order,
            answer_kind=answer_kind,
            question=question,
        )
        if semantic_plan
        else None
    )
    component_group_required = bool(
        search_plan and search_plan.supported and _requires_component_sum(search_plan, solution_request)
    )
    group_decision = decision_from_row_groups(
        solution_request,
        expansion.row_groups,
        order=order,
        answer_kind=answer_kind,
        question=question,
        target_unit=search_plan.target_unit if search_plan and search_plan.supported else solution_request.target_unit,
    )
    if component_group_required and not group_decision.supported:
        raise RawSelectionError(group_decision.reason or "component row groups are not deterministic")
    flow_decision = decision_from_flow_top_candidates(
        solution_request,
        expansion.candidates,
        order=order,
        answer_kind=answer_kind,
        question=question,
        target_unit=request.target_unit if request.target_unit != "unknown" else solution_request.target_unit,
    )
    decision_source = (
        "row_group_deterministic"
        if group_decision.supported
        else "flow_top_deterministic"
        if flow_decision.supported
        else "semantic_constraints"
        if semantic_decision and semantic_decision.supported
        else "selection_planner"
    )
    decision = (
        group_decision
        if group_decision.supported
        else flow_decision
        if flow_decision.supported
        else semantic_decision
    )
    if decision is None or not decision.supported:
        decision = await aplan_raw_selection(
            question=question,
            request=solution_request,
            order=order,
            answer_kind=answer_kind,
            candidates=expansion.solution_candidates,
            planner_thinking=planner_thinking,
        )
    return _SelectionDecisionResult(
        semantic_plan=semantic_plan,
        semantic_decision=semantic_decision,
        group_decision=group_decision,
        flow_decision=flow_decision,
        decision_source=decision_source,
        decision=decision,
    )


async def aprepare_raw_selection_linker(
    state: Mapping[str, Any],
    *,
    use_planner: bool = True,
    planner_thinking: bool = False,
) -> dict[str, Any]:
    """Prepare a validated raw-table selection answer for graph execution."""
    request, axis, order, answer_kind, reason = build_request(state)
    if request is None or axis is None or order is None or answer_kind is None:
        raise RawSelectionError(reason)

    candidates, cand_diag = raw.build_candidates(
        request,
        table_ids=list(state.get("table_ids") or []),
        shortlist=list(state.get("shortlist") or []),
        limit_per_slot=32,
    )
    if not candidates:
        raise RawSelectionError("no raw selection candidates")
    if cand_diag["missing_slots"]:
        raise RawSelectionError(f"missing candidates for slots {cand_diag['missing_slots']}")
    if not use_planner:
        raise RawSelectionError("raw selection requires planner")

    expansion = await _expand_selection_with_search_plan(
        state, request, candidates, cand_diag, planner_thinking=planner_thinking,
    )
    solution_request = expansion.request
    search_plan = expansion.search_plan

    cascade = await _selection_decision_cascade(
        state, request, expansion, order=order, answer_kind=answer_kind, planner_thinking=planner_thinking,
    )

    allow_total_row_selector = solution_request.wants_total
    if search_plan and search_plan.supported and not search_plan.prefer_total_row:
        allow_total_row_selector = False
    solution, frames, names, chosen, winning_slot = build_solution(
        solution_request,
        cascade.decision,
        expansion.solution_candidates,
        expected_order=order,
        expected_answer_kind=answer_kind,
        allow_total_row_selector=allow_total_row_selector,
    )
    return {
        "solution": solution,
        "frames": frames,
        "names": names,
        "table_ids": list(dict.fromkeys(table_id for candidate in chosen for table_id in raw._candidate_table_ids(candidate))),
        "diag": {
            "done": True,
            "axis": axis,
            "order": order,
            "answer_kind": answer_kind,
            "winning_slot": winning_slot.key,
            "initial_request": request.model_dump(),
            "request": solution_request.model_dump(),
            "initial_candidate_summary": cand_diag,
            "candidate_summary": expansion.solution_cand_diag,
            "search_plan": search_plan.model_dump() if search_plan else None,
            "search_expansion_used": solution_request != request,
            "semantic_plan": cascade.semantic_plan.model_dump() if cascade.semantic_plan else None,
            "semantic_decision": cascade.semantic_decision.model_dump() if cascade.semantic_decision else None,
            "row_group_decision": cascade.group_decision.model_dump(),
            "flow_decision": cascade.flow_decision.model_dump(),
            "decision_source": cascade.decision_source,
            "decision": cascade.decision.model_dump(),
            "chosen": [candidate.model_dump() for candidate in chosen],
        },
    }


def should_attempt_raw_selection_linker(state: Mapping[str, Any]) -> tuple[bool, str]:
    request, axis, order, answer_kind, reason = build_request(state)
    return (request is not None and axis is not None and order is not None and answer_kind is not None), reason


__all__ = [
    "RawSelectionDecision",
    "RawSelectionError",
    "RawSelectionSlotDecision",
    "aplan_raw_selection",
    "aprepare_raw_selection_linker",
    "build_request",
    "build_solution",
    "decision_from_flow_top_candidates",
    "decision_from_row_groups",
    "should_attempt_raw_selection_linker",
    "validate_decision",
]
