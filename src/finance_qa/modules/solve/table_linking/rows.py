"""Row-hierarchy enrichment for raw table linking.

OCR'd note tables keep the metric in section header rows and label the numeric
rows by period only:

```text
Nhà xưởng (bao gồm chi phí phát triển đất và cơ sở hạ tầng)
Nguyên giá:
  Số đầu năm            173.618.450.871
  Số cuối năm           476.439.458.160
Giá trị hao mòn lũy kế:
  Số cuối năm            43.720.836.237
Giá trị còn lại:
  Số cuối năm           432.718.621.923
```

A leaf label of `Số cuối năm` carries no linkable wording — every token is a
stopword — and the same label appears three times in one table. Scoring or
prompting on the leaf alone therefore cannot reach the right cell. This module
recovers the ancestor chain deterministically so a solver can score and render
`Nhà xưởng ... > Giá trị còn lại: > Số cuối năm`.

Section headers are detected structurally: a row with a label, no numeric value
anywhere, and at least one word that is not a year or a unit — otherwise a
spilled `2021 VND` header row would be read as a section. Consecutive header rows
nest; a header after value rows replaces its sibling. Tables with no such rows get
empty paths, so flat statements behave exactly as before.

The normalized DataFrame stays the execution authority. Profiles are keyed by row
position and never rewrite a label or a value.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd
from pydantic import BaseModel, Field

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.lookup import label_column
from finance_qa.modules.tools.numeric import parse_number


MAX_PATH_DEPTH = 3

_NON_WORD = re.compile(r"[^a-z0-9]+")
# A spilled header/unit row such as `2021 VND` or `Đơn vị tính: VND` has no
# metric wording, so it names no section.
_UNIT_WORDS = frozenset({
    "vnd", "usd", "dong", "trieu", "ty", "nghin", "tram", "don", "vi", "tinh",
    "unit", "currency",
})


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _norm(text: object) -> str:
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _names_a_section(label: str) -> bool:
    for token in _norm(label).split():
        # OCR glues the year to the unit (`2021VND`), so digits are stripped
        # before asking whether what remains is a word or just a unit.
        word = token.strip("0123456789")
        if len(word) > 1 and word not in _UNIT_WORDS:
            return True
    return False


def _has_numeric_value(row: pd.Series, label_col: object) -> bool:
    for column in row.index:
        if column == label_col:
            continue
        value = row[column]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not pd.isna(value):
                return True
            continue
        if parse_number(_text(value)) is not None:
            return True
    return False


class LinkedRowProfile(BaseModel):
    """One normalized DataFrame row with its section ancestors."""

    position: int
    label: str = ""
    path: list[str] = Field(default_factory=list)
    is_section_header: bool = False
    has_value: bool = False

    @property
    def path_text(self) -> str:
        pieces = [*self.path, self.label] if self.label else list(self.path)
        return " > ".join(pieces)


def build_row_profiles(
    table_id: str,
    *,
    df: pd.DataFrame | None = None,
    label_col: object | None = None,
) -> dict[int, LinkedRowProfile]:
    """Map row position -> row profile with ancestor section labels."""
    if df is None:
        df = load_frame(table_id)
    if df.empty or df.shape[1] < 2:
        return {}
    if label_col is None or label_col not in df.columns:
        try:
            label_col = label_column(df)
        except Exception:  # noqa: BLE001 - without a label column there is no hierarchy
            return {}

    profiles: dict[int, LinkedRowProfile] = {}
    stack: list[str] = []
    previous_was_header = False
    for position, row in df.iterrows():
        label = _text(row.get(label_col))
        has_value = _has_numeric_value(row, label_col)
        if label and not has_value and _names_a_section(label):
            if not previous_was_header and stack:
                # A header after value rows closes its sibling section rather
                # than nesting inside it.
                stack.pop()
            stack.append(label)
            del stack[:-MAX_PATH_DEPTH]
            profiles[int(position)] = LinkedRowProfile(
                position=int(position),
                label=label,
                path=stack[:-1],
                is_section_header=True,
            )
            previous_was_header = True
            continue
        profiles[int(position)] = LinkedRowProfile(
            position=int(position),
            label=label,
            path=list(stack),
            has_value=has_value,
        )
        previous_was_header = False
    return profiles


__all__ = ["LinkedRowProfile", "MAX_PATH_DEPTH", "build_row_profiles"]
