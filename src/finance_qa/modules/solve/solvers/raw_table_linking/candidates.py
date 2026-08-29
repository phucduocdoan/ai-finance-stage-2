"""Candidate construction for raw-table linking."""
from __future__ import annotations

import re
from typing import Any, Sequence

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import meta_for, page_text, table_metadata
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.lookup import label_column
from finance_qa.modules.solve.common.units import detect_unit
from finance_qa.modules.solve.facts.table_profile import build_table_profile
from finance_qa.modules.solve.solvers.raw_table_linking import request as _request
from finance_qa.modules.solve.solvers.raw_table_linking import scoring as _scoring
from finance_qa.modules.solve.solvers.table_profiles.columns import (
    build_column_group_candidates,
    build_column_profiles,
)
from finance_qa.modules.solve.solvers.table_profiles.rows import build_row_profiles
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
    RawScopeSlot,
)


def _ratio_numerator_roles(request: RawLinkRequest) -> set[str]:
    norm = request.query_norm
    if re.search(r"\b(?:ngan\s+han|duoi\s+(?:1|mot)\s+nam|duoi\s+12\s+thang)\b", norm):
        return {"lt_1y"}
    if re.search(r"\b(?:trung\s+han|1\s+(?:toi|den)\s+5\s+nam|tu\s+tren\s+1\s+nam\s+den\s+5\s+nam)\b", norm):
        return {"1_to_5y"}
    if re.search(r"\b(?:dai\s+han|tren\s+5\s+nam)\b", norm):
        return {"gt_5y"}
    return {"lt_1y", "1_to_5y", "gt_5y"}


