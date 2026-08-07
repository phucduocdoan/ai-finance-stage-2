"""Pure validator functions: return a list of error strings, never mutate the plan."""

from __future__ import annotations

import ast
import re
from typing import Any

import pandas as pd

from finance_qa.planning.ir import UNIT_HINT_MAP, question_context
from finance_qa.planning.table_profile import _CURRENT_COL_MARKERS, _PRIOR_COL_MARKERS
from finance_qa.preprocessing.questions import detect_unit, find_years


# ---------------------------------------------------------------------------
# Semantic validators (question vs query)
# ---------------------------------------------------------------------------

def semantic_errors(
    question: str,
    query: str,
    frames: dict[str, pd.DataFrame],
) -> list[str]:
    """Cheap invariants visible from the question but not from successful eval()."""
    q = question.casefold()
    errors: list[str] = []

    if "trung bình" in q:
        n_points = len(re.findall(r"\b(?:19|20)\d{2}\b", question))
        has_average = ".mean(" in query or "len(" in query
        if n_points > 1:
            has_average = has_average or re.search(
                rf"/\s*(?:float\()?{n_points}(?:\.0)?\)?(?:\D|$)", query
            ) is not None
        if not has_average:
            errors.append(f"câu hỏi lấy trung bình {n_points} mốc nhưng query chưa chia {n_points}")

    years = find_years(question)
    if len(years) > 1:
        direction = None
        if "cao nhất" in q or "lớn nhất" in q:
            direction = "max"
        elif "thấp nhất" in q or "nhỏ nhất" in q:
            direction = "min"
        if direction and not re.search(
            rf"\.(?:idx)?{direction}\s*\(|\b{'nlargest' if direction == 'max' else 'nsmallest'}\s*\(",
            query,
        ):
            errors.append(
                f"câu hỏi chọn năm có giá trị {direction} nhưng query chưa thực hiện "
                f"phép chọn {direction} trên các năm. "
                f"Dùng pd.Series({{'2021': val_2021, '2022': val_2022, ...}}).idx{direction}() "
                f"để lấy năm có giá trị {direction}, rồi dùng dict[năm_đó] để lấy answer."
            )
    return errors


# ---------------------------------------------------------------------------
# Plan validators (plan structure vs question / tables)
# ---------------------------------------------------------------------------

def plan_order_errors(
    question: str,
    plan: dict[str, Any],
    table_ids: dict[str, str],
) -> list[str]:
    """Enforce A-B ordering for a two-company difference from enriched entities."""
    if "chênh lệch" not in question.casefold():
        return []
    tickers = question_context(question).get("tickers") or []
    if len(tickers) != 2:
        return []
    try:
        body = ast.parse(plan["formula"], mode="eval").body
    except (KeyError, SyntaxError, TypeError):
        return []
    if not (
        isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Sub)
        and isinstance(body.left, ast.Name)
        and isinstance(body.right, ast.Name)
    ):
        return []
    by_id = {binding.get("id"): binding for binding in plan.get("bindings", [])}
    left = by_id.get(body.left.id, {}).get("variable")
    right = by_id.get(body.right.id, {}).get("variable")
    if left not in table_ids or right not in table_ids:
        return []
    actual = [table_ids[left].split("_", 1)[0], table_ids[right].split("_", 1)[0]]
    if actual == tickers:
        return []
    if actual == list(reversed(tickers)):
        return [
            f"chênh lệch phải theo thứ tự câu hỏi {tickers[0]} - {tickers[1]}, "
            f"formula đang là {actual[0]} - {actual[1]}"
        ]
    return []


def plan_contract_errors(
    question: str,
    plan: dict[str, Any],
    table_ids: dict[str, str] | None = None,
) -> list[str]:
    """Check plan result shape and multi-period coverage against enriched metadata."""
    context = question_context(question)
    hint = context.get("unit_hint") or detect_unit(question)
    expected_units = UNIT_HINT_MAP.get(hint)
    errors = []
    output_unit = plan.get("output_unit")
    if expected_units and output_unit not in expected_units:
        errors.append(
            f"output_unit={output_unit!r} không khớp đơn vị câu hỏi {hint!r}; "
            f"phải thuộc {sorted(expected_units)}"
        )

    years = context.get("years") or find_years(question)
    formula = plan.get("formula", "")
    is_multi_period_op = len(years) > 1 and re.search(
        r"\b(argmax|argmin|mean|sum|max|min)(?:_where)?\s*\(", formula
    )
    if is_multi_period_op:
        plan_text = " ".join(
            [formula]
            + [
                f"{b.get('id', '')} {b.get('meaning', '')} {b.get('column', '')}"
                for b in plan.get("bindings", [])
            ]
        )
        missing = [year for year in years if str(year) not in plan_text]
        if missing:
            errors.append(
                "plan chưa bao phủ các năm đã hỏi: "
                + ", ".join(str(year) for year in missing)
            )

    if table_ids:
        for binding in plan.get("bindings", []):
            if not isinstance(binding, dict):
                continue
            variable = binding.get("variable")
            table_id = table_ids.get(variable, "")
            report_match = re.search(r"financial_statements_(20\d{2})", table_id)
            if not report_match:
                continue
            report_year = int(report_match.group(1))
            column = str(binding.get("column", ""))
            column_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", column)}
            column_folded = column.casefold()
            if len(column_years) == 1:
                inferred_year = next(iter(column_years))
            elif any(marker in column_folded for marker in _PRIOR_COL_MARKERS):
                inferred_year = report_year - 1
            elif any(marker in column_folded for marker in _CURRENT_COL_MARKERS):
                inferred_year = report_year
            else:
                continue
            claimed_text = f"{binding.get('id', '')} {binding.get('meaning', '')}"
            claimed_years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", claimed_text)}
            if claimed_years and inferred_year not in claimed_years:
                errors.append(
                    f"binding {binding.get('id')!r} ghi năm {sorted(claimed_years)} "
                    f"nhưng cột {column!r} của report {report_year} biểu diễn năm {inferred_year}"
                )
    return errors


