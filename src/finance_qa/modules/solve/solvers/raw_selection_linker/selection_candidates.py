"""Raw-table selection candidate scoring and component-row-group generation.

Ranking-value/unit helpers over already-linked candidates, plus the
deterministic component-row-sum group builder used when a metric is spread
across several rows that must be summed before ranking.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.units import MONEY_SCALE
from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


_COMPONENT_SUM_REASON = re.compile(
    r"\b(?:tong\s+hop|cong\s+(?:cac|nhieu)|thanh\s+phan|component)\b"
)
_NON_COMPONENT_PHRASE = re.compile(
    r"^(?:so\s+(?:cuoi|dau)\s+(?:nam|ky)|nguyen\s+gia|gia\s+tri\s+con\s+lai|"
    r"gia\s+tri\s+hao\s+mon\s+luy\s+ke|hao\s+mon\s+luy\s+ke)$"
)


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


def _is_flow_candidate(candidate: RawLinkedCandidate) -> bool:
    if isinstance(candidate, RawGroupCandidate):
        return False
    return bool(raw._FLOW_COL.search(raw._norm(candidate.column)))
