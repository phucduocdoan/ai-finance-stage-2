"""Offline tests for row-hierarchy enrichment primitives."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.solvers.table_linking import (  # noqa: E402
    LinkedRowProfile,
    build_row_profiles,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


# A real investment-property note: three identical `Số cuối năm` leaves whose only
# distinguishing evidence is the section header above them.
KBC_NOTE = "KBC_financial_statements_2019_consolidated|25"

profiles = build_row_profiles(KBC_NOTE)

check("section header rows are detected", [p.position for p in profiles.values() if p.is_section_header] == [0, 1, 6, 11])
check(
    "carrying-value leaf keeps its section ancestors",
    profiles[13].path_text
    == "Nhà xưởng (bao gồm chi phí phát triển đất và cơ sở hạ tầng) > Giá trị còn lại: > Số cuối năm",
)
check(
    "cost leaf with the same label lands in a different section",
    profiles[5].path == profiles[13].path[:-1] + ["Nguyên giá:"],
)
check("identical leaf labels are told apart by path", profiles[5].path_text != profiles[13].path_text)
check("value rows are not section headers", not profiles[13].is_section_header and profiles[13].has_value)
check("section header keeps only its own ancestors", profiles[11].path_text.endswith("> Giá trị còn lại:"))

# A flat balance sheet must be left alone: every row is its own leaf, and the
# spilled `2021 VND` header row names no section.
NVL_BALANCE_SHEET = "NVL_financial_statements_2022_consolidated|8"
flat = build_row_profiles(NVL_BALANCE_SHEET)
check("flat statement gets no section headers", not any(p.is_section_header for p in flat.values()))
check("flat statement rows carry no path", all(not p.path for p in flat.values()))
check("flat statement leaf label is unchanged", flat[18].path_text == "Chi phí xây dựng cơ bản dở dang")


def profiles_from(rows: list[list[object]], columns: list[str]) -> dict[int, LinkedRowProfile]:
    frame = pd.DataFrame(rows, columns=columns)
    return build_row_profiles("synthetic|1", df=frame, label_col=columns[0])


nested = profiles_from(
    [
        ["Bất động sản đầu tư", None],
        ["Nguyên giá:", None],
        ["Số cuối năm", 100.0],
        ["Giá trị còn lại:", None],
        ["Số cuối năm", 40.0],
    ],
    ["label", "value"],
)
check("consecutive headers nest", nested[1].path == ["Bất động sản đầu tư"])
check(
    "a header after value rows replaces its sibling",
    nested[4].path == ["Bất động sản đầu tư", "Giá trị còn lại:"],
)

unit_row = profiles_from(
    [
        ["Triệu VND", None],
        ["Đơn vị tính: VND", None],
        ["2019VND", None],
        ["31.12.2019VND", None],
        ["Tiền gửi", 10.0],
    ],
    ["label", "value"],
)
check("unit-only rows name no section", all(not p.is_section_header for p in unit_row.values()))
check("unit-only rows do not pollute paths", not unit_row[4].path)

deep = profiles_from(
    [
        ["Tài sản", None],
        ["Bất động sản", None],
        ["Nhà xưởng", None],
        ["Giá trị còn lại:", None],
        ["Số cuối năm", 1.0],
    ],
    ["label", "value"],
)
check(
    "path depth is bounded to the innermost sections",
    deep[4].path == ["Bất động sản", "Nhà xưởng", "Giá trị còn lại:"],
)

print("\nall table-linking row tests passed")
