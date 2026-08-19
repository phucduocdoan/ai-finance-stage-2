"""Deterministic diagnostics over the final codegen cell selection.

This module does not answer questions and does not repair queries. It compares
the final pandas query against a typed ``TableProfile`` so offline runs can say
whether a miss looks like a year-column mistake, row/metric mismatch, unit-kind
mistake, or a multi-axis question collapsed to one cell.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from typing import Any, Literal, Mapping

import pandas as pd
from pydantic import BaseModel, Field

from finance_qa.modules.solve.structured_facts import (
    DERIVED_ALIASES,
    PRIMITIVES,
    canonical_metric,
    metric_source_unit,
    metrics_in_text,
)
from finance_qa.modules.solve.table_profile import (
    ProfileColumn,
    ProfileRow,
    TableProfile,
    build_table_profile,
)
from finance_qa.modules.solve.units import MONEY_SCALE, unit_from_hint


Severity = Literal["info", "weak", "strong"]

_NON_WORD = re.compile(r"[^a-z0-9]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_PRIOR_PERIOD = re.compile(
    r"\b(?:dau nam|dau ky|nam truoc|ky truoc|01 01|1 1)\b"
)
_DETAIL_TERMS = (
    "thuyet minh",
    "chi tiet",
    "nguyen vat lieu",
    "gia goc",
    "the chap",
    "cam co",
    "nguoi ban",
    "khach hang",
    "khu vuc",
    "mien ",
    "thanh pham",
    "cong cu dung cu",
    "vay ngan han",
    "vay dai han",
)
_COMPARISON_TERMS = (
    "chenh lech",
    "tang truong",
    "so voi",
    "cao nhat",
    "thap nhat",
    "lon nhat",
    "nho nhat",
    "trung binh",
    "binh quan",
    "median",
)
_RATIO_TERMS = (
    "ty le",
    "ty so",
    "ty suat",
    "he so",
    "bien loi",
    "roe",
    "roa",
    "d e",
    "tren",
)
_PERIOD_LABEL_TERMS = (
    "so cuoi",
    "so dau",
    "nam nay",
    "nam truoc",
    "31 12",
    "01 01",
)
_NOTE_REF = re.compile(r"^(?:[ivxlcdm]+|v)\s*\d+[a-z]?$")


def _norm(text: object) -> str:
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _literal_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        return -int(node.operand.value)
    return None


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return str(node.value)
    return None


class QueryRef(BaseModel):
    """One dataframe cell reference found in the final pandas query."""

    variable: str
    row_position: int | None = None
    column: str = ""
    column_index: int | None = None
    expression: str = ""


class ProfileQueryCell(BaseModel):
    """One resolved query reference, with table-profile attributes attached."""

    variable: str
    table_id: str = ""
    row_position: int | None = None
    row_label: str = ""
    row_metrics: list[str] = Field(default_factory=list)
    column: str = ""
    column_index: int | None = None
    column_role: str = ""
    column_year: int | None = None
    column_unit: str = ""
    natural_unit: str = ""
    expression: str = ""


class ProfileFinding(BaseModel):
    """A validation signal. Diagnostic only; no score-time behavior changes."""

    code: str
    severity: Severity
    message: str
    variable: str = ""
    table_id: str = ""
    row_position: int | None = None
    column: str = ""


def _slice_pair(node: ast.AST) -> tuple[int | None, str | int | None]:
    if not isinstance(node, ast.Tuple) or len(node.elts) < 2:
        return None, None
    row = _literal_int(node.elts[0])
    col_text = _literal_str(node.elts[1])
    col: str | int | None = col_text if col_text is not None else _literal_int(node.elts[1])
    return row, col


def _append_ref(
    refs: list[QueryRef],
    seen: set[tuple[str, int | None, str, int | None]],
    *,
    variable: str,
    row: int | None,
    column: str | int | None,
    expression: str,
) -> None:
    column_text = column if isinstance(column, str) else ""
    column_index = column if isinstance(column, int) else None
    key = (variable, row, column_text, column_index)
    if row is None or column is None or key in seen:
        return
    seen.add(key)
    refs.append(
        QueryRef(
            variable=variable,
            row_position=row,
            column=column_text,
            column_index=column_index,
            expression=expression,
        )
    )


def query_cell_refs(query: str) -> list[QueryRef]:
    """Extract common ``dfN.iloc[row][col]`` cell reads from a pandas expression."""
    try:
        tree = ast.parse(query or "", mode="eval")
    except SyntaxError:
        return []

    refs: list[QueryRef] = []
    seen: set[tuple[str, int | None, str, int | None]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        expr = ast.get_source_segment(query, node) or ""

        # df1.iloc[12, 3] or df1.iloc[12, "Năm nay"]
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "iloc"
            and isinstance(node.value.value, ast.Name)
        ):
            row, column = _slice_pair(node.slice)
            _append_ref(
                refs,
                seen,
                variable=node.value.value.id,
                row=row,
                column=column,
                expression=expr,
            )

        # df1.iloc[12]["Năm nay"]
        if (
            isinstance(node.value, ast.Subscript)
            and isinstance(node.value.value, ast.Attribute)
            and node.value.value.attr == "iloc"
            and isinstance(node.value.value.value, ast.Name)
        ):
            row = _literal_int(node.value.slice)
            col_text = _literal_str(node.slice)
            col: str | int | None = col_text if col_text is not None else _literal_int(node.slice)
            _append_ref(
                refs,
                seen,
                variable=node.value.value.value.id,
                row=row,
                column=col,
                expression=expr,
            )

        # df1["Năm nay"].iloc[12]
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "iloc"
            and isinstance(node.value.value, ast.Subscript)
            and isinstance(node.value.value.value, ast.Name)
        ):
            row = _literal_int(node.slice)
            col_text = _literal_str(node.value.value.slice)
            col: str | int | None = col_text if col_text is not None else _literal_int(node.value.value.slice)
            _append_ref(
                refs,
                seen,
                variable=node.value.value.value.id,
                row=row,
                column=col,
                expression=expr,
            )
    return refs


def _row_at(profile: TableProfile, position: int | None) -> ProfileRow | None:
    if position is None:
        return None
    return next((row for row in profile.rows if row.position == position), None)


def _column_at(
    profile: TableProfile,
    *,
    column: str = "",
    column_index: int | None = None,
) -> ProfileColumn | None:
    if column:
        return next((col for col in profile.columns if col.name == column), None)
    if column_index is None:
        return None
    return next((col for col in profile.columns if col.index == column_index), None)


def _natural_unit(row_metrics: list[str], column_unit: str) -> str:
    for metric in row_metrics:
        unit = metric_source_unit(metric)
        if unit and unit != "unknown":
            return unit
    return column_unit or "unknown"


def _resolved_cells(
    refs: list[QueryRef],
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
) -> tuple[list[ProfileQueryCell], list[ProfileFinding], dict[str, TableProfile]]:
    findings: list[ProfileFinding] = []
    profiles: dict[str, TableProfile] = {}
    cells: list[ProfileQueryCell] = []
    for ref in refs:
        table_id = names.get(ref.variable, "")
        frame = frames.get(ref.variable)
        if frame is None or not table_id:
            findings.append(
                ProfileFinding(
                    code="unknown_dataframe",
                    severity="strong",
                    message="Query reads a dataframe variable that is not bound in state.",
                    variable=ref.variable,
                    table_id=table_id,
                    row_position=ref.row_position,
                    column=ref.column,
                )
            )
            continue
        try:
            profile = profiles.setdefault(ref.variable, build_table_profile(table_id, frame))
        except Exception as exc:  # noqa: BLE001 - validator is diagnostic only
            findings.append(
                ProfileFinding(
                    code="profile_build_failed",
                    severity="weak",
                    message=f"TableProfile could not be built: {type(exc).__name__}: {exc}",
                    variable=ref.variable,
                    table_id=table_id,
                    row_position=ref.row_position,
                    column=ref.column,
                )
            )
            continue

        row = _row_at(profile, ref.row_position)
        column = _column_at(profile, column=ref.column, column_index=ref.column_index)
        if column is None:
            findings.append(
                ProfileFinding(
                    code="unknown_column",
                    severity="strong",
                    message="Query column is not present in the table profile.",
                    variable=ref.variable,
                    table_id=table_id,
                    row_position=ref.row_position,
                    column=ref.column or str(ref.column_index),
                )
            )
        if ref.row_position is not None and not (0 <= ref.row_position < len(frame)):
            findings.append(
                ProfileFinding(
                    code="row_out_of_bounds",
                    severity="strong",
                    message="Query row position is outside the dataframe.",
                    variable=ref.variable,
                    table_id=table_id,
                    row_position=ref.row_position,
                    column=ref.column,
                )
            )

        row_metrics = list(row.metric_candidates) if row is not None else []
        column_name = column.name if column is not None else ref.column
        cells.append(
            ProfileQueryCell(
                variable=ref.variable,
                table_id=table_id,
                row_position=ref.row_position,
                row_label="" if row is None else row.label,
                row_metrics=row_metrics,
                column=column_name,
                column_index=column.index if column is not None else ref.column_index,
                column_role=column.role if column is not None else "",
                column_year=column.year if column is not None else None,
                column_unit=column.unit if column is not None else "",
                natural_unit=_natural_unit(row_metrics, column.unit if column is not None else ""),
                expression=ref.expression,
            )
        )
    return cells, findings, profiles


def _years_from_state(state: Mapping[str, Any], question: str) -> list[int]:
    years = [int(y) for y in (state.get("years") or []) if str(y).isdigit()]
    for match in _YEAR.finditer(question):
        year = int(match.group(0))
        if year not in years:
            years.append(year)
    return years


def _expected_year(question: str, years: list[int]) -> int | None:
    if len(years) != 1:
        return None
    year = years[0]
    return year - 1 if _PRIOR_PERIOD.search(_norm(question)) else year


def _intent(state: Mapping[str, Any]) -> dict[str, Any]:
    question = str(state.get("question") or "")
    metric = canonical_metric(str(state.get("metric") or ""))
    metrics = metrics_in_text(" ".join([question, metric]))
    if metric and metric not in metrics:
        metrics.insert(0, metric)
    expected_unit = (
        unit_from_hint(str(state.get("unit_hint") or ""))
        or unit_from_hint(question)
        or (metric_source_unit(metric) if metric else "")
        or "unknown"
    )
    norm_question = _norm(question)
    if expected_unit == "unknown" and "nam nao" in norm_question:
        expected_unit = "year"
    if expected_unit in MONEY_SCALE:
        expected_kind = "money"
    elif expected_unit in {"percent", "ratio"}:
        expected_kind = "ratio"
    elif any(metric_source_unit(item) in {"percent", "ratio"} for item in metrics):
        expected_kind = "ratio"
    elif any(term in norm_question for term in _RATIO_TERMS):
        expected_kind = "ratio"
    elif metrics and all(metric_source_unit(item) in MONEY_SCALE for item in metrics):
        expected_kind = "money"
    else:
        expected_kind = "unknown"
    return {
        "years": _years_from_state(state, question),
        "metrics": metrics,
        "direct_metrics": [item for item in metrics if item in PRIMITIVES],
        "derived_metrics": [item for item in metrics if item in DERIVED_ALIASES],
        "expected_unit": expected_unit,
        "expected_kind": expected_kind,
        "detail_like": any(term in norm_question for term in _DETAIL_TERMS),
        "comparison_like": any(term in norm_question for term in _COMPARISON_TERMS),
    }


def _has_arithmetic(query: str) -> bool:
    try:
        tree = ast.parse(query or "", mode="eval")
    except SyntaxError:
        return False
    return any(isinstance(node, (ast.BinOp, ast.Compare, ast.BoolOp, ast.IfExp)) for node in ast.walk(tree))


def _suspect_shifted_profile(profile: TableProfile | None, cell: ProfileQueryCell) -> bool:
    """Whether profile roles themselves look displaced by extraction."""
    if profile is None:
        return False
    if "has_unnamed_columns" not in profile.quality_flags:
        return False
    if any(
        any(term in _norm(label_column) for term in _PERIOD_LABEL_TERMS)
        for label_column in profile.label_columns
    ):
        return True
    return bool(_NOTE_REF.match(_norm(cell.row_label)))


def _year_mismatch_severity(profile: TableProfile | None, cell: ProfileQueryCell) -> Severity:
    """Year repair is only safe on clean statement-like period columns."""
    if profile is None:
        return "strong"
    flags = set(profile.quality_flags)
    if flags & {"note_table", "wide_table"}:
        return "weak"
    if _suspect_shifted_profile(profile, cell):
        return "weak"
    return "strong"


def _add_cell_findings(
    findings: list[ProfileFinding],
    *,
    state: Mapping[str, Any],
    intent: Mapping[str, Any],
    cells: list[ProfileQueryCell],
    profiles: Mapping[str, TableProfile],
) -> None:
    question = str(state.get("question") or "")
    expected_year = _expected_year(question, list(intent.get("years") or []))
    if expected_year is not None and not bool(state.get("multi_year")):
        allowed_report_years = {expected_year, *list(intent.get("years") or [])}
        for cell in cells:
            profile = profiles.get(cell.variable)
            if (
                profile is not None
                and profile.year is not None
                and profile.year not in allowed_report_years
            ):
                findings.append(
                    ProfileFinding(
                        code="table_year_mismatch",
                        severity="strong",
                        message=f"Question asks for year {sorted(allowed_report_years)}, but query reads report year {profile.year}.",
                        variable=cell.variable,
                        table_id=cell.table_id,
                        row_position=cell.row_position,
                        column=cell.column,
                    )
                )
            if cell.column_year is not None and cell.column_year != expected_year:
                severity = _year_mismatch_severity(profile, cell)
                findings.append(
                    ProfileFinding(
                        code="column_year_mismatch",
                        severity=severity,
                        message=(
                            f"Question asks for column year {expected_year}, but query reads column year {cell.column_year}."
                            + (" This table/profile is not repair-safe." if severity == "weak" else "")
                        ),
                        variable=cell.variable,
                        table_id=cell.table_id,
                        row_position=cell.row_position,
                        column=cell.column,
                    )
                )

    direct_metrics = list(intent.get("direct_metrics") or [])
    if len(direct_metrics) == 1:
        expected = direct_metrics[0]
        for cell in cells:
            if cell.row_metrics and expected not in cell.row_metrics:
                findings.append(
                    ProfileFinding(
                        code="row_metric_mismatch",
                        severity="weak",
                        message=f"Question metric is {expected}, but selected row maps to {cell.row_metrics}.",
                        variable=cell.variable,
                        table_id=cell.table_id,
                        row_position=cell.row_position,
                        column=cell.column,
                    )
                )

    expected_kind = str(intent.get("expected_kind") or "unknown")
    if len(cells) == 1 and expected_kind in {"money", "ratio"}:
        cell = cells[0]
        if cell.column_role and cell.column_role != "numeric":
            findings.append(
                ProfileFinding(
                    code="non_numeric_column_read",
                    severity="strong",
                    message=f"Question expects a numeric value, but query reads a {cell.column_role} column.",
                    variable=cell.variable,
                    table_id=cell.table_id,
                    row_position=cell.row_position,
                    column=cell.column,
                )
            )
        if (
            expected_kind == "ratio"
            and cell.natural_unit in MONEY_SCALE
            and not _has_arithmetic(str(state.get("pandas_query") or ""))
        ):
            findings.append(
                ProfileFinding(
                    code="ratio_question_single_money_cell",
                    severity="weak",
                    message="Question appears ratio-like, but the query reads one money cell without arithmetic.",
                    variable=cell.variable,
                    table_id=cell.table_id,
                    row_position=cell.row_position,
                    column=cell.column,
                )
            )
        if expected_kind == "money" and cell.natural_unit in {"percent", "ratio"}:
            findings.append(
                ProfileFinding(
                    code="money_question_ratio_cell",
                    severity="weak",
                    message="Question appears money-like, but the selected row/column is ratio-like.",
                    variable=cell.variable,
                    table_id=cell.table_id,
                    row_position=cell.row_position,
                    column=cell.column,
                )
            )

    derived_metrics = list(intent.get("derived_metrics") or [])
    if len(cells) == 1 and derived_metrics and cells[0].row_metrics:
        cell = cells[0]
        if not any(metric in cell.row_metrics for metric in derived_metrics):
            findings.append(
                ProfileFinding(
                    code="derived_question_single_primitive_cell",
                    severity="weak",
                    message=f"Question asks for derived metric {derived_metrics}, but query reads one primitive row {cell.row_metrics}.",
                    variable=cell.variable,
                    table_id=cell.table_id,
                    row_position=cell.row_position,
                    column=cell.column,
                )
            )

    multi_axis = (
        bool(state.get("multi_year"))
        or bool(state.get("multi_company"))
        or len(intent.get("years") or []) > 1
        or len(state.get("tickers") or []) > 1
    )
    if multi_axis and len(cells) < 2 and intent.get("expected_unit") != "year":
        findings.append(
            ProfileFinding(
                code="multi_axis_single_cell",
                severity="weak",
                message="Question names multiple years/companies, but final query reads fewer than two cells.",
            )
        )

    if bool(intent.get("detail_like")) and cells:
        note_tables = [
            cell for cell in cells
            if "note_table" in (profiles.get(cell.variable).quality_flags if profiles.get(cell.variable) else [])
        ]
        if not note_tables:
            findings.append(
                ProfileFinding(
                    code="detail_question_non_note_table",
                    severity="weak",
                    message="Question looks like a note/detail request, but query reads no note table.",
                )
            )


def _metadata_findings(
    state: Mapping[str, Any],
    cells: list[ProfileQueryCell],
) -> list[ProfileFinding]:
    solution = state.get("solution") or {}
    if not isinstance(solution, Mapping):
        return []
    findings: list[ProfileFinding] = []
    table_variable = str(solution.get("table_variable") or "")
    target_column = str(solution.get("target_column") or "")
    if table_variable and cells and table_variable not in {cell.variable for cell in cells}:
        findings.append(
            ProfileFinding(
                code="solution_table_not_read",
                severity="weak",
                message="Solution.table_variable does not appear in the final pandas query.",
                variable=table_variable,
            )
        )
    if target_column and cells and target_column not in {cell.column for cell in cells}:
        findings.append(
            ProfileFinding(
                code="solution_column_not_read",
                severity="weak",
                message="Solution.target_column does not appear among parsed query cells.",
                variable=table_variable,
                column=target_column,
            )
        )
    return findings


def validate_profile_selection(
    state: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame] | None = None,
    names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return profile-based diagnostics for the final answer state."""
    frames = frames or {}
    names = names or {}
    query = str(state.get("pandas_query") or "")
    intent = _intent(state)
    refs = query_cell_refs(query)
    cells, findings, profiles = _resolved_cells(refs, frames, names)

    if not frames or not names:
        findings.append(
            ProfileFinding(
                code="no_bound_frames",
                severity="info",
                message="Final solver did not leave dataframe frames/names to validate.",
            )
        )
    if not refs:
        findings.append(
            ProfileFinding(
                code="no_iloc_cell_refs",
                severity="weak",
                message="Final pandas query contains no parseable .iloc cell reference.",
            )
        )
    if (state.get("diag") or {}).get("units", {}).get("failed"):
        findings.append(
            ProfileFinding(
                code="execution_failed",
                severity="strong",
                message="The final query failed execution before unit conversion.",
            )
        )
    if float(state.get("answer") or 0.0) == 0.0 and (
        not refs or (state.get("diag") or {}).get("units", {}).get("failed")
    ):
        findings.append(
            ProfileFinding(
                code="zero_answer_untrusted",
                severity="strong",
                message="Answer is zero and the query is missing or failed.",
            )
        )

    _add_cell_findings(findings, state=state, intent=intent, cells=cells, profiles=profiles)
    findings.extend(_metadata_findings(state, cells))

    return {
        "done": True,
        "query_cells": [cell.model_dump() for cell in cells],
        "findings": [finding.model_dump() for finding in findings],
        "intent": {
            "years": intent["years"],
            "metrics": intent["metrics"],
            "expected_unit": intent["expected_unit"],
            "expected_kind": intent["expected_kind"],
            "detail_like": intent["detail_like"],
            "comparison_like": intent["comparison_like"],
        },
        "summary": {
            "strong": sum(1 for finding in findings if finding.severity == "strong"),
            "weak": sum(1 for finding in findings if finding.severity == "weak"),
            "info": sum(1 for finding in findings if finding.severity == "info"),
        },
    }


__all__ = [
    "ProfileFinding",
    "ProfileQueryCell",
    "QueryRef",
    "query_cell_refs",
    "validate_profile_selection",
]
