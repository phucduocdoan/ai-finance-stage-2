"""Offline tests for raw-table selection linking."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.codegen.execute import aexecute  # noqa: E402
from finance_qa.modules.solve.solvers import raw_selection_linker as raw_sel  # noqa: E402
from finance_qa.modules.solve.solvers import raw_table_linker as raw  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


FRAMES = {
    "NVL_financial_statements_2021_consolidated|40": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí xây dựng cơ bản dở dang"],
        "Số cuối nămTriệu đồng": [10000.0],
    }),
    "NVL_financial_statements_2022_consolidated|40": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí xây dựng cơ bản dở dang"],
        "Số cuối nămTriệu đồng": [25000.0],
    }),
    "NVL_financial_statements_2023_consolidated|40": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí xây dựng cơ bản dở dang"],
        "Số cuối nămTriệu đồng": [7000.0],
    }),
    "VCB_financial_statements_2021_consolidated|12": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí thuế thu nhập doanh nghiệp hiện hành"],
        "Năm nayTriệu đồng": [7000000.0],
    }),
    "VCB_financial_statements_2022_consolidated|12": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí thuế thu nhập doanh nghiệp hiện hành"],
        "Năm nayTriệu đồng": [8400000.0],
    }),
    "VCB_financial_statements_2023_consolidated|12": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí thuế thu nhập doanh nghiệp hiện hành"],
        "Năm nayTriệu đồng": [6500000.0],
    }),
    "VCB_financial_statements_2024_consolidated|tax_move": pd.DataFrame({
        "Chỉ tiêu": ["Thuế TNDN hiện hành"],
        "Số dư tại 1/1/2024Triệu đồng": [1000.0],
        "Phát sinh trong năm": [5000.0],
        "Số dư tại 31/12/2024": [3000.0],
    }),
    "VCB_financial_statements_2025_consolidated|tax_move": pd.DataFrame({
        "Chỉ tiêu": ["Thuế TNDN hiện hành"],
        "Số dư tại 1/1/2025Triệu đồng": [3000.0],
        "Phát sinh trong năm": [8000.0],
        "Số dư tại 31/12/2025": [4000.0],
    }),
    "HDG_financial_statements_2021_consolidated|5": pd.DataFrame({
        "Chỉ tiêu": ["Tiền và các khoản tương đương tiền", "Chi phí lãi vay"],
        "Số cuối nămTriệu đồng": [100000.0, 200000.0],
    }),
    "HDG_financial_statements_2023_consolidated|5": pd.DataFrame({
        "Chỉ tiêu": ["Tiền và các khoản tương đương tiền", "Chi phí lãi vay"],
        "Số cuối nămTriệu đồng": [900000.0, 300000.0],
    }),
    "HDG_financial_statements_2025_consolidated|5": pd.DataFrame({
        "Chỉ tiêu": ["Tiền và các khoản tương đương tiền", "Chi phí lãi vay"],
        "Số cuối nămTriệu đồng": [400000.0, 100000.0],
    }),
    "CTG_financial_statements_2022_consolidated|82": pd.DataFrame({
        "Chỉ tiêu": [
            "Tài sản khác giữ hộ",
            "Tài sản thuê ngoài",
            "Các chứng từ có giá trị khác đang bảo quản",
        ],
        "Số cuối nămTriệu đồng": [6063559.0, 11023860.0, 88827993.0],
    }),
    "CTG_financial_statements_2023_consolidated|83": pd.DataFrame({
        "Chỉ tiêu": [
            "Kim loại quý, đá quý giữ hộ",
            "Tài sản khác giữ hộ",
            "Tài sản thuê ngoài",
            "Các chứng từ có giá trị khác đang bảo quản",
        ],
        "Số cuối nămTriệu đồng": [47734.0, 8503445.0, 11590006.0, 71514898.0],
    }),
    "CTG_financial_statements_2024_consolidated|83": pd.DataFrame({
        "Chỉ tiêu": [
            "Kim loại quý, đá quý giữ hộ",
            "Tài sản khác giữ hộ",
            "Tài sản thuê ngoài",
            "Các chứng từ có giá trị khác đang bảo quản",
        ],
        "Số cuối nămTriệu đồng": [80879.0, 10469024.0, 12129496.0, 110291470.0],
    }),
    "CTG_financial_statements_2025_consolidated|81": pd.DataFrame({
        "Chỉ tiêu": [
            "Kim loại quý, đá quý giữ hộ",
            "Tài sản khác giữ hộ",
            "Tài sản thuê ngoài",
            "Các chứng từ có giá trị khác đang bảo quản",
        ],
        "Số cuối nămTriệu đồng": [83090.0, 9014969.0, 12308133.0, 73621198.0],
    }),
}


META = {}
for table_id in FRAMES:
    ticker, _, rest = table_id.partition("_financial_statements_")
    year = int(rest[:4])
    doc_type = "consolidated" if "_consolidated" in table_id else "unknown"
    META[table_id] = {
        "ticker": ticker,
        "year": year,
        "doc_type": doc_type,
        "statement_type": "note",
        "context_page_text": "Đơn vị tính: Triệu đồng",
        "first_col_labels": FRAMES[table_id]["Chỉ tiêu"].tolist(),
    }


# Module-level, so it outlives this file: under `pytest tests/` the fakes were still
# installed when `test_table_profiles_columns.py` imported, and its NVL cell-candidate
# checks failed against these four synthetic tables. `_RAW_ORIGINALS` + the restore at
# the end of the file keep the patch scoped to this module.
_RAW_ORIGINALS = {
    name: getattr(raw, name)
    for name in ("load_frame", "meta_for", "page_text", "table_metadata")
}

raw.load_frame = lambda table_id: FRAMES[table_id]
raw.meta_for = lambda table_id: META.get(table_id, {})
raw.page_text = lambda table_id: META.get(table_id, {}).get("context_page_text", "")
raw.table_metadata = lambda: META


def _candidate_for(candidates, slot_key: str, row_text: str):
    return next(
        c for c in candidates
        if c.slot_key == slot_key and row_text in c.row_label
    )


Q_YEAR = (
    "Trong các năm 2021, 2022 và 2023, chi phí xây dựng cơ bản dở dang cuối năm "
    "của NVL cao nhất vào năm nào?"
)
state_year = {
    "question": Q_YEAR,
    "tickers": ["NVL"],
    "years": [2021, 2022, 2023],
    "doc_type": "consolidated",
    "multi_year": True,
    "multi_company": False,
}
request, axis, order, answer_kind, reason = raw_sel.build_request(state_year)
check("raw selection accepts temporal year-answer question", request is not None and not reason)
assert request is not None
check("raw selection infers year axis", axis == "year" and order == "max")
check("raw selection infers selected-year answer", answer_kind == "selected_year")
candidates, diag = raw.build_candidates(
    request,
    table_ids=list(FRAMES),
    limit_per_slot=8,
)
check("raw selection candidates cover every year", not diag["missing_slots"])
search = raw.RawSearchPlan(
    supported=True,
    row_phrases=["Chi phí xây dựng cơ bản dở dang"],
    target_unit="vnd",
)
semantic = raw.semantic_plan_from_search_plan(request, search)
semantic_decision = raw_sel.decision_from_semantic_plan(
    request,
    semantic,
    candidates,
    order="max",
    answer_kind="selected_year",
    question=Q_YEAR,
)
check("semantic bridge builds a raw selection decision", semantic_decision.supported)
year_decision = raw_sel.RawSelectionDecision(
    supported=True,
    operation="select",
    rank_op="max",
    answer_kind="selected_year",
    slots=[
        raw_sel.RawSelectionSlotDecision(
            slot_key=f"NVL:{year}",
            selector_candidate_id=_candidate_for(
                candidates, f"NVL:{year}", "Chi phí xây dựng cơ bản dở dang"
            ).id,
        )
        for year in (2021, 2022, 2023)
    ],
    target_unit="year",
)
solution, frames, names, chosen, winning_slot = raw_sel.build_solution(
    request,
    year_decision,
    candidates,
    expected_order="max",
    expected_answer_kind="selected_year",
)
check("raw selection picks the largest year", winning_slot.key == "NVL:2022")
result = asyncio.run(aexecute(solution, "", frames, question=Q_YEAR, names=names, max_repairs=0))
check("selected-year query returns the winning year", result["answer"] == 2022.0)
check("selected-year query still reads evidence", "df" in result["pandas_query"])

total_candidate = _candidate_for(
    candidates, "NVL:2021", "Chi phí xây dựng cơ bản dở dang"
).model_copy(update={
    "id": "total-nvl-2021",
    "row_label": "Tổng cộng",
    "is_total_row": True,
    "score": 0.9,
})
total_row_decision = raw_sel.RawSelectionDecision(
    supported=True,
    operation="select",
    rank_op="max",
    answer_kind="selected_year",
    slots=[
        raw_sel.RawSelectionSlotDecision(
            slot_key="NVL:2021",
            selector_candidate_id=total_candidate.id,
        ),
        *[
            raw_sel.RawSelectionSlotDecision(
                slot_key=f"NVL:{year}",
                selector_candidate_id=_candidate_for(
                    candidates, f"NVL:{year}", "Chi phí xây dựng cơ bản dở dang"
                ).id,
            )
            for year in (2022, 2023)
        ],
    ],
    target_unit="year",
)
try:
    raw_sel.build_solution(
        request,
        total_row_decision,
        [total_candidate, *candidates],
        expected_order="max",
        expected_answer_kind="selected_year",
    )
    total_without_intent_rejected = False
except raw_sel.RawSelectionError as exc:
    total_without_intent_rejected = "total row" in str(exc)
check("raw selection rejects total rows without total intent", total_without_intent_rejected)

total_request = request.model_copy(update={"wants_total": True})
try:
    raw_sel.build_solution(
        total_request,
        total_row_decision,
        [total_candidate, *candidates],
        expected_order="max",
        expected_answer_kind="selected_year",
        allow_total_row_selector=False,
    )
    semantic_component_total_rejected = False
except raw_sel.RawSelectionError as exc:
    semantic_component_total_rejected = "total row" in str(exc)
check("raw selection rejects total rows when semantic plan wants components", semantic_component_total_rejected)

flow_question = "Thuế TNDN hiện hành phải nộp trong năm 2024 là bao nhiêu?"
flow_request = raw.RawLinkRequest(
    operation="select",
    slots=[raw.RawScopeSlot(ticker="VCB", year=2024)],
    doc_type="consolidated",
    period="annual",
    target_unit="million_vnd",
    query_norm=raw._norm(flow_question),
    query_tokens=raw._tokens(flow_question),
)
flow_candidates, _ = raw.build_candidates(
    flow_request,
    table_ids=["VCB_financial_statements_2024_consolidated|tax_move"],
    limit_per_slot=4,
)
check("in-year payable questions prefer flow columns", flow_candidates[0].column == "Phát sinh trong năm")
flow_selection_question = (
    "Trong các năm 2024 và 2025, thuế TNDN hiện hành phải nộp trong năm "
    "cao nhất là bao nhiêu tỷ đồng?"
)
flow_selection_request = raw.RawLinkRequest(
    operation="select",
    slots=[raw.RawScopeSlot(ticker="VCB", year=2024), raw.RawScopeSlot(ticker="VCB", year=2025)],
    doc_type="consolidated",
    period="annual",
    target_unit="billion_vnd",
    query_norm=raw._norm(flow_selection_question),
    query_tokens=raw._tokens(flow_selection_question),
)
flow_selection_candidates, _ = raw.build_candidates(
    flow_selection_request,
    table_ids=[
        "VCB_financial_statements_2024_consolidated|tax_move",
        "VCB_financial_statements_2025_consolidated|tax_move",
    ],
    limit_per_slot=4,
)
flow_decision = raw_sel.decision_from_flow_top_candidates(
    flow_selection_request,
    flow_selection_candidates,
    order="max",
    answer_kind="answer_value",
    question=flow_selection_question,
    target_unit="billion_vnd",
)
check("flow top candidates produce deterministic selection", flow_decision.supported)
solution, frames, names, chosen, winning_slot = raw_sel.build_solution(
    flow_selection_request,
    flow_decision,
    flow_selection_candidates,
    expected_order="max",
    expected_answer_kind="answer_value",
)
check("flow top selection picks the largest flow year", winning_slot.key == "VCB:2025")
result = asyncio.run(aexecute(solution, "", frames, question=flow_selection_question, names=names, max_repairs=0))
check("flow top selection scales selected value", result["answer"] == 8.0)


Q_GROUP_YEAR = (
    "Trong các năm 2022, 2023, 2024, 2025, giá trị tài sản giữ hộ/bảo quản "
    "của CTG cao nhất vào năm nào?"
)
state_group_year = {
    "question": Q_GROUP_YEAR,
    "tickers": ["CTG"],
    "years": [2022, 2023, 2024, 2025],
    "doc_type": "consolidated",
    "multi_year": True,
    "multi_company": False,
}
group_request, axis, order, answer_kind, reason = raw_sel.build_request(state_group_year)
check("raw selection accepts component-row temporal question", group_request is not None and not reason)
assert group_request is not None
group_candidates, group_cand_diag = raw.build_candidates(
    group_request,
    table_ids=list(FRAMES),
    limit_per_slot=12,
)
check("component-row candidates cover every year", not group_cand_diag["missing_slots"])
group_search = raw.RawSearchPlan(
    supported=True,
    row_phrases=[
        "Kim loại quý, đá quý giữ hộ",
        "Tài sản khác giữ hộ",
        "Tài sản thuê ngoài",
        "Các chứng từ có giá trị khác đang bảo quản",
    ],
    prefer_total_row=False,
    requires_component_sum=True,
    target_unit="million_vnd",
)
no_group_search = raw.RawSearchPlan(
    supported=True,
    row_phrases=[
        "Thuế TNDN hiện hành",
        "Chi phí thuế TNDN hiện hành",
        "Chi phí thuế thu nhập doanh nghiệp hiện hành",
    ],
    prefer_total_row=False,
    requires_component_sum=False,
    target_unit="million_vnd",
    reason="phrases are metric synonyms",
)
synonym_rows_reason_search = no_group_search.model_copy(update={
    "reason": "Các snippets cung cấp rõ ràng các dòng Thuế TNDN hiện hành cho từng năm.",
})
no_row_groups, no_row_group_diag = raw_sel._row_phrase_group_candidates(
    group_request,
    no_group_search,
    group_candidates,
)
check("row-phrase groups require component-sum intent", not no_row_groups and "component sum" in no_row_group_diag["reason"])
synonym_reason_groups, synonym_reason_diag = raw_sel._row_phrase_group_candidates(
    group_request,
    synonym_rows_reason_search,
    group_candidates,
)
check(
    "mentioning rows in reason does not imply component sum",
    not synonym_reason_groups and "component sum" in synonym_reason_diag["reason"],
)
identity_include_search = no_group_search.model_copy(update={
    "include_phrases": ["Ngân hàng TMCP Công Thương Việt Nam", "2022", "2023"],
})
identity_row_groups, identity_row_group_diag = raw_sel._row_phrase_group_candidates(
    group_request,
    identity_include_search,
    group_candidates,
)
check(
    "identity include phrases do not trigger component-row groups",
    not identity_row_groups and "component sum" in identity_row_group_diag["reason"],
)
header_include_search = no_group_search.model_copy(update={
    "row_phrases": ["Nhà xưởng"],
    "context_phrases": ["Bất động sản đầu tư"],
    "include_phrases": [
        "Bất động sản đầu tư",
        "Nhà xưởng",
        "Giá trị còn lại",
        "Số cuối năm",
        "Số đầu năm",
        "Nguyên giá",
        "Giá trị hao mòn lũy kế",
    ],
})
header_row_groups, header_row_group_diag = raw_sel._row_phrase_group_candidates(
    group_request,
    header_include_search,
    group_candidates,
)
check(
    "header include phrases do not trigger component-row groups",
    not header_row_groups and "component sum" in header_row_group_diag["reason"],
)
row_groups, row_group_diag = raw_sel._row_phrase_group_candidates(
    group_request,
    group_search,
    group_candidates,
)
check("row-phrase group candidates cover every year", row_group_diag["groups_per_slot"] == {
    "CTG:2022": 1,
    "CTG:2023": 1,
    "CTG:2024": 1,
    "CTG:2025": 1,
})
group_auto_decision = raw_sel.decision_from_row_groups(
    group_request,
    row_groups,
    order="max",
    answer_kind="selected_year",
    question=Q_GROUP_YEAR,
    target_unit="year",
)
check("row-phrase groups produce deterministic decision", group_auto_decision.supported)
solution, frames, names, chosen, winning_slot = raw_sel.build_solution(
    group_request,
    group_auto_decision,
    [*group_candidates, *row_groups],
    expected_order="max",
    expected_answer_kind="selected_year",
    allow_total_row_selector=False,
)
check("component-row group selection picks the largest year", winning_slot.key == "CTG:2024")
result = asyncio.run(aexecute(solution, "", frames, question=Q_GROUP_YEAR, names=names, max_repairs=0))
check("component-row group selected-year query executes", result["answer"] == 2024.0)
check("component-row group query sums real cells", " + " in result["pandas_query"])
# The year has to come out of the comparison, not out of a constant added to a cell
# that was multiplied by zero. `* 0 + 2024` also re-executes to 2024, which is how
# that shape survived; what it cannot do is answer a different year when the cells
# say so, and that is what the second check below pins.
check("selected-year query carries every year, not just the winner", all(
    f", {year})" in solution.pandas_query for year in (2022, 2023, 2024, 2025)
))
check("selected-year query annihilates nothing", "* 0" not in solution.pandas_query)
var_2022 = next(var for var, table_id in names.items() if "_2022_" in table_id)
bumped = dict(frames)
bumped[var_2022] = frames[var_2022].assign(
    **{"Số cuối nămTriệu đồng": frames[var_2022]["Số cuối nămTriệu đồng"] * 1e6}
)
check(
    "raising the 2022 cells moves the answer to 2022",
    raw_sel.run_query(solution.pandas_query, bumped) == 2022,
)
# The safety property the caller relies on: `year_selection_query` returns None
# rather than a query that lands somewhere other than where the ranking did, and
# the caller then keeps the old shape. Without this the rewrite could move an
# answer, which is the one thing it must never do.
check(
    "a rewrite landing on the wrong year is refused",
    raw_sel.year_selection_query(
        [(0.0, SimpleNamespace(year=2022), c, None) for c in chosen[:1]]
        + [(0.0, SimpleNamespace(year=2023), c, None) for c in chosen[1:2]],
        {t: v for v, t in names.items()},
        group_request.value_transform,
        "max",
        frames,
        winning_year=1999,
    )
    is None,
)

distractor_candidates = [
    raw.RawCellCandidate(
        id="d-ctg-2025-1",
        slot_key="CTG:2025",
        ticker="CTG",
        year=2025,
        table_id="CTG_financial_statements_2025_consolidated|distractor",
        row_position=0,
        column="Số cuối nămTriệu đồng",
        value=300000000.0,
        source_unit="million_vnd",
        # A real phrase hit, so the distractor table clears the three-component floor
        # on its own merits. `Động sản` used to stand here and matched `Tài sản thuê
        # ngoài` at a perfect 1.0, because a one-token row divided by its own length.
        row_label="Các chứng từ có giá trị khác",
        row_score=0.62,
        table_score=0.5,
        column_score=0.5,
        score=0.62,
    ),
    raw.RawCellCandidate(
        id="d-ctg-2025-2",
        slot_key="CTG:2025",
        ticker="CTG",
        year=2025,
        table_id="CTG_financial_statements_2025_consolidated|distractor",
        row_position=1,
        column="Số cuối nămTriệu đồng",
        value=400000000.0,
        source_unit="million_vnd",
        row_label="Tài sản khác",
        row_score=0.62,
        table_score=0.5,
        column_score=0.5,
        score=0.62,
    ),
    raw.RawCellCandidate(
        id="d-ctg-2025-3",
        slot_key="CTG:2025",
        ticker="CTG",
        year=2025,
        table_id="CTG_financial_statements_2025_consolidated|distractor",
        row_position=2,
        column="Số cuối nămTriệu đồng",
        value=500000000.0,
        source_unit="million_vnd",
        row_label="Tiền gửi, vàng, đá quý, kim loại quý, chứng từ có giá",
        row_score=0.62,
        table_score=0.5,
        column_score=0.5,
        score=0.62,
    ),
]
excluded_group_search = group_search.model_copy(update={"exclude_phrases": ["Tiền gửi"]})
groups_with_distractor, _ = raw_sel._row_phrase_group_candidates(
    group_request,
    excluded_group_search,
    [*group_candidates, *distractor_candidates],
)
correct_2025 = next(
    group for group in groups_with_distractor
    if group.slot_key == "CTG:2025" and "giữ hộ" in group.label and "Tiền gửi" not in group.label
)
distractor_2025 = next(
    group for group in groups_with_distractor
    if group.slot_key == "CTG:2025" and "Tiền gửi" in group.label
)
check(
    "exclude phrases lower component-row distractor groups",
    correct_2025.score - distractor_2025.score >= 0.04,
)
distractor_decision = raw_sel.decision_from_row_groups(
    group_request,
    groups_with_distractor,
    order="max",
    answer_kind="selected_year",
    question=Q_GROUP_YEAR,
    target_unit="year",
)
check("row-phrase groups stay deterministic with excluded distractor", distractor_decision.supported)

saved_search = raw.aplan_raw_search
saved_group_builder = raw_sel._row_phrase_group_candidates
saved_selection_planner = raw_sel.aplan_raw_selection
planner_called = []


async def fake_component_search(**kwargs):
    return group_search.model_copy(update={"requires_component_sum": True})


def fake_empty_groups(*args, **kwargs):
    return [], {"group_candidate_count": 0, "groups_per_slot": {}, "reason": "forced empty groups"}


async def fake_selection_planner(**kwargs):
    planner_called.append(True)
    return raw_sel.RawSelectionDecision(
        supported=False,
        operation="select",
        rank_op="max",
        answer_kind="selected_year",
        reason="planner should not be called",
    )


try:
    raw.aplan_raw_search = fake_component_search
    raw_sel._row_phrase_group_candidates = fake_empty_groups
    raw_sel.aplan_raw_selection = fake_selection_planner
    try:
        asyncio.run(raw_sel.aprepare_raw_selection_linker(state_group_year))
        component_fail_closed = False
    except raw_sel.RawSelectionError as exc:
        component_fail_closed = "row groups" in str(exc)
finally:
    raw.aplan_raw_search = saved_search
    raw_sel._row_phrase_group_candidates = saved_group_builder
    raw_sel.aplan_raw_selection = saved_selection_planner
check("component-sum raw selection fails closed before selection planner", component_fail_closed and not planner_called)


Q_VALUE = (
    "Trong các năm 2021, 2022 và 2023, chi phí thuế thu nhập doanh nghiệp hiện "
    "hành của VCB cao nhất vào năm nào và bằng bao nhiêu tỷ đồng?"
)
state_value = {
    "question": Q_VALUE,
    "tickers": ["VCB"],
    "years": [2021, 2022, 2023],
    "doc_type": "consolidated",
    "multi_year": True,
    "multi_company": False,
    "unit_hint": "tỷ đồng",
}
request, axis, order, answer_kind, reason = raw_sel.build_request(state_value)
check("raw selection accepts selected-value question", request is not None and not reason)
assert request is not None
check("raw selection keeps value answer when question asks money", answer_kind == "answer_value")
candidates, diag = raw.build_candidates(
    request,
    table_ids=list(FRAMES),
    limit_per_slot=8,
)
value_decision = raw_sel.RawSelectionDecision(
    supported=True,
    operation="select",
    rank_op="max",
    answer_kind="answer_value",
    slots=[
        raw_sel.RawSelectionSlotDecision(
            slot_key=f"VCB:{year}",
            selector_candidate_id=_candidate_for(
                candidates, f"VCB:{year}", "Chi phí thuế thu nhập doanh nghiệp hiện hành"
            ).id,
            answer_candidate_id=_candidate_for(
                candidates, f"VCB:{year}", "Chi phí thuế thu nhập doanh nghiệp hiện hành"
            ).id,
        )
        for year in (2021, 2022, 2023)
    ],
    target_unit="billion_vnd",
)
solution, frames, names, chosen, winning_slot = raw_sel.build_solution(
    request,
    value_decision,
    candidates,
    expected_order="max",
    expected_answer_kind="answer_value",
)
check("raw selection picks the largest value slot", winning_slot.key == "VCB:2022")
result = asyncio.run(aexecute(solution, "", frames, question=Q_VALUE, names=names, max_repairs=0))
check("selected value is scaled from million to billion", result["answer"] == 8400.0)

bridge_value = raw_sel.decision_from_semantic_plan(
    request,
    raw.semantic_plan_from_search_plan(
        request,
        raw.RawSearchPlan(
            supported=True,
            row_phrases=["Chi phí thuế thu nhập doanh nghiệp hiện hành"],
            target_unit="billion_vnd",
        ),
    ),
    candidates,
    order="max",
    answer_kind="answer_value",
    question="Ngân hàng TMCP Ngoại thương Việt Nam có mức thuế TNDN hiện hành lớn nhất là bao nhiêu tỷ đồng?",
)
check("semantic bridge does not treat Viet Nam co as selected-slot wording", bridge_value.supported)


Q_OTHER = (
    "Trong các năm 2021, 2023, 2025, tiền và các khoản tương đương tiền cuối năm "
    "của HDG lớn nhất vào năm nào? Chi phí lãi vay của năm đó là bao nhiêu tỷ đồng?"
)
state_other = {
    "question": Q_OTHER,
    "tickers": ["HDG"],
    "years": [2021, 2023, 2025],
    "doc_type": "consolidated",
    "multi_year": True,
    "multi_company": False,
    "unit_hint": "tỷ đồng",
}
request, axis, order, answer_kind, reason = raw_sel.build_request(state_other)
check("raw selection accepts different answer metric question", request is not None and not reason)
assert request is not None
candidates, diag = raw.build_candidates(
    request,
    table_ids=list(FRAMES),
    limit_per_slot=16,
)
guarded = raw_sel.decision_from_semantic_plan(
    request,
    raw.semantic_plan_from_search_plan(
        request,
        raw.RawSearchPlan(
            supported=True,
            row_phrases=["Tiền và các khoản tương đương tiền"],
            target_unit="billion_vnd",
        ),
    ),
    candidates,
    order="max",
    answer_kind="answer_value",
    question=Q_OTHER,
)
check("semantic bridge refuses answer-different-at-selected-slot questions", not guarded.supported)
other_decision = raw_sel.RawSelectionDecision(
    supported=True,
    operation="select",
    rank_op="max",
    answer_kind="answer_value",
    slots=[
        raw_sel.RawSelectionSlotDecision(
            slot_key=f"HDG:{year}",
            selector_candidate_id=_candidate_for(
                candidates, f"HDG:{year}", "Tiền và các khoản tương đương tiền"
            ).id,
            answer_candidate_id=_candidate_for(candidates, f"HDG:{year}", "Chi phí lãi vay").id,
        )
        for year in (2021, 2023, 2025)
    ],
    target_unit="billion_vnd",
)
solution, frames, names, chosen, winning_slot = raw_sel.build_solution(
    request,
    other_decision,
    candidates,
    expected_order="max",
    expected_answer_kind="answer_value",
)
check("raw selection can answer a different metric at winning slot", winning_slot.key == "HDG:2023")
result = asyncio.run(aexecute(solution, "", frames, question=Q_OTHER, names=names, max_repairs=0))
check("different answer metric is read at winning slot", result["answer"] == 300.0)


filtered, _, _, _, reason = raw_sel.build_request({
    "question": (
        "Trong các năm 2022-2024, xét các năm có tỷ lệ lợi nhuận sau thuế "
        "trên doanh thu thuần lớn hơn 10%, doanh thu thuần thấp nhất là bao nhiêu?"
    ),
    "tickers": ["CEO"],
    "years": [2022, 2023, 2024],
})
check("threshold-filter selection stays out of raw selection v1", filtered is None and "filter" in reason)

listed, _, _, _, reason = raw_sel.build_request({
    "question": (
        "Trong các năm 2015, 2016, 2018, 2019, 2020 và 2021, số dư lãi dự thu "
        "cao nhất vào năm nào?"
    ),
    "tickers": ["PLX"],
    "years": [2015, 2016, 2017, 2018, 2019, 2020, 2021],
})
assert listed is not None
check("explicit year list does not inherit expanded missing years", [slot.year for slot in listed.slots] == [2015, 2016, 2018, 2019, 2020, 2021])

for _name, _fn in _RAW_ORIGINALS.items():
    setattr(raw, _name, _fn)