# ---------------------------------------------------------------------------
# Concept validator (domain ontology)
# ---------------------------------------------------------------------------

_ROW_CONCEPTS = (
    {
        "name": "share_capital",
        "question_aliases": ("vốn cổ phần",),
        "row_aliases": (
            "vốn góp của chủ sở hữu",
            "cổ phiếu phổ thông có quyền biểu quyết",
            "vốn điều lệ",
            "vốn cổ phần",
        ),
        "row_exclusions": ("thặng dư",),
        "explanation": (
            "vốn cổ phần là vốn góp/cổ phiếu theo mệnh giá, không phải tổng "
            "vốn chủ sở hữu hay thặng dư vốn cổ phần"
        ),
    },
)

_CONTRASTING_PHRASES = (
    ("trong nước", "nước ngoài"),
    ("nước ngoài", "trong nước"),
)

_FORMULA_ROW_REQUIREMENTS = (
    {
        "name": "interest_coverage",
        "question_aliases": ("khả năng thanh toán lãi vay",),
        "required_groups": (
            ("lợi nhuận kế toán trước thuế", "lợi nhuận trước thuế"),
            ("chi phí lãi vay",),
        ),
        "explanation": (
            "khả năng thanh toán lãi vay cần lợi nhuận trước thuế và chi phí "
            "lãi vay; lợi nhuận sau thuế không thay thế được lợi nhuận trước thuế"
        ),
    },
)


def _row_text(df: pd.DataFrame, row_index: int) -> str:
    return " ".join(
        str(value).strip().casefold()
        for value in df.iloc[row_index]
        if isinstance(value, str) and value.strip()
    )


def _concept_matches(row_text: str, concept: dict[str, Any]) -> bool:
    return any(alias in row_text for alias in concept["row_aliases"]) and not any(
        phrase in row_text for phrase in concept["row_exclusions"]
    )


def binding_concept_errors(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> list[str]:
    """Require selected rows to satisfy any canonical concept in the question."""
    folded_question = question.casefold()
    errors = []

    for expected, contradictory in _CONTRASTING_PHRASES:
        if expected not in folded_question:
            continue
        for binding in plan.get("bindings", []):
            variable = binding.get("variable")
            row_index = binding.get("row_index")
            selected_text = str(binding.get("meaning", "")).casefold()
            if variable in frames and isinstance(row_index, int):
                if 0 <= row_index < len(frames[variable]):
                    selected_text += " " + _row_text(frames[variable], row_index)
            if contradictory in selected_text:
                errors.append(
                    f"binding {binding.get('id')!r} mâu thuẫn câu hỏi: cần "
                    f"{expected!r}, nhưng dòng/meaning ghi {contradictory!r}"
                )

    for concept in _ROW_CONCEPTS:
        if not any(alias in folded_question for alias in concept["question_aliases"]):
            continue
        selected_match = any(
            variable in frames
            and isinstance(row_index, int)
            and 0 <= row_index < len(frames[variable])
            and _concept_matches(_row_text(frames[variable], row_index), concept)
            for binding in plan.get("bindings", [])
            if isinstance(binding, dict)
            for variable, row_index in [(binding.get("variable"), binding.get("row_index"))]
        )
        if selected_match:
            continue
        candidates = [
            f"{var}.row {row}: {_row_text(frame, row)[:120]!r}"
            for var, frame in frames.items()
            for row in range(len(frame))
            if _concept_matches(_row_text(frame, row), concept)
        ]
        errors.append(
            f"concept {concept['name']}: {concept['explanation']}; "
            f"candidates: {'; '.join(candidates[:6]) or 'không tìm thấy'}"
        )

    selected_rows = [
        _row_text(frames[variable], row_index)
        for binding in plan.get("bindings", [])
        if isinstance(binding, dict)
        for variable, row_index in [(binding.get("variable"), binding.get("row_index"))]
        if variable in frames and isinstance(row_index, int) and 0 <= row_index < len(frames[variable])
    ]
    for requirement in _FORMULA_ROW_REQUIREMENTS:
        if not any(alias in folded_question for alias in requirement["question_aliases"]):
            continue
        missing_groups = [
            aliases for aliases in requirement["required_groups"]
            if not any(alias in row for alias in aliases for row in selected_rows)
        ]
        if missing_groups:
            candidates = [
                f"{var}.row {row}: {_row_text(frame, row)[:120]!r}"
                for var, frame in frames.items()
                for row in range(len(frame))
                if any(
                    alias in _row_text(frame, row)
                    for aliases in missing_groups for alias in aliases
                )
            ]
            errors.append(
                f"concept {requirement['name']}: {requirement['explanation']}; "
                f"candidates: {'; '.join(candidates[:6])}"
            )
    return errors
