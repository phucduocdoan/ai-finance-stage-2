"""Offline tests for raw-table cell linking."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.codegen.execute import aexecute  # noqa: E402
from finance_qa.modules.solve.solvers import raw_table_linker as raw  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


# Row wording, on the three cases that used to tie. `ngắn` survives tokenising, so
# short-term and long-term are different words; bank names still leave row scoring
# because `_scoring_query_for_table` drops them per table.
check("ngắn hạn is not dài hạn", raw._tokens("Ngắn hạn") != raw._tokens("Dài hạn"))

q32_tokens = raw._tokens(
    "Số dư phải thu theo tiến độ kế hoạch hợp đồng của FPT đến ngày 31/12/2025 là bao nhiêu tỷ đồng?"
)
check(
    "a one-word row cannot tie a six-word exact hit",
    raw._token_score(q32_tokens, "Tiền")
    < raw._token_score(q32_tokens, "Phải thu theo tiến độ kế hoạch hợp đồng"),
)

q164_tokens = raw._tokens(
    "Trích khấu hao bất động sản đầu tư cho thuê của CTCP Phát triển Sunshine Homes (SSH)"
)
check(
    "an aggregated line scores below the row naming only what was asked",
    raw._token_score(q164_tokens, "Khấu hao tài sản cố định và bất động sản đầu tư")
    < raw._token_score(q164_tokens, "Trích khấu hao trong năm"),
)


FRAMES = {
    "KLB_financial_statements_2024_separate|42": pd.DataFrame({
        "Unnamed: 0": ["Chứng chỉ tiền gửi (*)", "Trái phiếu (**)", "Tổng cộng"],
        "31/12/2024": [3228106.0, 800000.0, 4028106.0],
        "31/12/2023": [3459091.0, 0.0, 3459091.0],
    }),
    "EIB_financial_statements_2024_separate|54": pd.DataFrame({
        "Unnamed: 0": [
            "Dưới 1 năm- Chứng chỉ tiền gửi bằng VND",
            "Từ 1 năm đến 5 năm- Trái phiếu bằng VND",
            "Chỉ phí phát hành giấy tờ có giá",
            "",
        ],
        "31.12.2024Triệu đồng": ["7.200.000", "3.680.000", "(15.497)", "10.864.503"],
        "31.12.2023Triệu đồng": ["2.000.000", "-", "-", "2.000.000"],
    }),
    "EIB_financial_statements_2024_separate|32": pd.DataFrame({
        "Unnamed: 0": [
            "Chứng khoán nợ",
            "Trái phiếu do các TCTD khác trong nước phát hành",
            "Chứng chỉ tiền gửi do các TCTD khác trong nước phát hành",
            "Trái phiếu Chính phủ",
        ],
        "31.12.2024Triệu đồng": ["", "7.100.029", "3.300.000", "693.518"],
        "31.12.2023Triệu đồng": ["", "1.300.000", "2.200.000", "-"],
    }),
    "FTS_financial_statements_2020|28": pd.DataFrame({
        "STT": ["4", ""],
        "Loại phải thu khó đòi phải lập dự phòng": ["Dự phòng nợ phải thu khác khó đòi", "Cộng"],
        "Số cuối năm | Số đầu năm": [50600000.0, 50600000.0],
        "Số cuối năm | Số cuối năm": [78650000.0, 78650000.0],
    }),
    "FTS_financial_statements_2021|27": pd.DataFrame({
        "STT": ["4", ""],
        "Loại phải thu khó đòi phải lập dự phòng": ["Dự phòng nợ phải thu khác khó đòi", "Cộng"],
        "Số cuối năm | Số đầu năm": [78650000.0, 78650000.0],
        "Số cuối năm | Số cuối năm": [125070000.0, 125070000.0],
    }),
    "HDB_financial_statements_2021_separate|5": pd.DataFrame({
        "Chỉ tiêu": ["Cho vay khách hàng"],
        "Số cuối năm Triệu đồng": [187884207.0],
    }),
    "HDB_financial_statements_2021_separate|33": pd.DataFrame({
        "Chỉ tiêu": ["Cho vay các tổ chức kinh tế, cá nhân trong nước"],
        "Số cuối nămTriệu đồng": [185373610.0],
    }),
    "ABB_financial_statements_2021_separate|5": pd.DataFrame({
        "Chỉ tiêu": ["Cho vay khách hàng"],
        "Số cuối năm Triệu đồng": [68173079.0],
    }),
    "ABB_financial_statements_2021_separate|32": pd.DataFrame({
        "Chỉ tiêu": ["Cho vay các tổ chức kinh tế, cá nhân trong nước"],
        "Số cuối nămTriệu đồng": [68729213.0],
    }),
    "FIT_financial_statements_2023_separate|17": pd.DataFrame({
        "Unnamed: 0": ["Tiền mặt", "Tiền gửi ngân hàng không kỳ hạn", "Cộng"],
        "Số cuối năm": [15330585.0, 450067589.0, 465398174.0],
        "Số đầu năm": [21854140.0, 2134606503.0, 2156460643.0],
    }),
    "FIT_financial_statements_2023_separate|35": pd.DataFrame({
        "Unnamed: 0": ["Số đầu năm", "Số tiền vay trong năm", "Số tiền trả trong năm", "Số dư cuối năm"],
        "Vay ngắn hạnngân hàng (*)": [208282174564.0, 2543016584121.0, -2331307464795.0, 419991293890.0],
        "Vay ngắn hạn các tổ chức khác": [39004041769.0, 0.0, -39004041769.0, 0.0],
        "Cộng": [247286216333.0, 2543016584121.0, -2370311506564.0, 419991293890.0],
    }),
    "HAG_financial_statements_2022_separate|6": pd.DataFrame({
        "TÀI SẢN": ["TỔNG CỘNG TÀI SẢN"],
        "Số cuối năm": [15071487424.0],
    }),
    "HAG_financial_statements_2022_separate|7": pd.DataFrame({
        "NGUỒN VỐN": ["8. Vay ngắn hạn", "3. Vay dài hạn"],
        "Số cuối năm": [1958725949.0, 3581600405.0],
    }),
}

META = {
    "KLB_financial_statements_2024_separate|42": {
        "ticker": "KLB",
        "year": 2024,
        "doc_type": "separate",
        "statement_type": "note",
        "note_title": "Phát hành giấy tờ có giá thông thường:",
        "context_page_text": "Đơn vị tính: Triệu đồng Việt Nam",
        "first_col_labels": ["Chứng chỉ tiền gửi (*)", "Trái phiếu (**)", "Tổng cộng"],
    },
    "EIB_financial_statements_2024_separate|54": {
        "ticker": "EIB",
        "year": 2024,
        "doc_type": "separate",
        "statement_type": "note",
        "context_page_text": "17 PHÁT HÀNH GIẤY TỜ CÓ GIÁ",
        "first_col_labels": [
            "Dưới 1 năm- Chứng chỉ tiền gửi bằng VND",
            "Từ 1 năm đến 5 năm- Trái phiếu bằng VND",
            "Chỉ phí phát hành giấy tờ có giá",
        ],
    },
    "EIB_financial_statements_2024_separate|32": {
        "ticker": "EIB",
        "year": 2024,
        "doc_type": "separate",
        "statement_type": "note",
        "context_page_text": "10 CHỨNG KHOÁN ĐẦU TƯ 10.2 Chứng khoán đầu tư giữ đến ngày đáo hạn",
        "first_col_labels": [
            "Chứng khoán nợ",
            "Trái phiếu do các TCTD khác trong nước phát hành",
            "Chứng chỉ tiền gửi do các TCTD khác trong nước phát hành",
        ],
    },
    "FTS_financial_statements_2020|28": {
        "ticker": "FTS",
        "year": 2020,
        "doc_type": "aggregated",
        "statement_type": "note",
        "header_flat": "STT | Loại phải thu khó đòi phải lập dự phòng | Số cuối năm | Số đầu năm",
        "first_col_labels": ["Dự phòng nợ phải thu khác khó đòi", "Cộng"],
    },
    "FTS_financial_statements_2021|27": {
        "ticker": "FTS",
        "year": 2021,
        "doc_type": "aggregated",
        "statement_type": "note",
        "header_flat": "STT | Loại phải thu khó đòi phải lập dự phòng | Số cuối năm | Số đầu năm",
        "first_col_labels": ["Dự phòng nợ phải thu khác khó đòi", "Cộng"],
    },
    "HDB_financial_statements_2021_separate|5": {
        "ticker": "HDB",
        "year": 2021,
        "doc_type": "separate",
        "statement_type": "balance_sheet",
        "company_name": "Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh",
        "first_col_labels": ["Cho vay khách hàng"],
    },
    "HDB_financial_statements_2021_separate|33": {
        "ticker": "HDB",
        "year": 2021,
        "doc_type": "separate",
        "statement_type": "note",
        "company_name": "Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh",
        "note_title": "Phân tích cho vay theo loại",
        "first_col_labels": ["Cho vay các tổ chức kinh tế, cá nhân trong nước"],
    },
    "ABB_financial_statements_2021_separate|5": {
        "ticker": "ABB",
        "year": 2021,
        "doc_type": "separate",
        "statement_type": "balance_sheet",
        "company_name": "Ngân hàng TMCP An Bình",
        "first_col_labels": ["Cho vay khách hàng"],
    },
    "ABB_financial_statements_2021_separate|32": {
        "ticker": "ABB",
        "year": 2021,
        "doc_type": "separate",
        "statement_type": "note",
        "company_name": "Ngân hàng TMCP An Bình",
        "note_title": "Phân tích cho vay theo loại",
        "first_col_labels": ["Cho vay các tổ chức kinh tế, cá nhân trong nước"],
    },
    "FIT_financial_statements_2023_separate|17": {
        "ticker": "FIT",
        "year": 2023,
        "doc_type": "separate",
        "statement_type": "note",
        "note_title": "Tiền và các khoản tương đương tiền",
        "header_flat": "Số cuối năm | Số đầu năm",
        "first_col_labels": ["Tiền mặt", "Tiền gửi ngân hàng không kỳ hạn", "Cộng"],
    },
    "FIT_financial_statements_2023_separate|35": {
        "ticker": "FIT",
        "year": 2023,
        "doc_type": "separate",
        "statement_type": "note",
        "header_flat": "Vay ngắn hạn ngân hàng | Vay ngắn hạn các tổ chức khác | Cộng",
        "first_col_labels": ["Số đầu năm", "Số tiền vay trong năm", "Số tiền trả trong năm", "Số dư cuối năm"],
    },
    "HAG_financial_statements_2022_separate|6": {
        "ticker": "HAG",
        "year": 2022,
        "doc_type": "separate",
        "statement_type": "balance_sheet",
        "first_col_labels": ["TỔNG CỘNG TÀI SẢN"],
    },
    "HAG_financial_statements_2022_separate|7": {
        "ticker": "HAG",
        "year": 2022,
        "doc_type": "separate",
        "statement_type": "balance_sheet",
        "first_col_labels": ["8. Vay ngắn hạn", "3. Vay dài hạn"],
    },
}


_real_loaders = (raw.load_frame, raw.meta_for, raw.page_text)
raw.load_frame = lambda table_id: FRAMES[table_id]
raw.meta_for = lambda table_id: META.get(table_id, {})
raw.page_text = lambda table_id: META.get(table_id, {}).get("context_page_text", "")


Q_DIFF = (
    "Hiệu giữa số dư trái phiếu phát hành của công ty mẹ KLB và công ty mẹ EIB "
    "cuối năm 2024 là bao nhiêu triệu đồng?"
)
state_diff = {
    "question": Q_DIFF,
    "tickers": ["KLB", "EIB"],
    "years": [2024],
    "doc_type": "separate",
    "multi_year": False,
    "multi_company": True,
    "unit_hint": "triệu đồng",
}

request, reason = raw.build_request(state_diff)
check("diff raw linker request is accepted", request is not None and not reason)
assert request is not None
check("diff preserves ticker order", [slot.key for slot in request.slots] == ["KLB:2024", "EIB:2024"])

candidates, diag = raw.build_candidates(
    request,
    table_ids=[
        "KLB_financial_statements_2024_separate|42",
        "EIB_financial_statements_2024_separate|32",
        "EIB_financial_statements_2024_separate|54",
    ],
)
check("diff candidates cover every slot", not diag["missing_slots"])
search = raw.RawSearchPlan(
    supported=True,
    row_phrases=["Trái phiếu"],
    context_phrases=["Phát hành giấy tờ có giá"],
    exclude_phrases=["Chứng khoán đầu tư", "do các TCTD khác trong nước phát hành"],
    target_unit="million_vnd",
    confidence=0.9,
)
request = raw.request_with_search_plan(request, search)
candidates, diag = raw.build_candidates(
    request,
    table_ids=[
        "KLB_financial_statements_2024_separate|42",
        "EIB_financial_statements_2024_separate|32",
        "EIB_financial_statements_2024_separate|54",
    ],
)
klb = next(c for c in candidates if c.slot_key == "KLB:2024" and "Trái phiếu" in c.row_label and c.column == "31/12/2024")
eib = next(
    c for c in candidates
    if c.slot_key == "EIB:2024"
    and c.table_id == "EIB_financial_statements_2024_separate|54"
    and "Trái phiếu" in c.row_label
)
check("candidate builder keeps row-context semantic hit", eib.value == 3680000.0)
check("candidate records unit provenance", bool(eib.source_unit_from))
plan = raw.semantic_plan_from_search_plan(request, search)
auto = raw.decision_from_semantic_plan(request, plan, candidates)
check("semantic diff selects issued-bond rows", auto.supported and auto.candidate_ids == [klb.id, eib.id])
decision = raw.RawLinkerDecision(
    supported=True,
    operation="diff",
    candidate_ids=[klb.id, eib.id],
    target_unit="million_vnd",
    confidence=0.9,
)
solution, frames, names, chosen = raw.build_solution(request, decision, candidates)
check("diff solution reads two selected tables", list(names.values()) == [klb.table_id, eib.table_id])
result = asyncio.run(aexecute(solution, "", frames, question=Q_DIFF, names=names, max_repairs=0))
check("diff executes as first slot minus second", result["answer"] == -2880000.0)
check("diff query remains executable pandas", "df1.iloc" in result["pandas_query"] and "df2.iloc" in result["pandas_query"])


Q_DOMESTIC_DIFF = (
    "Tính chênh lệch quy mô dư nợ cho vay khách hàng nội địa của công ty mẹ HDB "
    "so với công ty mẹ ABB vào năm 2021 theo đơn vị triệu đồng."
)
state_domestic = {
    "question": Q_DOMESTIC_DIFF,
    "tickers": ["HDB", "ABB"],
    "years": [2021],
    "doc_type": "separate",
    "multi_year": False,
    "multi_company": True,
    "unit_hint": "triệu đồng",
}
request, reason = raw.build_request(state_domestic)
check("domestic diff raw linker request is accepted", request is not None and request.operation == "diff")
assert request is not None
candidates, diag = raw.build_candidates(
    request,
    table_ids=[
        "HDB_financial_statements_2021_separate|5",
        "ABB_financial_statements_2021_separate|5",
        "HDB_financial_statements_2021_separate|33",
        "ABB_financial_statements_2021_separate|32",
    ],
)
check("domestic diff candidates cover every slot", not diag["missing_slots"])
check("domestic detail does not auto-select a broad same-label total", not raw.deterministic_decision(request, candidates).supported)
search = raw.RawSearchPlan(
    supported=True,
    row_phrases=["Cho vay các tổ chức kinh tế, cá nhân trong nước"],
    target_unit="million_vnd",
    confidence=0.9,
)
request = raw.request_with_search_plan(request, search)
candidates, diag = raw.build_candidates(
    request,
    table_ids=[
        "HDB_financial_statements_2021_separate|5",
        "ABB_financial_statements_2021_separate|5",
        "HDB_financial_statements_2021_separate|33",
        "ABB_financial_statements_2021_separate|32",
    ],
)
plan = raw.semantic_plan_from_search_plan(request, search)
auto = raw.decision_from_semantic_plan(request, plan, candidates)
check("semantic domestic diff selects trong nước note rows", auto.supported)
solution, frames, names, chosen = raw.build_solution(request, auto, candidates)
check("domestic diff avoids balance-sheet total rows", all("trong nước" in c.row_label for c in chosen))
result = asyncio.run(aexecute(solution, "", frames, question=Q_DOMESTIC_DIFF, names=names, max_repairs=0))
check("domestic diff executes detail-note subtraction", result["answer"] == 116644397.0)


Q_AVG = (
    "Giá trị trung bình của tổng số dư dự phòng phải thu khó đòi cuối kỳ của FTS "
    "tại các mốc cuối năm 2020 và 2021 là bao nhiêu triệu đồng?"
)
state_avg = {
    "question": Q_AVG,
    "tickers": ["FTS"],
    "years": [2020, 2021],
    "doc_type": "unknown",
    "multi_year": True,
    "multi_company": False,
    "unit_hint": "triệu đồng",
}

request, reason = raw.build_request(state_avg)
check("avg raw linker request is accepted", request is not None and request.operation == "avg")
assert request is not None
candidates, diag = raw.build_candidates(
    request,
    table_ids=["FTS_financial_statements_2020|28", "FTS_financial_statements_2021|27"],
)
check("avg candidates cover every year", not diag["missing_slots"])
totals = [
    next(
        c for c in candidates
        if c.slot_key == f"FTS:{year}" and c.is_total_row and c.column == "Số cuối năm | Số cuối năm"
    )
    for year in (2020, 2021)
]
check("total-row candidates outrank component candidates when question asks total", all(c.score > 0.5 for c in totals))
auto = raw.deterministic_decision(request, candidates)
check("deterministic avg selects one total row per year", auto.supported and auto.candidate_ids == [c.id for c in totals])
decision = raw.RawLinkerDecision(
    supported=True,
    operation="avg",
    candidate_ids=[candidate.id for candidate in totals],
    target_unit="million_vnd",
    confidence=0.91,
)
solution, frames, names, _ = raw.build_solution(request, decision, candidates)
result = asyncio.run(aexecute(solution, "", frames, question=Q_AVG, names=names, max_repairs=0))
check("avg executes and scales undeclared VND to million VND", abs(result["answer"] - 101.86) < 1e-9)

filtered, reason = raw.build_request({
    **state_avg,
    "question": "Năm 2016, trong số các công ty AAA, DCM và DPM có tỷ lệ lợi nhuận lớn hơn 10%, tổng doanh thu thuần là bao nhiêu?",
    "tickers": ["AAA", "DCM", "DPM"],
    "years": [2016],
})
check("conditional-filter questions stay out of raw linker phase 1", filtered is None and "outside" in reason)

ratio_direct, reason = raw.build_request({
    "question": "Tổng vay ngắn hạn gấp tổng tiền mặt và tiền gửi ngân hàng của công ty mẹ FIT cuối năm 2023 bao nhiêu lần?",
    "tickers": ["FIT"],
    "years": [2023],
    "doc_type": "separate",
    "multi_year": False,
    "multi_company": False,
    "unit_hint": "lần",
})
check("single-slot ratio request is accepted as component ratio", ratio_direct is not None and ratio_direct.operation == "ratio")
assert ratio_direct is not None
ratio_candidates, ratio_diag = raw.build_candidates(
    ratio_direct,
    table_ids=["FIT_financial_statements_2023_separate|35", "FIT_financial_statements_2023_separate|17"],
    limit_per_slot=32,
)
check("ratio candidates keep closing-balance period rows", any(c.row_label == "Số dư cuối năm" for c in ratio_candidates))
fit_num = next(
    c for c in ratio_candidates
    if c.table_id == "FIT_financial_statements_2023_separate|35"
    and c.row_label == "Số dư cuối năm"
    and c.column == "Cộng"
)
fit_den = next(
    c for c in ratio_candidates
    if c.table_id == "FIT_financial_statements_2023_separate|17"
    and c.row_label == "Cộng"
    and c.column == "Số cuối năm"
)
ratio_solution, ratio_frames, ratio_names, ratio_chosen = raw.build_ratio_solution(
    ratio_direct,
    raw.RawRatioDecision(
        supported=True,
        operation="ratio",
        slots=[
            raw.RawRatioSlotDecision(
                slot_key="FIT:2023",
                numerator_candidate_ids=[fit_num.id],
                denominator_candidate_ids=[fit_den.id],
            ),
        ],
        target_unit="ratio",
    ),
    ratio_candidates,
)
check("ratio solution chooses numerator and denominator cells", ratio_chosen == [fit_num, fit_den])
ratio_result = asyncio.run(aexecute(ratio_solution, "", ratio_frames, question=ratio_direct.query_norm, names=ratio_names, max_repairs=0))
check("single-slot ratio executes without percent scaling", abs(ratio_result["answer"] - (fit_num.value / fit_den.value)) < 1e-9)
try:
    raw.validate_ratio_decision(
        ratio_direct,
        raw.RawRatioDecision(
            supported=True,
            operation="ratio",
            slots=[
                raw.RawRatioSlotDecision(
                    slot_key="FIT:2023",
                    numerator_candidate_ids=[fit_num.id],
                    denominator_candidate_ids=[
                        c.id for c in ratio_candidates
                        if c.table_id == "FIT_financial_statements_2023_separate|17"
                        and c.column == "Số cuối năm"
                    ],
                ),
            ],
            target_unit="ratio",
        ),
        ratio_candidates,
    )
except raw.RawTableLinkError as exc:
    check("ratio side cannot mix total row with its components", "mixes a total row" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("ratio side cannot mix total row with its components")

multi_component_request = raw.RawLinkRequest(
    operation="ratio",
    slots=[raw.RawScopeSlot(ticker="HAG", year=2022)],
    target_unit="percent",
)
multi_component_candidates = [
    raw.RawCellCandidate(
        id="c1",
        slot_key="HAG:2022",
        table_id="HAG_financial_statements_2022_separate|7",
        ticker="HAG",
        year=2022,
        row_position=0,
        row_label="8. Vay ngắn hạn",
        column="Số cuối năm",
        value=1958725949.0,
        source_unit="unknown",
        score=0.9,
    ),
    raw.RawCellCandidate(
        id="c2",
        slot_key="HAG:2022",
        table_id="HAG_financial_statements_2022_separate|7",
        ticker="HAG",
        year=2022,
        row_position=1,
        row_label="3. Vay dài hạn",
        column="Số cuối năm",
        value=3581600405.0,
        source_unit="unknown",
        score=0.9,
    ),
    raw.RawCellCandidate(
        id="c3",
        slot_key="HAG:2022",
        table_id="HAG_financial_statements_2022_separate|6",
        ticker="HAG",
        year=2022,
        row_position=0,
        row_label="TỔNG CỘNG TÀI SẢN",
        column="Số cuối năm",
        value=15071487424.0,
        source_unit="unknown",
        score=0.9,
    ),
]
multi_solution, multi_frames, multi_names, _ = raw.build_ratio_solution(
    multi_component_request,
    raw.RawRatioDecision(
        supported=True,
        operation="ratio",
        slots=[
            raw.RawRatioSlotDecision(
                slot_key="HAG:2022",
                numerator_candidate_ids=["c1", "c2"],
                denominator_candidate_ids=["c3"],
            ),
        ],
        target_unit="percent",
    ),
    multi_component_candidates,
)
multi_result = asyncio.run(aexecute(multi_solution, "", multi_frames, question="ratio", names=multi_names, max_repairs=0))
expected_multi = (multi_component_candidates[0].value + multi_component_candidates[1].value) / multi_component_candidates[2].value * 100
check("multi-component ratio executes with percent scaling", abs(multi_result["answer"] - expected_multi) < 1e-9)

single_slot_sum, reason = raw.build_request({
    "question": "Tổng số tiền khách hàng trả trước ngắn hạn của SJG cuối năm 2019 là bao nhiêu nghìn tỷ đồng?",
    "tickers": ["SJG"],
    "years": [2019],
    "doc_type": "separate",
    "multi_year": False,
    "multi_company": False,
    "unit_hint": "nghìn tỷ đồng",
})
check("single-slot sum wording falls back instead of reading a generic total row", single_slot_sum is None and "single-slot" in reason)

low_direct_request = raw.RawLinkRequest(
    operation="direct",
    slots=[raw.RawScopeSlot(ticker="FTS", year=2020)],
    target_unit="trillion_vnd",
)
low_direct_candidate = raw.RawCellCandidate(
    id="c1",
    slot_key="FTS:2020",
    table_id="FTS_financial_statements_2020|11",
    ticker="FTS",
    year=2020,
    row_position=17,
    row_label="D. VỐN CHỦ SỞ HỮU (400 = 410 + 420)",
    column="Số cuối năm",
    value=2202166223231.0,
    source_unit="unknown",
    score=0.54,
)
try:
    raw.build_solution(
        low_direct_request,
        raw.RawLinkerDecision(
            supported=True,
            operation="direct",
            candidate_ids=["c1"],
            target_unit="trillion_vnd",
        ),
        [low_direct_candidate],
    )
except raw.RawTableLinkError as exc:
    check("low-evidence direct planner candidate fails closed", "direct candidate evidence" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("low-evidence direct planner candidate fails closed")

zero_candidate = low_direct_candidate.model_copy(update={"score": 0.9, "value": 0.0})
try:
    raw.build_solution(
        low_direct_request,
        raw.RawLinkerDecision(
            supported=True,
            operation="direct",
            candidate_ids=["c1"],
            target_unit="trillion_vnd",
        ),
        [zero_candidate],
    )
except raw.RawTableLinkError as exc:
    check("zero-valued raw candidate fails closed", "zero" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("zero-valued raw candidate fails closed")

percent_request = raw.RawLinkRequest(
    operation="direct",
    slots=[raw.RawScopeSlot(ticker="MSN", year=2022)],
    target_unit="percent",
)
percent_candidate = raw.RawCellCandidate(
    id="c1",
    slot_key="MSN:2022",
    table_id="MSN_financial_statements_2022_consolidated|23",
    ticker="MSN",
    year=2022,
    row_position=1,
    row_label="Tỷ lệ sở hữu",
    column="2022",
    value=48.4,
    source_unit="percent",
    score=0.9,
)
chosen = raw.validate_decision(
    percent_request,
    raw.RawLinkerDecision(
        supported=True,
        operation="direct",
        candidate_ids=["c1"],
        target_unit="percent",
    ),
    [percent_candidate],
)
check("direct percent cell can answer a percent target", chosen == [percent_candidate])

avg_money_percent_request = raw.RawLinkRequest(
    operation="avg",
    slots=[
        raw.RawScopeSlot(ticker="ACB", year=2019),
        raw.RawScopeSlot(ticker="MBB", year=2019),
    ],
    target_unit="percent",
)
avg_money_candidates = [
    raw.RawCellCandidate(
        id="c1",
        slot_key="ACB:2019",
        table_id="ACB_financial_statements_2019_separate|27",
        ticker="ACB",
        year=2019,
        row_position=1,
        row_label="Ngắn hạn",
        column="31.12.2019Triệu VND",
        value=143115446.0,
        source_unit="million_vnd",
        score=0.9,
    ),
    raw.RawCellCandidate(
        id="c2",
        slot_key="MBB:2019",
        table_id="MBB_financial_statements_2019_separate|7",
        ticker="MBB",
        year=2019,
        row_position=1,
        row_label="Tổng cộng",
        column="31/12/2019triệu đồng",
        value=289158718.0,
        source_unit="million_vnd",
        score=0.9,
    ),
]
try:
    raw.validate_decision(
        avg_money_percent_request,
        raw.RawLinkerDecision(
            supported=True,
            operation="avg",
            candidate_ids=["c1", "c2"],
            target_unit="percent",
        ),
        avg_money_candidates,
    )
except raw.RawTableLinkError as exc:
    check("avg over money cells cannot answer a percent target", "ratio/percent target" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("avg over money cells cannot answer a percent target")

try:
    raw.validate_decision(
        raw.RawLinkRequest(
            operation="direct",
            slots=[raw.RawScopeSlot(ticker="MSN", year=2022)],
            target_unit="million_vnd",
        ),
        raw.RawLinkerDecision(
            supported=True,
            operation="direct",
            candidate_ids=["c1"],
            target_unit="million_vnd",
        ),
        [percent_candidate],
    )
except raw.RawTableLinkError as exc:
    check("money target cannot be answered by a percent cell", "money target" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("money target cannot be answered by a percent cell")

normalized_same_row_request = raw.RawLinkRequest(
    operation="sum",
    slots=[
        raw.RawScopeSlot(ticker="VGT", year=2016),
        raw.RawScopeSlot(ticker="VGT", year=2024),
    ],
    target_unit="hundred_billion_vnd",
)
normalized_same_row_candidates = [
    raw.RawCellCandidate(
        id="c1",
        slot_key="VGT:2016",
        table_id="VGT_financial_statements_2016_separate|1",
        ticker="VGT",
        year=2016,
        row_position=1,
        row_label="Cổ tức",
        column="2016VND",
        value=333469304204.0,
        source_unit="unknown",
        score=0.52,
    ),
    raw.RawCellCandidate(
        id="c2",
        slot_key="VGT:2024",
        table_id="VGT_financial_statements_2024_separate|1",
        ticker="VGT",
        year=2024,
        row_position=1,
        row_label="Cổ tức",
        column="2024VND",
        value=374746516545.0,
        source_unit="unknown",
        score=0.52,
    ),
]
normalized_same_row_decision = raw.normalize_planner_decision(
    normalized_same_row_request,
    raw.RawLinkerDecision(
        supported=False,
        operation="sum",
        candidate_ids=["c1", "c2"],
        target_unit="hundred_billion_vnd",
        reason="planner was unsure but ids are complete",
    ),
)
chosen = raw.validate_decision(
    normalized_same_row_request,
    normalized_same_row_decision,
    normalized_same_row_candidates,
)
check("normalized unsupported ids pass when row evidence is coherent", chosen == normalized_same_row_candidates)

normalized_mixed_row_request = raw.RawLinkRequest(
    operation="sum",
    slots=[
        raw.RawScopeSlot(ticker="VIF", year=2025),
        raw.RawScopeSlot(ticker="DPM", year=2025),
    ],
    target_unit="billion_vnd",
    wants_total=True,
)
normalized_mixed_row_candidates = [
    raw.RawCellCandidate(
        id="c1",
        slot_key="VIF:2025",
        table_id="VIF_financial_statements_2025_consolidated|20",
        ticker="VIF",
        year=2025,
        row_position=9,
        row_label="TỔNG CỘNG",
        column="Số cuối năm",
        value=144614855225.0,
        source_unit="vnd",
        is_total_row=True,
        score=1.0,
    ),
    raw.RawCellCandidate(
        id="c2",
        slot_key="DPM:2025",
        table_id="DPM_financial_statements_2025_consolidated|9",
        ticker="DPM",
        year=2025,
        row_position=8,
        row_label="Phần lãi trong công ty liên kết",
        column="Năm nay",
        value=3039782074.0,
        source_unit="vnd",
        score=0.39,
    ),
]
normalized_mixed_row_decision = raw.normalize_planner_decision(
    normalized_mixed_row_request,
    raw.RawLinkerDecision(
        supported=False,
        operation="sum",
        candidate_ids=["c1", "c2"],
        target_unit="billion_vnd",
        reason="candidate ids are complete but rows describe different facts",
    ),
)
try:
    raw.validate_decision(
        normalized_mixed_row_request,
        normalized_mixed_row_decision,
        normalized_mixed_row_candidates,
    )
except raw.RawTableLinkError as exc:
    check("normalized unsupported ids fail when row evidence is incoherent", "coherent row evidence" in str(exc))
else:  # pragma: no cover - the check above should always raise
    raise AssertionError("normalized unsupported ids fail when row evidence is incoherent")


# A note whose value rows are labelled by period only: the metric lives in the
# section header rows above them, and the same leaf label repeats three times.
KBC_NOTE = "KBC_financial_statements_2019_consolidated|25"
FRAMES[KBC_NOTE] = pd.DataFrame({
    "Unnamed: 0": [
        "Nhà xưởng (bao gồm chi phí phát triển đất và cơ sở hạ tầng)",
        "Nguyên giá:",
        "Số đầu năm",
        "Số cuối năm",
        "Giá trị hao mòn lũy kế:",
        "Số đầu năm",
        "Số cuối năm",
        "Giá trị còn lại:",
        "Số đầu năm",
        "Số cuối năm",
    ],
    "VND": [
        None, None, 173618450871.0, 476439458160.0,
        None, 38733838508.0, 43720836237.0,
        None, 134884612363.0, 432718621923.0,
    ],
})
META[KBC_NOTE] = {
    "ticker": "KBC",
    "year": 2019,
    "doc_type": "consolidated",
    "statement_type": "note",
    "note_title": "Bất động sản đầu tư",
    "first_col_labels": ["Nguyên giá:", "Giá trị hao mòn lũy kế:", "Giá trị còn lại:"],
}

Q_CARRYING = (
    "Trong các năm 2015, 2017 và 2019, giá trị còn lại cuối năm của bất động sản "
    "đầu tư (nhà xưởng) của Tổng Công ty Phát triển Đô thị Kinh Bắc "
    "(KBC, báo cáo hợp nhất) cao nhất vào năm nào?"
)
check(
    "company legal form is not read as a request for a total",
    not raw._wants_total(Q_CARRYING),
)
check(
    "a real total question still wants a total row",
    raw._wants_total("Tổng giá trị hàng tồn kho cuối năm 2024 của HPG là bao nhiêu?"),
)

carrying_request = raw.RawLinkRequest(
    operation="select",
    slots=[raw.RawScopeSlot(ticker="KBC", year=2019)],
    doc_type="consolidated",
    period="current",
    target_unit="vnd",
    query_norm=raw._norm(Q_CARRYING),
    query_tokens=raw._tokens(Q_CARRYING),
    wants_total=raw._wants_total(Q_CARRYING),
)
carrying_candidates, carrying_diag = raw.build_candidates(
    carrying_request,
    table_ids=[KBC_NOTE],
    limit_per_slot=32,
)
check("period-only note rows reach the candidate surface", not carrying_diag["missing_slots"])
carrying = next(
    c for c in carrying_candidates
    if c.row_position == 9 and c.column == "VND"
)
check("period-only row carries its section ancestors", carrying.row_path == [
    "Nhà xưởng (bao gồm chi phí phát triển đất và cơ sở hạ tầng)",
    "Giá trị còn lại:",
])
check("carrying-value cell keeps its physical value", carrying.value == 432718621923.0)
check("row path is what the metric is scored on", carrying_candidates[0].id == carrying.id)
cost_end = next(c for c in carrying_candidates if c.row_position == 3 and c.column == "VND")
check("a same-leaf row in another section scores lower", cost_end.score < carrying.score)
carrying_start = next(c for c in carrying_candidates if c.row_position == 8 and c.column == "VND")
check(
    "period intent separates the two identical leaves of one section",
    carrying_start.row_score < carrying.row_score,
)
check(
    "section header rows never become candidates",
    all(c.row_position not in {0, 1, 4, 7} for c in carrying_candidates),
)

# A table read with a numeric column as its label column: those rows name no
# metric, so they must not inherit the wording of the section above them.
NUMERIC_LABEL_NOTE = "SSI_financial_statements_2019_separate|76"
FRAMES[NUMERIC_LABEL_NOTE] = pd.DataFrame({
    "Unnamed: 0": [
        "Giá trị hợp lý của tài sản tài chính FVTPL",
        "172.712.731.397",
        "26.089.965.620",
    ],
    "Số dư chênh lệch đánh giá lại cuối năm": [None, 276147000000.0, -13110600000.0],
})
META[NUMERIC_LABEL_NOTE] = {
    "ticker": "SSI",
    "year": 2019,
    "doc_type": "separate",
    "statement_type": "note",
    "note_title": "Tài sản tài chính",
}
numeric_label_request = raw.RawLinkRequest(
    operation="direct",
    slots=[raw.RawScopeSlot(ticker="SSI", year=2019)],
    doc_type="separate",
    period="current",
    target_unit="trillion_vnd",
    query_norm=raw._norm("giá trị hợp lý của tài sản tài chính loại FVTPL cuối năm 2019"),
    query_tokens=raw._tokens("giá trị hợp lý của tài sản tài chính loại FVTPL cuối năm 2019"),
)
numeric_label_candidates, _ = raw.build_candidates(
    numeric_label_request,
    table_ids=[NUMERIC_LABEL_NOTE],
    limit_per_slot=12,
)
check(
    "a number-labelled row inherits no section wording",
    all(not c.row_path for c in numeric_label_candidates),
)
check(
    "a number-labelled row cannot pass the direct evidence gate",
    not raw.deterministic_decision(numeric_label_request, numeric_label_candidates).supported,
)


# Column and row shape, on the four cases the score used to decide by row order.
BREAKDOWN_NOTE = "DTK_financial_statements_2024_consolidated|73"
FRAMES[BREAKDOWN_NOTE] = pd.DataFrame({
    "Unnamed: 0": ["Doanh thu", "Giá vốn"],
    "Điện": [12548788301513.0, 11000000000000.0],
    "Than": [157970986678.0, 120000000000.0],
    "Cộng": [12839301284671.0, 11300000000000.0],
    "Tỷ lệ(%)": [100.0, 88.0],
})
META[BREAKDOWN_NOTE] = {
    "ticker": "DTK",
    "year": 2024,
    "doc_type": "consolidated",
    "statement_type": "note",
    "note_title": "Báo cáo bộ phận theo lĩnh vực kinh doanh",
}
Q_BREAKDOWN = "Doanh thu của DTK năm 2024 là bao nhiêu trăm tỷ đồng?"
breakdown_request = raw.RawLinkRequest(
    operation="direct",
    slots=[raw.RawScopeSlot(ticker="DTK", year=2024)],
    doc_type="consolidated",
    period="current",
    target_unit="hundred_billion_vnd",
    query_norm=raw._norm(Q_BREAKDOWN),
    query_tokens=raw._tokens(Q_BREAKDOWN),
)
breakdown_candidates, _ = raw.build_candidates(
    breakdown_request, table_ids=[BREAKDOWN_NOTE], limit_per_slot=12
)
check(
    "a question naming no segment takes the total column",
    breakdown_candidates[0].column == "Cộng",
)
check(
    "a share-of-total column cannot answer a question asked in đồng",
    all(c.column != "Tỷ lệ(%)" for c in breakdown_candidates),
)

Q_SEGMENT = "Doanh thu từ điện của DTK năm 2024 là bao nhiêu trăm tỷ đồng?"
segment_candidates, _ = raw.build_candidates(
    breakdown_request.model_copy(update={
        "query_norm": raw._norm(Q_SEGMENT), "query_tokens": raw._tokens(Q_SEGMENT),
    }),
    table_ids=[BREAKDOWN_NOTE],
    limit_per_slot=12,
)
check(
    "naming a segment keeps the total column from taking the bonus",
    next(c for c in segment_candidates if c.column == "Điện").column_score
    == next(c for c in segment_candidates if c.column == "Cộng").column_score,
)

PREPAID_NOTE = "IJC_financial_statements_2016_consolidated|17"
FRAMES[PREPAID_NOTE] = pd.DataFrame({
    "Unnamed: 0": ["Trả trước cho các bên liên quan", "- Trả trước tiền thuê đất", "Cộng"],
    "Số cuối năm": [19619115288.0, 5576335963.0, 25195451251.0],
})
META[PREPAID_NOTE] = {
    "ticker": "IJC",
    "year": 2016,
    "doc_type": "consolidated",
    "statement_type": "note",
    "note_title": "Trả trước cho người bán ngắn hạn",
}
Q_PREPAID = "Số tiền trả trước cho người bán ngắn hạn của IJC đến ngày 31/12/2016 là bao nhiêu tỷ đồng?"
prepaid_candidates, _ = raw.build_candidates(
    raw.RawLinkRequest(
        operation="direct",
        slots=[raw.RawScopeSlot(ticker="IJC", year=2016)],
        doc_type="consolidated",
        period="current",
        target_unit="billion_vnd",
        query_norm=raw._norm(Q_PREPAID),
        query_tokens=raw._tokens(Q_PREPAID),
    ),
    table_ids=[PREPAID_NOTE],
    limit_per_slot=12,
)
check(
    "a total row scores off its siblings even when the question omits tổng",
    next(c for c in prepaid_candidates if c.row_label == "Cộng").row_score > 0,
)

Q_COMPONENT = "Số dư trả trước tiền thuê đất của IJC đến ngày 31/12/2016 là bao nhiêu tỷ đồng?"
component_candidates, _ = raw.build_candidates(
    raw.RawLinkRequest(
        operation="direct",
        slots=[raw.RawScopeSlot(ticker="IJC", year=2016)],
        doc_type="consolidated",
        period="current",
        target_unit="billion_vnd",
        query_norm=raw._norm(Q_COMPONENT),
        query_tokens=raw._tokens(Q_COMPONENT),
    ),
    table_ids=[PREPAID_NOTE],
    limit_per_slot=12,
)
check(
    "the row the question names by name outranks the total above it",
    component_candidates[0].row_label == "- Trả trước tiền thuê đất",
)

# pytest imports every test module into one process, so leaving the synthetic
# loaders in place makes any module that reads a real table fail depending on
# collection order.
raw.load_frame, raw.meta_for, raw.page_text = _real_loaders

print("tất cả PASS")
