"""Offline tests for column/header enrichment primitives."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.solvers import raw_table_linker as raw  # noqa: E402
from finance_qa.modules.solve.solvers.table_linking import (  # noqa: E402
    RawScopeSlot,
    build_column_group_candidates,
    build_column_profiles,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


ACB_TABLE = "ACB_financial_statements_2019_separate|97"

profiles = build_column_profiles(ACB_TABLE)
by_name = {profile.name: profile for profile in profiles}

check(
    "unnamed maturity column recovers raw subheader",
    "Từ trên 1 tháng đến 3 tháng" in by_name["Unnamed: 4"].raw_header_stack,
)
check("maturity column gets lt_1y role", "lt_1y" in by_name["Unnamed: 4"].semantic_roles)
check("total column gets total role", "total" in by_name["Unnamed: 8"].semantic_roles)
check("overdue column is not treated as lt_1y", "lt_1y" not in by_name["Quá hạn"].semantic_roles)
check(
    "maturity buckets get no year from column order",
    all(profile.resolved_year is None for profile in profiles),
)

# A balance sheet whose value column lost its year at the OCR line break, next to
# two numeric identifier columns. `repair_group_leaf_header` puts the year back from
# the spilled header row, so both periods are named and `column_years` has nothing
# left to infer -- that is why `resolved_year` is None here now.
NVL_BALANCE_SHEET = "NVL_financial_statements_2022_consolidated|8"
NVL_CURRENT = "Tại ngày 31 tháng 12 năm | 2022 VND"
NVL_PRIOR = "Tại ngày 31 tháng 12 năm | 2021 VND"
nvl = {profile.name: profile for profile in build_column_profiles(NVL_BALANCE_SHEET)}
check("Mã số column is an identifier", nvl["Mã số"].is_identifier)
check("Thuyết minh column is an identifier", nvl["Thuyết minh"].is_identifier)
check("value column is not an identifier", not nvl[NVL_CURRENT].is_identifier)
check("both periods are named, so neither needs a guessed year", set(nvl) >= {NVL_CURRENT, NVL_PRIOR})
check(
    "a named year is not repeated as a resolved one",
    nvl[NVL_CURRENT].resolved_year is None and nvl[NVL_PRIOR].resolved_year is None,
)

# OCR drops the space in these headers often enough to matter.
nvl_2020 = {profile.name: profile for profile in build_column_profiles("NVL_financial_statements_2020_consolidated|7")}
check("identifier match survives lost spaces", nvl_2020["Mãsố"].is_identifier and nvl_2020["Thuyếtminh"].is_identifier)

# Cell linking has to honour those two column facts: `Mã số`/`Thuyết minh` are
# numeric but are not values, and the value column's year is only recoverable
# from its period wording plus the report year.
nvl_request = raw.RawLinkRequest(
    operation="select",
    slots=[RawScopeSlot(ticker="NVL", year=2022)],
    doc_type="consolidated",
    period="current",
    target_unit="vnd",
    query_norm=raw._norm("chi phí xây dựng cơ bản dở dang cuối năm"),
    query_tokens=raw._tokens("chi phí xây dựng cơ bản dở dang cuối năm"),
)
nvl_cells, _ = raw.build_candidates(
    nvl_request,
    table_ids=[NVL_BALANCE_SHEET],
    limit_per_slot=40,
    max_tables=1,
)
nvl_rows = [cell for cell in nvl_cells if cell.table_id == NVL_BALANCE_SHEET]
check(
    "identifier columns never become value candidates",
    all(cell.column not in {"Mã số", "Thuyết minh"} for cell in nvl_rows),
)
cip = [cell for cell in nvl_rows if "xây dựng cơ bản dở dang" in cell.row_label]
check("construction-in-progress row still yields candidates", bool(cip))
# Both periods carrying their own year is stronger than outranking: the comparative
# column no longer reaches the candidate list for a `current` request at all.
check(
    "only the asked-for period becomes a candidate",
    {cell.column for cell in cip} == {NVL_CURRENT},
)

groups = build_column_group_candidates(
    ACB_TABLE,
    RawScopeSlot(ticker="ACB", year=2019),
)
loan_lt_1y = next(
    group for group in groups
    if group.semantic_role == "lt_1y" and group.label.startswith("Cho vay khách hàng")
)
loan_total = next(
    group for group in groups
    if group.semantic_role == "total" and group.label.startswith("Cho vay khách hàng")
)
check(
    "lt_1y group is built from four maturity bucket cells",
    [cell.column for cell in loan_lt_1y.cells]
    == ["Trong hạn", "Đơn vị: Triệu VND", "Unnamed: 4", "Unnamed: 5"],
)
check("lt_1y group sums selected physical cells", loan_lt_1y.value == 144152172.0)
check("total group points at total column", [cell.column for cell in loan_total.cells] == ["Unnamed: 8"])
check("total group preserves physical total value", loan_total.value == 265981486.0)


Q955 = (
    "Trung bình tỷ trọng cho vay ngắn hạn trong tổng dư nợ cho vay khách hàng "
    "vào cuối năm 2019 tại công ty mẹ của Ngân hàng TMCP Á Châu (ACB), "
    "Ngân hàng TMCP Quân đội (MBB), Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BID) "
    "và Ngân hàng TMCP Sài Gòn Tài Lộc (STB) là bao nhiêu phần trăm?"
)
Q955_TABLES = [
    "ACB_financial_statements_2019_separate|27",
    "ACB_financial_statements_2019_separate|97",
    "MBB_financial_statements_2019_separate|28",
    "BID_financial_statements_2019_separate|27",
    "STB_financial_statements_2019_separate|29",
]


def q955_request() -> raw.RawLinkRequest:
    return raw.RawLinkRequest(
        operation="ratio",
        slots=[
            RawScopeSlot(ticker="ACB", year=2019),
            RawScopeSlot(ticker="MBB", year=2019),
            RawScopeSlot(ticker="BID", year=2019),
            RawScopeSlot(ticker="STB", year=2019),
        ],
        doc_type="separate",
        period="current",
        target_unit="percent",
        query_norm=raw._norm(Q955),
        query_tokens=raw._tokens(Q955),
        wants_total=True,
        ratio_aggregate="avg",
    )


def q955_options() -> tuple[raw.RawLinkRequest, list[raw.RawLinkedCandidate], list[raw.RawRatioOption]]:
    request = q955_request()
    original_scope_table_ids = raw._scope_table_ids
    raw._scope_table_ids = lambda slot, doc_type: [
        table_id for table_id in Q955_TABLES
        if table_id.startswith(f"{slot.ticker}_")
    ]
    try:
        candidates, _ = raw.build_ratio_candidates(
            request,
            table_ids=Q955_TABLES,
            shortlist=Q955_TABLES,
            cell_limit_per_slot=80,
            group_limit_per_slot=12,
            max_tables=8,
        )
    finally:
        raw._scope_table_ids = original_scope_table_ids
    options, diag = raw.build_ratio_options(request, candidates, max_options_per_side=6)
    check("q955 ratio option surface has numerator and denominator per slot", diag["missing_options"] == [])
    return request, candidates, options


request, candidates, options = q955_options()
by_slot_side = {
    slot.key: {
        side: [option for option in options if option.slot_key == slot.key and option.side == side]
        for side in ("numerator", "denominator")
    }
    for slot in request.slots
}
check(
    "ACB direct maturity row is preferred over wide-group fallback",
    by_slot_side["ACB:2019"]["numerator"][0].label == "Ngắn hạn :: 31.12.2019Triệu VND",
)
check(
    "ACB wide maturity group remains available as fallback",
    any(
        option.source_kind == "group" and option.label == "Cho vay khách hàng (i) :: lt_1y"
        for option in by_slot_side["ACB:2019"]["numerator"]
    ),
)
check(
    "MBB numerator option links short-term loan row",
    by_slot_side["MBB:2019"]["numerator"][0].label == "Nợ ngắn hạn :: 31/12/2019triệu đồng",
)
check(
    "BID numerator option links short-term loan row",
    by_slot_side["BID:2019"]["numerator"][0].label
    == "Nợ ngắn hạn (Dưới 1 năm) :: Số cuối nămTriệu VND",
)
check(
    "STB numerator option links short-term loan row",
    by_slot_side["STB:2019"]["numerator"][0].label == "Nợ ngắn hạn :: Số cuối nămTriệu đồng",
)
check(
    "STB denominator option prefers loan total table",
    by_slot_side["STB:2019"]["denominator"][0].table_ids == ["STB_financial_statements_2019_separate|29"],
)

decision = raw.deterministic_ratio_option_decision(request, options)
check("deterministic ratio option selector accepts clear q955 surface", decision.supported)
ratio_decision = raw.ratio_decision_from_options(request, decision, options)
solution, _, _, chosen = raw.build_ratio_solution(request, ratio_decision, candidates)
check("ratio option decision converts to executable ratio decision", ratio_decision.supported)
check("ratio option solution averages four slot ratios", "/ 4" in solution.pandas_query)
check("ratio option selected two candidates per slot", len(chosen) == 8)

cell_candidates, cell_diag = raw.build_candidates(
    request,
    table_ids=Q955_TABLES,
    shortlist=Q955_TABLES,
    limit_per_slot=32,
    max_tables=8,
)
cell_options, cell_option_diag = raw.build_ratio_options(request, cell_candidates, max_options_per_side=6)
cell_option_decision = raw.deterministic_ratio_option_decision(request, cell_options)
check("q955 cell-only candidates cover every ratio slot", cell_diag["missing_slots"] == [])
check("q955 cell-only ratio options cover every side", cell_option_diag["missing_options"] == [])
check("q955 cell-only option selector avoids flat ratio planner", cell_option_decision.supported)

print("tất cả PASS")
