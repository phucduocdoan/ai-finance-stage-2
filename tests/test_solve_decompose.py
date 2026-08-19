"""Regression tests for `modules.solve.decompose` (selection fan-out planning).

Everything here is the deterministic half: the trigger, the axis, the template
filling, the table split and the selection arithmetic. `aplan` is the only part
that needs a model and is deliberately not exercised — the point of splitting the
module was that the arithmetic which decides the answer can be checked without a
server.

The questions are the real ones from the 94-question gold set, so a change that
breaks the shapes actually present in the block fails here rather than in a
40-minute run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.decompose import (
    SelectionPlan,
    axis_of,
    degenerate_query,
    pick,
    sub_question,
    tables_for,
    years_in_text,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


Q363 = ("Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, "
        "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?")
Q390 = ("Năm 2024, giá trị hàng tồn kho của doanh nghiệp có hệ số thanh toán nhanh "
        "thấp nhất trong 3 doanh nghiệp Hoà Phát, Hoa Sen, Nam Kim là bao nhiêu nghìn tỷ đồng?")
Q387 = ("Trong giai đoạn 2021-2024, ở năm mà Hòa Phát có tỷ lệ lưu chuyển tiền thuần từ "
        "hoạt động kinh doanh trên lợi nhuận sau thuế thấp nhất (chỉ tính các năm có lợi "
        "nhuận sau thuế lớn hơn 0), hệ số khả năng thanh toán lãi vay của năm đó là bao nhiêu lần?")
Q439 = ("Trong giai đoạn 2018–2024 của HPG, xét các năm có biên lợi nhuận gộp thấp hơn mức "
        "trung vị của cả giai đoạn. Trong số các năm này, ROE của năm có tỷ lệ dòng tiền "
        "thuần từ hoạt động kinh doanh (CFO) trên doanh thu thuần cao nhất là bao nhiêu phần trăm?")
Q372 = ("Công ty Vincom Retail có hệ số dòng tiền hoạt động trên nợ ngắn hạn vào năm sau "
        "năm có hệ số thanh toán nhanh thấp nhất trong giai đoạn 2021-2024 là bao nhiêu lần?")
Q_PLAIN = "Doanh thu thuần năm 2023 của HPG là bao nhiêu tỷ đồng?"


# ---------------------------------------------------------------- the trigger

check("câu thường không kích hoạt", axis_of(Q_PLAIN, [2023], ["HPG"]) is None)
check("dấu hiệu nhưng trục 1 phần tử không kích hoạt",
      axis_of("Doanh thu cao nhất của HPG năm 2023?", [2023], ["HPG"]) is None)
check("trục năm", axis_of(Q363, [2016, 2017, 2018, 2019, 2020], ["KBC"])
      == ("year", [2016, 2017, 2018, 2019, 2020]))
check("trục mã khi chỉ có một năm",
      axis_of(Q390, [2024], ["HPG", "HSG", "NKG"]) == ("ticker", ["HPG", "HSG", "NKG"]))
check("năm thắng trục khi cả hai đều nhiều",
      axis_of(Q363, [2016, 2017], ["KBC", "HPG"])[0] == "year")

# `understand` is an LLM call and `metric` has sat unused in the state since it
# was added, so the trigger must not be the first thing to trust one of its
# fields blind: an empty `years` still finds the span written in the question.
check("years rỗng vẫn đọc được dải năm trong câu hỏi",
      axis_of(Q363, [], ["KBC"]) == ("year", [2016, 2017, 2018, 2019, 2020]))
check("dải năm bung đủ", years_in_text(Q439) == {2018, 2019, 2020, 2021, 2022, 2023, 2024})
check("liệt kê rời rạc giữ nguyên",
      years_in_text("Trong các năm 2015, 2017 và 2019 ...") == {2015, 2017, 2019})
check("dải quá rộng chỉ giữ hai đầu mút", years_in_text("giai đoạn 2005-2024") == {2005, 2024})
# ...and a period that cannot be enumerated is not an axis at all: ranking two
# endpoints and answering from the winner would never say the other eighteen
# years were not looked at.
check("dải quá rộng không kích hoạt",
      axis_of("Trong giai đoạn 2005-2024, năm HPG có doanh thu cao nhất là năm nào?",
              [2005, 2024], ["HPG"]) is None)


# ------------------------------------------------------------------ templates

check("điền năm", sub_question("Tỷ số D/E của KBC năm {year} là bao nhiêu?", "year", 2018)
      == "Tỷ số D/E của KBC năm 2018 là bao nhiêu?")
check("điền mã", sub_question("Hệ số thanh toán nhanh của {ticker} năm 2024?", "ticker", "HSG")
      == "Hệ số thanh toán nhanh của HSG năm 2024?")
# Both placeholders, not just the axis one: a blanked company turns the
# sub-question into "hệ số ... của  năm 2018" (measured on q363).
check("trục năm vẫn điền mã",
      sub_question("D/E của {ticker} năm {year}?", "year", 2018, "KBC")
      == "D/E của KBC năm 2018?")
check("trục mã vẫn điền năm",
      sub_question("D/E của {ticker} năm {year}?", "ticker", "HSG", "2024")
      == "D/E của HSG năm 2024?")
# A template the model wrote with a stray brace must not take the question down;
# the node reads "" as "no sub-question" and falls back to the unchanged path.
check("template hỏng trả về rỗng", sub_question("Tỷ số {metric} năm {year}?", "year", 2018) == "")


# ------------------------------------------------------------- table splitting

IDS = [
    "KBC_financial_statements_2016_consolidated|8",
    "KBC_financial_statements_2020_consolidated|9",
    "KBC_financial_statements_2018_consolidated|8",
    "KBC_financial_statements_2018_consolidated|4",
    "HPG_financial_statements_2018_consolidated|3",
]
check("tách theo năm", tables_for(IDS, "year", 2018) == [
    "KBC_financial_statements_2018_consolidated|8",
    "KBC_financial_statements_2018_consolidated|4",
    "HPG_financial_statements_2018_consolidated|3",
])
check("giữ thứ tự xếp hạng của retrieval",
      tables_for(IDS, "year", 2018)[0].endswith("|8"))
check("tách theo mã", tables_for(IDS, "ticker", "HPG")
      == ["HPG_financial_statements_2018_consolidated|3"])
check("phần tử không có bảng", tables_for(IDS, "year", 2017) == [])


# --------------------------------------------------------------- the selection

RANK = SelectionPlan(rank_metric="D/E của KBC năm {year}?", rank_op="max",
                     answer_metric="Hệ số thanh toán lãi vay của KBC năm {year}?")

winner, trace = pick(RANK, "year", {2016: 1.0, 2017: 3.0, 2018: 2.0})
check("argmax chọn đúng năm", winner == 2017)
check("trace mang toàn bộ chuỗi", trace["ranks"] == {"2016": 1.0, "2017": 3.0, "2018": 2.0})

MIN = RANK.model_copy(update={"rank_op": "min"})
check("argmin", pick(MIN, "year", {2016: 1.0, 2017: 3.0, 2018: 2.0})[0] == 2016)

# A sub-question that produced no number is dropped, never scored 0.0: on q381
# ("the year HPG had the *lowest* CFO/LNST") a spurious zero wins `min` outright
# and every query downstream still runs cleanly.
winner, trace = pick(MIN, "year", {2016: None, 2017: 3.0, 2018: 2.0})
check("phần tử hỏng bị loại chứ không thành 0.0", winner == 2018)
check("phần tử hỏng được ghi lại", trace["dropped"] == ["2016"])
check("dưới 2 phần tử sống thì bỏ cuộc",
      pick(MIN, "year", {2016: None, 2017: None, 2018: 2.0})[0] is None)

# q387: rank over the years that pass a literal predicate.
FILTERED = MIN.model_copy(update={
    "filter_metric": "LNST của HPG năm {year}?", "filter_op": ">", "filter_threshold": "0",
})
winner, trace = pick(FILTERED, "year",
                     {2021: 1.0, 2022: 0.5, 2023: 0.2, 2024: 0.9},
                     {2021: 5.0, 2022: -2.0, 2023: -1.0, 2024: 3.0})
check("lọc theo ngưỡng số rồi mới xếp hạng", winner == 2024)
check("người sống sót được ghi lại", trace["survivors"] == ["2021", "2024"])
check("ngưỡng được ghi lại", trace["threshold"] == 0.0)

# q439/q378: the threshold is the median of the series being filtered on, which
# is why it is a keyword and not a number the model was asked to compute.
MEDIAN = SelectionPlan(rank_metric="CFO/DTT của HPG năm {year}?", rank_op="max",
                       answer_metric="ROE của HPG năm {year}?",
                       filter_metric="Biên lợi nhuận gộp của HPG năm {year}?",
                       filter_op="<", filter_threshold="median")
winner, trace = pick(MEDIAN, "year",
                     {2018: 1.0, 2019: 9.0, 2020: 3.0, 2021: 2.0, 2022: 8.0},
                     {2018: 10.0, 2019: 20.0, 2020: 30.0, 2021: 40.0, 2022: 50.0})
check("trung vị làm ngưỡng", trace["threshold"] == 30.0)
check("xếp hạng chỉ trong nhóm dưới trung vị", winner == 2019)

check("không ai qua được lọc thì bỏ cuộc",
      pick(FILTERED, "year", {2021: 1.0, 2022: 0.5},
           {2021: -5.0, 2022: -2.0})[0] is None)
# A filter narrowing the field to one is the question doing its job; a *ranking*
# with one candidate is not, which is why the guard sits before the filter.
check("lọc còn đúng 1 phần tử vẫn hợp lệ",
      pick(FILTERED, "year", {2021: 1.0, 2022: 0.5}, {2021: 5.0, 2022: -2.0})[0] == 2021)
check("ngưỡng không đọc được thì bỏ cuộc",
      pick(FILTERED.model_copy(update={"filter_threshold": "dương"}), "year",
           {2021: 1.0, 2022: 0.5}, {2021: 5.0, 2022: -2.0})[0] is None)

# q372/q407: "the year *after* the one with the lowest ...".
OFFSET = MIN.model_copy(update={"offset": 1})
winner, trace = pick(OFFSET, "year", {2021: 3.0, 2022: 1.0, 2023: 2.0, 2024: 4.0})
check("lệch một kỳ", winner == 2023)
check("cả mốc gốc lẫn mốc lệch đều được ghi lại",
      trace["winner"] == "2022" and trace["winner_after_offset"] == "2023")
check("lệch kỳ không áp cho trục mã",
      pick(OFFSET.model_copy(update={"rank_op": "max"}), "ticker",
           {"HPG": 1.0, "HSG": 2.0})[0] == "HSG")


# ------------------------------------------------------- the degenerate query

# What a sub-question returns when the model cannot find its second row. It is
# not a failure `aexecute` can see — the query runs and yields 1.0, which then
# beats every genuine ratio in the series (measured on q363, four years of five).
check("x / x là suy biến",
      degenerate_query('df1.iloc[19]["Số cuối năm"] / df1.iloc[19]["Số cuối năm"]'))
check("hai dòng khác nhau thì không",
      not degenerate_query('df2.iloc[0]["Số cuối năm"] / df3.iloc[0]["Số cuối năm"]'))
check("cùng bảng khác dòng thì không",
      not degenerate_query('df1.iloc[12]["Số cuối năm"] / df1.iloc[1]["Số cuối năm"]'))
check("một ô đơn lẻ không phải suy biến",
      not degenerate_query('df1.iloc[0]["Số cuối năm"]'))
check("truy vấn không parse được thì bỏ qua", not degenerate_query("df1.iloc[0] /"))
# Only the top-level division: `(a - b) / (a - b)` is the same mistake, but
# `a / b * (c / c)` is not one this has any business rewriting.
check("suy biến trên biểu thức ghép",
      degenerate_query('(df1.iloc[1]["A"] - df1.iloc[2]["A"]) / (df1.iloc[1]["A"] - df1.iloc[2]["A"])'))

print("tất cả PASS")
