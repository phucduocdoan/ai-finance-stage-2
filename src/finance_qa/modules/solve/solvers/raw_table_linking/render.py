"""Prompt rendering helpers for raw-table linking planners."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import meta_for, table_metadata
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.lookup import label_column
from finance_qa.modules.solve.facts.table_profile import build_table_profile
from finance_qa.modules.solve.solvers.raw_table_linking import request as _request
from finance_qa.modules.solve.solvers.raw_table_linking import scoring as _scoring
from finance_qa.modules.solve.solvers.raw_table_linking.schema import RawRatioOption
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


def _candidate_table_ids(candidate: RawLinkedCandidate) -> list[str]:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.table_ids
    return [candidate.table_id]


def _candidate_query(
    candidate: RawLinkedCandidate,
    table_to_var: Mapping[str, str],
    transform: str,
) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.query(table_to_var, transform)  # type: ignore[arg-type]
    return candidate.query(table_to_var[candidate.table_id], transform)  # type: ignore[arg-type]


def _candidate_first_cell(candidate: RawLinkedCandidate) -> tuple[str, int, str, str]:
    if isinstance(candidate, RawGroupCandidate):
        first = candidate.cells[0]
        return first.table_id, first.row_position, first.column, first.source_unit
    return candidate.table_id, candidate.row_position, candidate.column, candidate.source_unit


def render_ratio_options(
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
) -> str:
    lines = [
        f"Operation inferred: {request.operation}",
        f"Ratio aggregate: {'average of per-slot ratios' if request.ratio_aggregate == 'avg' else 'single ratio'}",
        "Choose exactly one numerator option and one denominator option for each slot.",
    ]
    by_slot: dict[str, dict[str, list[RawRatioOption]]] = {
        slot.key: {"numerator": [], "denominator": []}
        for slot in request.slots
    }
    for option in options:
        if option.slot_key in by_slot:
            by_slot[option.slot_key][option.side].append(option)
    for slot in request.slots:
        lines.append(f"Slot {slot.key}:")
        for side, title in (("numerator", "Numerator options"), ("denominator", "Denominator options")):
            lines.append(f"  {title}:")
            for option in by_slot[slot.key][side]:
                lines.append(
                    f"  - {option.id} kind={option.source_kind} "
                    f"label={option.label!r} role={option.semantic_role or '?'} "
                    f"tables={option.table_ids} "
                    f"value={_scoring._format_value(option.value)} unit={option.unit} "
                    f"candidate_ids={option.candidate_ids} score={option.score:.2f} "
                    f"context={option.context!r}"
                )
    return "\n".join(lines)


def render_candidates(request: RawLinkRequest, candidates: Sequence[RawLinkedCandidate]) -> str:
    lines = [
        f"Operation inferred: {request.operation}",
        "Required slots in order: " + ", ".join(slot.key for slot in request.slots),
        "Candidates:",
    ]
    for candidate in candidates:
        if isinstance(candidate, RawGroupCandidate):
            flags = []
            if candidate.semantic_role:
                flags.append(f"role={candidate.semantic_role}")
            if candidate.table_context:
                flags.append(f"context={candidate.table_context[:420]}")
            cell_refs = ", ".join(
                f"{cell.table_id}:r{cell.row_position}:{cell.column}"
                for cell in candidate.cells[:8]
            )
            lines.append(
                f"- {candidate.id} kind=group slot={candidate.slot_key} "
                f"tables={candidate.table_ids} label={candidate.label!r} "
                f"op={candidate.group_op} cells=[{cell_refs}] "
                f"value={_scoring._format_value(candidate.value)} unit={candidate.source_unit} "
                f"signals=(score={candidate.score:.2f}) "
                + (" ".join(flags) if flags else "")
            )
            continue
        flags = []
        if candidate.row_path:
            flags.append(f"row_path={' > '.join(candidate.row_path)!r}")
        if candidate.is_total_row:
            flags.append("total_row")
        if candidate.table_context:
            flags.append(f"context={candidate.table_context[:420]}")
        if candidate.source_unit_from:
            flags.append(f"unit_from={candidate.source_unit_from[:120]}")
        signal = (
            f"score={candidate.score:.2f}; row={candidate.row_score:.2f}; "
            f"table={candidate.table_score:.2f}; column={candidate.column_score:.2f}"
        )
        lines.append(
            f"- {candidate.id} slot={candidate.slot_key} table={candidate.table_id} "
            f"row={candidate.row_position} label={candidate.row_label!r} "
            f"column={candidate.column!r} value={_scoring._format_value(candidate.value)} "
            f"unit={candidate.source_unit} signals=({signal}) "
            + (" ".join(flags) if flags else "")
        )
    return "\n".join(lines)


def _dedupe_texts(values: Sequence[object], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _scoring._text(value)
        norm = _norm(text)
        if not text or not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _table_label_snippets(
    request: RawLinkRequest,
    table_id: str,
    df: pd.DataFrame,
    profile_labels: Sequence[str],
    *,
    limit: int,
    meta_lookup=meta_for,
    label_lookup=label_column,
) -> list[str]:
    meta = meta_lookup(table_id)
    labels: list[object] = []
    labels.extend(_scoring._text_list(meta.get("first_col_labels")))
    labels.extend(profile_labels)
    try:
        label_col = label_lookup(df)
        labels.extend(df[label_col].tolist())
    except Exception:  # noqa: BLE001 - labels are advisory evidence for the planner
        pass

    initial = _dedupe_texts(labels, limit=4)
    scoring_tokens, scoring_norm = _scoring._scoring_query_for_table(
        request,
        table_id,
        meta_lookup=meta_lookup,
    )
    ranked = sorted(
        _dedupe_texts(labels, limit=80),
        key=lambda label: _scoring._semantic_score(scoring_tokens, scoring_norm, label),
        reverse=True,
    )
    return _dedupe_texts([*initial, *ranked], limit=limit)


def render_table_contexts(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 24,
    labels_per_table: int = 8,
    max_tables: int = 140,
    frame_loader=load_frame,
    meta_lookup=meta_for,
    metadata_lookup=table_metadata,
    label_lookup=label_column,
    profile_builder=build_table_profile,
) -> str:
    """Render real table snippets so the LLM maps question wording to table wording."""
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    lines = [
        "Real table snippets in scope. Copy phrase wording from these snippets when possible.",
    ]
    for slot in request.slots:
        slot_ranked = list(dict.fromkeys([
            *[
                table_id for table_id in ranked
                if _request._scope_ok(table_id, slot, request.doc_type, meta_lookup=meta_lookup)
            ],
            *_request._scope_table_ids(slot, request.doc_type, metadata_lookup=metadata_lookup),
        ]))[:max_tables]
        scored_tables: list[tuple[float, float, float, str, Mapping[str, Any], list[str], str]] = []
        for table_id in slot_ranked:
            try:
                df = frame_loader(table_id)
            except Exception:  # noqa: BLE001 - one unreadable table should not block evidence
                continue
            if df.empty:
                continue
            meta = meta_lookup(table_id)
            try:
                profile = profile_builder(table_id, df)
                profile_labels = [row.label for row in profile.rows]
            except Exception:  # noqa: BLE001 - profile is advisory
                profile_labels = []
            context = _scoring._table_context(meta, profile_labels)
            scoring_tokens, scoring_norm = _scoring._scoring_query_for_table(
                request,
                table_id,
                meta_lookup=meta_lookup,
            )
            context_score = _scoring._semantic_score(scoring_tokens, scoring_norm, context)
            labels = _table_label_snippets(
                request,
                table_id,
                df,
                profile_labels,
                limit=labels_per_table,
                meta_lookup=meta_lookup,
                label_lookup=label_lookup,
            )
            row_score = max(
                (_scoring._semantic_score(scoring_tokens, scoring_norm, label) for label in labels),
                default=0.0,
            )
            rank_bonus = _scoring._rank_bonus(table_id, ranked)
            score = context_score * 0.62 + row_score * 0.28 + rank_bonus
            if score <= 0:
                continue
            scored_tables.append((score, context_score, row_score, table_id, meta, labels, context))
        scored_tables.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        lines.append(f"Slot {slot.key}:")
        for score, context_score, row_score, table_id, meta, labels, context in scored_tables[:limit_per_slot]:
            title = (
                _scoring._text(meta.get("note_title"))
                or _scoring._text(meta.get("section_title"))
                or _scoring._text(meta.get("statement_type"))
            )
            header = _scoring._text(meta.get("header_flat"))
            page_hint = _scoring._short_context(_scoring._text(meta.get("context_page_text")), 260)
            if page_hint and page_hint in context:
                page_hint = _scoring._short_context(page_hint, 180)
            line = (
                f"- table={table_id}; title={title!r}; header={header!r}; "
                f"signals=({score:.2f}, context={context_score:.2f}, rows={row_score:.2f}); "
                f"labels={labels}"
            )
            if page_hint:
                line += f"; page_hint={page_hint!r}"
            lines.append(line)
    return "\n".join(lines)


__all__ = [
    "_candidate_first_cell",
    "_candidate_query",
    "_candidate_table_ids",
    "_dedupe_texts",
    "_table_label_snippets",
    "render_candidates",
    "render_ratio_options",
    "render_table_contexts",
]