def _candidate_rows(
    request: RawLinkRequest,
    slot: RawScopeSlot,
    table_id: str,
    ranked: Sequence[str],
    *,
    start_id: int,
    frame_loader=load_frame,
    meta_lookup=meta_for,
    page_text_lookup=page_text,
) -> list[RawCellCandidate]:
    try:
        df = frame_loader(table_id)
    except Exception:  # noqa: BLE001 - one unreadable table cannot answer
        return []
    if df.empty or df.shape[1] < 2:
        return []

    meta = meta_lookup(table_id)
    profile_label_col = None
    try:
        profile = build_table_profile(table_id, df)
        profile_labels = [row.label for row in profile.rows]
        profile_label_col = next((col for col in profile.label_columns if col in df.columns), None)
    except Exception:  # noqa: BLE001 - profile is advisory for linking
        profile_labels = []
    context = _scoring._table_context(meta, profile_labels)
    scoring_tokens, scoring_norm = _scoring._scoring_query_for_table(
        request,
        table_id,
        meta_lookup=meta_lookup,
    )
    table_score = _scoring._semantic_score(scoring_tokens, scoring_norm, context)
    label_col = profile_label_col or label_column(df)
    table_year = int(meta["year"]) if str(meta.get("year") or "").isdigit() else None
    # Section ancestors carry the metric on note tables whose value rows are
    # labelled by period only; identifier columns (`Mã số`, `Thuyết minh`) are
    # numeric but are not values.
    row_paths = {
        position: profile.path
        for position, profile in build_row_profiles(table_id, df=df, label_col=label_col).items()
        if profile.path and not profile.is_section_header
    }
    try:
        column_profiles = {
            profile.name: profile for profile in build_column_profiles(table_id, df=df)
        }
    except Exception:  # noqa: BLE001 - header enrichment is advisory for linking
        column_profiles = {}
    # Column scores do not depend on the row, so they are computed once per table.
    column_scores: dict[object, float] = {}
    for column in df.columns:
        if column == label_col:
            continue
        profile = column_profiles.get(str(column))
        if profile is not None and profile.is_identifier:
            continue
        # A share-of-total column cannot answer a question asked in đồng, and it holds a
        # number in the same row as the amount, so it wins ties it has no claim to.
        if request.target_unit in _scoring._MONEY_UNITS and _scoring._is_percent_column(column):
            continue
        column_scores[column] = max(0.0, min(1.0, _scoring._column_score(
            column,
            slot_year=slot.year,
            period=request.period,
            table_year=table_year,
            resolved_year=profile.resolved_year if profile else None,
        ) + _scoring._flow_column_adjustment(request, column)))

    # A breakdown table (`Điện | Than | Khác | Cộng`) holds the answer in its total
    # column unless the question names one of the parts. `_column_score` reads only
    # period wording, so those four columns tied and row order picked the winner.
    total_columns = {c for c in column_scores if _scoring._is_total_row(_norm(_scoring._leaf(c)))}
    if total_columns and not any(
        _scoring._token_score(scoring_tokens, _scoring._leaf(c)) > 0
        for c in column_scores
        if c not in total_columns
    ):
        for column in total_columns:
            column_scores[column] = min(1.0, column_scores[column] + 0.12)

    # `Cộng` says nothing about what is being added, so a total row borrows the best
    # score among the rows above it. This used to run only when the question spelled out
    # "tổng", which left every other total row at exactly 0 on the row axis: q109 asks
    # for prepayments to sellers and the answer is the note's `Cộng` row, scored 0.00.
    row_anchor = 0.0
    for position, raw_label in df[label_col].items():
        label = _scoring._text(raw_label)
        if label and not _scoring._is_total_row(label):
            row_anchor = max(
                row_anchor,
                _scoring._semantic_score(
                    scoring_tokens,
                    scoring_norm,
                    _scoring._row_text(label, row_paths.get(position)),
                ),
            )
    out: list[RawCellCandidate] = []

    for position, row in df.iterrows():
        row_label = _scoring._text(row.get(label_col))
        synthetic_total = False
        if not row_label and request.operation == "ratio" and _scoring._row_has_numeric_value(row, label_col):
            row_label = "Cộng"
            synthetic_total = True
        if not row_label:
            continue
        row_path = list(row_paths.get(position) or []) if _scoring._labels_a_row(row_label) else []
        total_row = _scoring._is_total_row(row_label)
        if synthetic_total:
            total_row = True
        generic_period_row = _scoring._is_generic_period_row(row_label)
        if not total_row and generic_period_row and request.operation != "ratio" and not row_path:
            # Without ancestors such a row has no linkable wording at all.
            continue
        row_score = (
            row_anchor if total_row
            else _scoring._semantic_score(
                scoring_tokens,
                scoring_norm,
                _scoring._row_text(row_label, row_path),
            )
        )
        if request.operation == "ratio" and generic_period_row:
            row_score = max(row_score, _scoring._generic_period_row_score(row_label, request.period))
        if not total_row:
            row_score = max(
                0.0,
                min(1.0, row_score + _scoring._row_period_adjustment(row_label, request.period)),
            )
        for column in df.columns:
            if column == label_col:
                continue
            if column not in column_scores:
                continue
            value = _scoring._safe_number(row[column])
            if value is None:
                continue
            col_score = column_scores[column]
            component_role = _scoring._component_role_from_text(
                _norm(f"{_scoring._row_text(row_label, row_path)} {column}"),
                is_total=total_row,
            )
            total_adjust = 0.0
            if request.wants_total:
                if total_row:
                    total_adjust = 0.35
                elif request.operation == "ratio" and component_role in _ratio_numerator_roles(request):
                    total_adjust = 0.0
                else:
                    total_adjust = -0.18
            elif total_row:
                # It borrowed the best row's score, so without it a total row would tie
                # the specific row it borrowed from. Enough to lose that tie, not enough
                # to fall behind rows the question does not name at all.
                total_adjust = -0.06
            elif _scoring._is_component_row(row_label) and row_score < row_anchor:
                # The dash is a printing convention, so charge it only while some other
                # row answers the question better. q313 asks for `Chi phí công cụ, dụng
                # cụ chờ phân bổ` and the note prints exactly that, under a dash.
                total_adjust = -0.12
            source_unit, source_unit_from = detect_unit(df, str(column), page_text_lookup(table_id))
            score = (
                row_score * 0.42
                + table_score * 0.24
                + col_score * 0.24
                + total_adjust
                + _scoring._rank_bonus(table_id, ranked)
            )
            if row_score == 0 and table_score < 0.18 and not (request.wants_total and total_row):
                continue
            if col_score <= 0 and request.period != "unknown":
                continue
            if score < 0.18:
                continue
            out.append(
                RawCellCandidate(
                    id=f"c{start_id + len(out)}",
                    slot_key=slot.key,
                    table_id=table_id,
                    ticker=slot.ticker,
                    year=slot.year,
                    row_position=int(position),
                    row_label=row_label,
                    row_path=row_path,
                    column=str(column),
                    value=float(value),
                    source_unit=(source_unit or "unknown"),  # type: ignore[arg-type]
                    source_unit_from=source_unit_from,
                    is_total_row=total_row,
                    row_score=round(row_score, 3),
                    table_score=round(table_score, 3),
                    column_score=round(col_score, 3),
                    score=round(max(0.0, min(score, 1.0)), 3),
                    table_context=_scoring._short_context(context, 420),
                )
            )
    return out


