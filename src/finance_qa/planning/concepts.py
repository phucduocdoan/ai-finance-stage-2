"""Canonical financial concepts whose report labels are not literal aliases.

This is domain ontology, not question-specific correction: entries describe a
financial term once and apply to every company, year, and table that uses it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


ROW_CONCEPTS = (
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

CONTRASTING_PHRASES = (
    ("trong nước", "nước ngoài"),
    ("nước ngoài", "trong nước"),
)

FORMULA_ROW_REQUIREMENTS = (
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


def _matches(row_text: str, concept: dict[str, Any]) -> bool:
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
    for expected, contradictory in CONTRASTING_PHRASES:
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

    for concept in ROW_CONCEPTS:
        if not any(alias in folded_question for alias in concept["question_aliases"]):
            continue

        selected_match = False
        for binding in plan.get("bindings", []):
            variable = binding.get("variable")
            row_index = binding.get("row_index")
            if variable not in frames or not isinstance(row_index, int):
                continue
            if 0 <= row_index < len(frames[variable]) and _matches(
                _row_text(frames[variable], row_index), concept
            ):
                selected_match = True
                break
        if selected_match:
            continue

        candidates = []
        for variable, frame in frames.items():
            for row_index in range(len(frame)):
                text = _row_text(frame, row_index)
                if _matches(text, concept):
                    candidates.append(f"{variable}.row {row_index}: {text[:120]!r}")
        detail = "; ".join(candidates[:6]) or "không tìm thấy candidate trong bảng"
        errors.append(
            f"concept {concept['name']}: {concept['explanation']}; candidates: {detail}"
        )

    selected_rows = []
    for binding in plan.get("bindings", []):
        variable = binding.get("variable")
        row_index = binding.get("row_index")
        if variable in frames and isinstance(row_index, int):
            if 0 <= row_index < len(frames[variable]):
                selected_rows.append(_row_text(frames[variable], row_index))
    for requirement in FORMULA_ROW_REQUIREMENTS:
        if not any(
            alias in folded_question for alias in requirement["question_aliases"]
        ):
            continue
        missing_groups = [
            aliases
            for aliases in requirement["required_groups"]
            if not any(alias in row for alias in aliases for row in selected_rows)
        ]
        if missing_groups:
            candidates = []
            for variable, frame in frames.items():
                for row_index in range(len(frame)):
                    text = _row_text(frame, row_index)
                    if any(
                        alias in text
                        for aliases in missing_groups
                        for alias in aliases
                    ):
                        candidates.append(f"{variable}.row {row_index}: {text[:120]!r}")
            errors.append(
                f"concept {requirement['name']}: {requirement['explanation']}; "
                f"candidates: {'; '.join(candidates[:6])}"
            )
    return errors