def build_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 12,
    max_tables: int = 140,
    frame_loader=load_frame,
    meta_lookup=meta_for,
    page_text_lookup=page_text,
    metadata_lookup=table_metadata,
) -> tuple[list[RawCellCandidate], dict[str, Any]]:
    """Build bounded candidates for each scope slot from raw CSV tables."""
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    all_candidates: list[RawCellCandidate] = []
    per_slot: dict[str, int] = {}
    per_slot_scanned: dict[str, int] = {}
    missing: list[str] = []
    next_id = 1
    for slot in request.slots:
        slot_candidates: list[RawCellCandidate] = []
        slot_ranked = list(dict.fromkeys([
            *[
                table_id for table_id in ranked
                if _request._scope_ok(table_id, slot, request.doc_type, meta_lookup=meta_lookup)
            ],
            *_request._scope_table_ids(slot, request.doc_type, metadata_lookup=metadata_lookup),
        ]))[:max_tables]
        per_slot_scanned[slot.key] = len(slot_ranked)
        for table_id in slot_ranked:
            if not _request._scope_ok(table_id, slot, request.doc_type, meta_lookup=meta_lookup):
                continue
            rows = _candidate_rows(
                request,
                slot,
                table_id,
                ranked,
                start_id=next_id,
                frame_loader=frame_loader,
                meta_lookup=meta_lookup,
                page_text_lookup=page_text_lookup,
            )
            next_id += len(rows)
            slot_candidates.extend(rows)
        slot_candidates.sort(
            key=lambda c: (
                -c.score,
                -c.row_score,
                -c.table_score,
                -c.column_score,
                c.table_id,
                c.row_position,
            )
        )
        kept = slot_candidates[:limit_per_slot]
        if not kept:
            missing.append(slot.key)
        per_slot[slot.key] = len(kept)
        all_candidates.extend(kept)
    # Reassign compact ids after per-slot pruning; this keeps planner prompts short.
    compact: list[RawCellCandidate] = []
    for index, candidate in enumerate(all_candidates, 1):
        compact.append(candidate.model_copy(update={"id": f"c{index}"}))
    return compact, {
        "candidate_count": len(compact),
        "per_slot": per_slot,
        "per_slot_scanned": per_slot_scanned,
        "missing_slots": missing,
    }


def _group_role_score(request: RawLinkRequest, group: RawGroupCandidate) -> float:
    norm = request.query_norm
    if group.semantic_role == "lt_1y" and re.search(r"\b(?:ngan\s+han|duoi\s+(?:1|mot)\s+nam|duoi\s+12\s+thang)\b", norm):
        return 0.28
    if group.semantic_role == "total" and re.search(r"\b(?:tong|tong\s+du\s+no|trong\s+tong|tren\s+tong)\b", norm):
        return 0.22
    if group.semantic_role in {"1_to_5y", "gt_5y"} and group.semantic_role in norm:
        return 0.16
    return 0.0


def _score_group_candidate(
    request: RawLinkRequest,
    group: RawGroupCandidate,
    *,
    table_score: float,
    rank_bonus: float,
) -> RawGroupCandidate:
    row_label = group.label.split("::", 1)[0]
    scoring_tokens = request.query_tokens
    row_score = _scoring._semantic_score(scoring_tokens, request.query_norm, row_label)
    score = row_score * 0.46 + table_score * 0.24 + _group_role_score(request, group) + rank_bonus
    return group.model_copy(update={"score": round(max(0.0, min(score, 1.0)), 3)})


def build_ratio_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    cell_limit_per_slot: int = 32,
    group_limit_per_slot: int = 18,
    max_tables: int = 140,
    frame_loader=load_frame,
    meta_lookup=meta_for,
    page_text_lookup=page_text,
    metadata_lookup=table_metadata,
) -> tuple[list[RawLinkedCandidate], dict[str, Any]]:
    """Build cell and group candidates for component-ratio planning."""
    cells, cell_diag = build_candidates(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=cell_limit_per_slot,
        max_tables=max_tables,
        frame_loader=frame_loader,
        meta_lookup=meta_lookup,
        page_text_lookup=page_text_lookup,
        metadata_lookup=metadata_lookup,
    )
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    groups_by_slot: dict[str, int] = {}
    all_groups: list[RawGroupCandidate] = []
    next_id = 1
    for slot in request.slots:
        slot_groups: list[RawGroupCandidate] = []
        slot_ranked = [
            table_id for table_id in ranked
            if _request._scope_ok(table_id, slot, request.doc_type, meta_lookup=meta_lookup)
        ][:max_tables]
        for table_id in slot_ranked:
            if not _request._scope_ok(table_id, slot, request.doc_type, meta_lookup=meta_lookup):
                continue
            try:
                df = frame_loader(table_id)
                profile = build_table_profile(table_id, df)
                context = _scoring._table_context(meta_lookup(table_id), [row.label for row in profile.rows])
                scoring_tokens, scoring_norm = _scoring._scoring_query_for_table(
                    request,
                    table_id,
                    meta_lookup=meta_lookup,
                )
                table_score = _scoring._semantic_score(scoring_tokens, scoring_norm, context)
                raw_groups = build_column_group_candidates(
                    table_id,
                    slot,
                    df=df,
                    start_id=next_id,
                )
            except Exception:  # noqa: BLE001 - advisory group extraction must fail closed
                continue
            next_id += len(raw_groups)
            for group in raw_groups:
                scored = _score_group_candidate(
                    request,
                    group,
                    table_score=table_score,
                    rank_bonus=_scoring._rank_bonus(table_id, ranked),
                )
                if scored.score >= 0.18:
                    slot_groups.append(scored)
        slot_groups.sort(
            key=lambda group: (
                -group.score,
                group.table_ids[0] if group.table_ids else "",
                group.label,
                group.semantic_role,
            )
        )
        kept = slot_groups[:group_limit_per_slot]
        groups_by_slot[slot.key] = len(kept)
        all_groups.extend(kept)

    compact_groups: list[RawGroupCandidate] = []
    for index, group in enumerate(all_groups, 1):
        compact_groups.append(group.model_copy(update={"id": f"g{index}"}))
    candidates: list[RawLinkedCandidate] = [*cells, *compact_groups]
    diag = dict(cell_diag)
    diag.update({
        "candidate_count": len(candidates),
        "cell_candidate_count": len(cells),
        "group_candidate_count": len(compact_groups),
        "groups_per_slot": groups_by_slot,
    })
    return candidates, diag


__all__ = [
    "_candidate_rows",
    "_group_role_score",
    "_ratio_numerator_roles",
    "_score_group_candidate",
    "build_candidates",
    "build_ratio_candidates",
]
