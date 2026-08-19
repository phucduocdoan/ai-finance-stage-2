"""Offline tests for the deterministic half of the solve pipeline.

No LLM, no retrieval: unit detection, unit conversion, the prompt context and the
execute/repair loop with a stubbed model. Everything here would have caught the
q45 failure that motivated `modules/solve/common/units.py`.

    PYTHONPATH=src .venv_bge/bin/python tests/test_solve_units.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.codegen import execute
from finance_qa.modules.solve.common import context, solution, units
from finance_qa.modules.data.table_store import load_frame

# The table behind question 45: BAB total liabilities, "Triệu VND" declared in row
# 0 of the grid rather than in any column name.
Q45_TABLE = "BAB_financial_statements_2020_separate|6"


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


# ── unit vocabulary ────────────────────────────────────────────────────────────
check(
    "solution.Unit literal matches units.UNITS",
    set(solution.Unit.__args__) == units.UNITS,
)

# ── unit_in_text ───────────────────────────────────────────────────────────────
check("million: 'Triệu VND'", units.unit_in_text("Triệu VND") == "million_vnd")
check("million: 'Đơn vị: triệu đồng'", units.unit_in_text("Đơn vị: triệu đồng") == "million_vnd")
check("billion beats bare vnd", units.unit_in_text("tỷ đồng") == "billion_vnd")
check("trillion beats billion", units.unit_in_text("nghìn tỷ đồng") == "trillion_vnd")
check("thousand: 'nghìn đồng'", units.unit_in_text("Nghìn đồng") == "thousand_vnd")
check("bare vnd", units.unit_in_text("VND") == "vnd")
# 'tỷ lệ' means "ratio"; matching a bare `tỷ` here inflated an earlier count of
# billion-unit tables from 0.2% to 19.0%.
check("'Tỷ lệ (%)' is not a money unit", units.unit_in_text("Tỷ lệ (%)") is None)
check("'tỷ suất lợi nhuận' is not a money unit", units.unit_in_text("tỷ suất lợi nhuận") is None)
check("empty text", units.unit_in_text("") is None)

# ── unit_from_hint ─────────────────────────────────────────────────────────────
check("hint: question asking triệu đồng", units.unit_from_hint("là bao nhiêu triệu đồng?") == "million_vnd")
check("hint: percent", units.unit_from_hint("bao nhiêu %?") == "percent")
check("hint: lần -> ratio", units.unit_from_hint("bao nhiêu lần?") == "ratio")
check("hint: money wins over ratio", units.unit_from_hint("tỷ đồng") == "billion_vnd")
check("hint: nothing stated", units.unit_from_hint("Doanh thu năm 2020 là bao nhiêu?") is None)

# ── detection on the real q45 frame ────────────────────────────────────────────
df45 = load_frame(Q45_TABLE)
unit, where = units.detect_table_unit(df45)
check("q45: unit detected from a grid cell, not a header", unit == "million_vnd")
check("q45: provenance names the row", where.startswith("row 0"))

# A column name declaring its own unit beats the table banner.
mixed = pd.DataFrame(
    {
        "Chỉ tiêu": ["Triệu VND", "Doanh thu"],
        "Giá (VND)": ["", "25000"],
        "2020": ["", "1234"],
    }
)
check("column-level unit wins", units.detect_unit(mixed, "Giá (VND)")[0] == "vnd")
check("falls back to table banner", units.detect_unit(mixed, "2020")[0] == "million_vnd")
check("no column given -> table level", units.detect_unit(mixed, None)[0] == "million_vnd")
check("undeclared table -> None", units.detect_table_unit(pd.DataFrame({"a": ["1"]}))[0] is None)

# qid280: "- Bằng VND" is a row label meaning "denominated in VND", not a unit
# banner, and it must not outrank the column names that say "Triệu đồng".
hdb = pd.DataFrame(
    {
        "Unnamed: 0": ["Cho vay tái tài trợ", "- Bằng VND", "- Bằng ngoại tệ"],
        "31.12.2022Triệu đồng": [None, 8634940.0, 174890.0],
    }
)
check("bare VND in a row label loses to a column name", units.detect_table_unit(hdb)[0] == "million_vnd")
check(
    "bare VND still wins when nothing else declares",
    units.detect_table_unit(pd.DataFrame({"a": ["- Bằng VND"], "2022": ["5"]}))[0] == "vnd",
)

# qid86/88/120: bank statements printed in millions whose banner row was lost in
# extraction. The declaration survives only in the page text.
PAGE = "BẢNG CÂN ĐỐI KẾ TOÁN HỢP NHẤT Tại ngày 31 tháng 12 năm 2019 Đơn vị tính: Triệu đồng Việt Nam"
silent = pd.DataFrame({"CHỈ TIÊU": ["IX. Tài sản cố định"], "31/12/2019": [589531.0]})
check("page declaration recovers an undeclared table", units.detect_table_unit(silent, PAGE)[0] == "million_vnd")
check("page text without a declaration is ignored", units.detect_table_unit(silent, "Lãi 5 triệu cổ phiếu")[0] is None)
check("declaration is read from page text", units.unit_in_declaration(PAGE)[0] == "million_vnd")
check("no declaration in page text", units.unit_in_declaration("Báo cáo hợp nhất 2019")[0] is None)
# A declared table ignores the page: the grid is closer to the value than the page is.
check("grid beats page text", units.detect_table_unit(df45, PAGE)[0] == "million_vnd")

# ── source unit resolution ─────────────────────────────────────────────────────
check("detected unit wins", units.resolve_source_unit("million_vnd", "trillion_vnd")[0] == "million_vnd")
# qid263: the model called a raw-VND cell "trillion_vnd" because the number is
# 4.26e12, so conversion_factor found nothing to convert and the answer stayed 1e12
# too large. Money scale is never taken from the model.
check("model money unit is discarded", units.resolve_source_unit(None, "trillion_vnd")[0] == "vnd")
check("undeclared defaults to vnd", units.resolve_source_unit(None, "unknown")[0] == "vnd")
check("model percent is kept", units.resolve_source_unit(None, "percent")[0] == "percent")
check("model ratio is kept", units.resolve_source_unit(None, "ratio")[0] == "ratio")
check("fallback is recorded", "vnd" in units.resolve_source_unit(None, "unknown")[1])

# ── model-written scale factors ────────────────────────────────────────────────
check("trailing /1e11 is stripped", units.strip_scale_factor("df1.iloc[0, 1] / 1e11")[0] == "df1.iloc[0, 1]")
check("trailing * 1000 is stripped", units.strip_scale_factor("df1.iloc[0, 3] * 1000")[0] == "df1.iloc[0, 3]")
check("trailing * 1e3 is stripped", units.strip_scale_factor("df1.iloc[1, 3] * 1e3")[0] == "df1.iloc[1, 3]")
check("stripped factor is reported", units.strip_scale_factor("df1.iloc[0, 1] / 1e11")[1] == ["/ 1e11"])
# * 100 is a ratio->percent conversion, which code never does, so it is the model's.
check("* 100 is left alone", units.strip_scale_factor("(df1.iloc[0,1] - df1.iloc[0,2]) * 100")[1] == [])
check("a ratio of two cells is left alone", units.strip_scale_factor("df1.iloc[0,1] / df1.iloc[0,2]")[1] == [])
check("a clean query is unchanged", units.strip_scale_factor("df1.iloc[12, 3]") == ("df1.iloc[12, 3]", []))
check(
    "a factor inside parentheses is left alone",
    units.strip_scale_factor("(df1.iloc[0,1] / 1e6).round(2)")[1] == [],
)
check("two stacked factors both go", units.strip_scale_factor("df1.iloc[0,1] / 1e6 * 1e9")[1] == ["* 1e9", "/ 1e6"])
check("nothing to strip leaves a bare literal", units.strip_scale_factor("0.0") == ("0.0", []))

# ── conversion ─────────────────────────────────────────────────────────────────
check("million -> vnd", units.conversion_factor("million_vnd", "vnd") == 1e6)
check("vnd -> million", units.conversion_factor("vnd", "million_vnd") == 1e-6)
check("identity", units.conversion_factor("million_vnd", "million_vnd") == 1.0)
check("scale-free target passes through", units.conversion_factor("million_vnd", "unknown") == 1.0)
check("percent is never rescaled", units.conversion_factor("percent", "million_vnd") == 1.0)

# The q45 bug in one line: the value is printed in triệu VND, the question asks for
# triệu VND, so the answer is the cell itself -- the old planner divided by 1e6.
check(
    "q45: no scaling when source == target",
    units.scale_expression("df1.iloc[12]['31/12/2020']", "million_vnd", "million_vnd")
    == "df1.iloc[12]['31/12/2020']",
)
check(
    "million -> vnd emits 1e6, not 1000000.0",
    units.scale_expression("X", "million_vnd", "vnd") == "(X) * 1e6",
)
check("vnd -> million emits 1e-6", units.scale_expression("X", "vnd", "million_vnd") == "(X) * 1e-6")
check(
    "billion -> million emits 1e3",
    units.scale_expression("X", "billion_vnd", "million_vnd") == "(X) * 1e3",
)

# ── prompt context ─────────────────────────────────────────────────────────────
block = context.table_context("df1", Q45_TABLE, df45)
check("context shows the declared unit", "million_vnd" in block)
check("context shows real cell values", "NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU" in block or "PHẢI TRẢ" in block)
check("context shows the shape", f"{df45.shape[0]} hàng" in block)
check("context shows column names", "31/12/2020" in block)
# Row numbers are what the model writes into .iloc[...], so they must be visible.
check("context shows row positions", "\n0 " in block or block.count("\n 0") or " 0  " in block)

big = pd.DataFrame({"a": [str(i) for i in range(200)], "b": list(range(200))})
check("big tables are truncated", "hàng ở giữa bị ẩn" in context._grid(big))
check("small tables are not truncated", "hàng ở giữa bị ẩn" not in context._grid(df45))

line = context.candidate_line(3, Q45_TABLE)
check("candidate line is numbered", line.startswith("[3] "))
check("candidate line carries the table id", Q45_TABLE in line)
check("candidate line stays one line", "\n" not in line)


# ── execute + repair ───────────────────────────────────────────────────────────
frames = {"df1": df45}


def run(coro):
    return asyncio.run(coro)


ok = solution.PandasSolution(
    table_variable="df1",
    target_row="Tiền gửi của các tổ chức tín dụng khác",
    target_column="31/12/2020",
    source_unit="million_vnd",
    target_unit="million_vnd",
    pandas_query="df1.iloc[4]['31/12/2020']",
)
result = run(execute.aexecute(ok, "", frames, question="… bao nhiêu triệu đồng?"))
check("clean query executes", result["answer"] == float(df45.iloc[4]["31/12/2020"]))
check("clean query is submitted unchanged", result["pandas_query"] == ok.pandas_query)
check("no errors on the happy path", result["errors"] == [])
check("diag records where the unit came from", result["diag"]["source_unit_from"].startswith("row 0"))

# Question asks for VND while the table prints triệu VND -> scaling is applied by
# code, and the submitted query carries it so the grader reproduces the answer.
scaled = run(execute.aexecute(ok, "", frames, question="… bao nhiêu đồng?"))
check("target VND scales up", scaled["answer"] == float(df45.iloc[4]["31/12/2020"]) * 1e6)
check("submitted query contains the factor", scaled["pandas_query"].endswith("* 1e6"))

hundred_billion = run(
    execute.aexecute(ok, "", frames, question="… mấy trăm tỷ đồng?", unit_hint="tỷ")
)
check("question unit beats lossy unit_hint", hundred_billion["diag"]["target_unit"] == "hundred_billion_vnd")
check("hundred-billion target scales from table unit", hundred_billion["answer"] == float(df45.iloc[4]["31/12/2020"]) / 1e5)

# The double-scaling bug, end to end: the model writes its own conversion AND
# mislabels the source unit. Pre-fix this produced answers 1e6-1e15 off gold.
q45_cell = float(df45.iloc[4]["31/12/2020"])
selfscaled = ok.model_copy(
    update={"pandas_query": "df1.iloc[4]['31/12/2020'] / 1e6", "source_unit": "trillion_vnd"}
)
once = run(execute.aexecute(selfscaled, "", frames, question="… bao nhiêu triệu đồng?"))
check("model's own factor is not applied", once["answer"] == q45_cell)
check("stripped factor is in the diag", once["diag"]["model_factors_stripped"] == ["/ 1e6"])
check("submitted query has no model factor", "1e6" not in once["pandas_query"])
# Same query, but now a conversion really is due: exactly one factor may appear.
to_vnd = run(execute.aexecute(selfscaled, "", frames, question="… bao nhiêu đồng?"))
check("conversion applied exactly once", to_vnd["answer"] == q45_cell * 1e6)

# The model's source_unit is only a fallback: the grid wins when it declares one.
lying = ok.model_copy(update={"source_unit": "vnd"})
fixed = run(execute.aexecute(lying, "", frames, question="… bao nhiêu triệu đồng?"))
check("grid overrides a wrong model source_unit", fixed["answer"] == float(df45.iloc[4]["31/12/2020"]))

# Repair: first attempt raises, the stub returns a working query.
broken = ok.model_copy(update={"pandas_query": "df1.iloc[4]['31/12/2021']"})
calls: list[str] = []


async def fake_repair(prompt, attempts_so_far, *, history=False):
    calls.append(attempts_so_far[-1][1])
    return ok


original_repair = execute._arepair
execute._arepair = fake_repair
repaired = run(execute.aexecute(broken, "PROMPT", frames, question="… triệu đồng?"))
execute._arepair = original_repair
check("repair is called once for one bad query", len(calls) == 1)
check("repair receives the execution error", "31/12/2021" in calls[0] or "KeyError" in calls[0])
check("repaired query returns the value", repaired["answer"] == float(df45.iloc[4]["31/12/2020"]))
check("the failed attempt is kept in errors", any("execute[0]" in e for e in repaired["errors"]))

# Repair budget is bounded: 2 repairs means at most 3 executions, then give up.
attempts: list[str] = []


async def never_fixes(prompt, attempts_so_far, *, history=False):
    attempts.append(attempts_so_far[-1][1])
    return broken


execute._arepair = never_fixes
gave_up = run(execute.aexecute(broken, "PROMPT", frames, question="… triệu đồng?"))
execute._arepair = original_repair
check("repair stops after max_repairs", len(attempts) == execute.MAX_REPAIRS)
check("failure still answers 0.0", gave_up["answer"] == 0.0)
# A bare float literal forfeits EXECUTION_ACCURACY; 322/1012 of the old flow's
# submitted queries were literals, 119 of them "0.0".
check("failure still submits a real query", gave_up["pandas_query"] == broken.pandas_query)

# ── column -> year, the join the model cannot make ─────────────────────────────
from finance_qa.modules.solve.common import columns  # noqa: E402


def frame(cols: dict) -> pd.DataFrame:
    return pd.DataFrame(cols)


BIG = [5e9, 6e9]
OLD = [4e9, 5e9]

check(
    "cuối năm / đầu năm resolve against the report year",
    columns.column_years(
        frame({"Mã số": [100, 110], "Số cuối năm": BIG, "Số đầu năm": OLD}), "x_2018|3", 2018
    ) == {"Số cuối năm": "2018", "Số đầu năm": "2017"},
)
check(
    "the comparative column of a two-period statement is one year back",
    columns.column_years(
        frame({"Tại ngày 31 tháng 12 năm": BIG, "Unnamed: 4": OLD}), "x_2018|3", 2018
    ) == {"Tại ngày 31 tháng 12 năm": "2018", "Unnamed: 4": "2017"},
)
check(
    "headers that already name the year are left alone",
    columns.column_years(frame({"2018": BIG, "2017": OLD}), "x_2018|3", 2018) == {},
)
check(
    "`Mã số` is numeric but is not money",
    columns.column_years(frame({"Mã số": [100, 110], "Chỉ tiêu": ["a", "b"]}), "x_2018|3", 2018) == {},
)
check(
    "no report year anywhere -> say nothing rather than guess",
    columns.column_years(frame({"Số cuối năm": BIG}), "abc|3", None) == {},
)
check(
    "the legend names every money column",
    columns.year_legend(frame({"Số cuối năm": BIG, "Số đầu năm": OLD}), "x_2018|3", 2018)
    == "Năm của từng cột số tiền (suy ra từ năm báo cáo): "
       "'Số cuối năm' = năm 2018; 'Số đầu năm' = năm 2017",
)
check("no money column -> no legend line", columns.year_legend(frame({"Chỉ tiêu": ["a"]}), "x_2018|3", 2018) == "")

legend_ctx = context.table_context("df1", Q45_TABLE, load_frame(Q45_TABLE))
check("table_context still renders without a legend when the header has years",
      legend_ctx.count("Năm của từng cột số tiền") <= 1)

# ── what the repair call is shown ──────────────────────────────────────────────
two_year = frame({"Số cuối năm": BIG, "Số đầu năm": OLD})
try:
    two_year.iloc[0]["2018"]
except Exception as exc:  # noqa: BLE001
    described = execute.describe_error(exc, 'df1.iloc[0]["2018"]', {"df1": two_year})
check("the error names its type", described.startswith("KeyError:"))
check("the error lists the columns that do exist", "'Số cuối năm', 'Số đầu năm'" in described)
check("the error gives the valid row range", "0..1" in described)
check("an unknown variable is reported as such",
      "df9: biến này không tồn tại" in execute.describe_error(KeyError("x"), "df9.iloc[0]", {}))
check("repair does not run at temperature 0", execute.REPAIR_TEMPERATURE > 0)

# ── what the verify call is shown ──────────────────────────────────────────────
from finance_qa.modules.solve.codegen import verify  # noqa: E402

five = pd.DataFrame({
    "Chỉ tiêu": ["a", "b", "c", "d", "e", "f"],
    "Số cuối năm": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
})
shown = verify.touched_rows('df1.iloc[3]["Số cuối năm"]', {"df1": five}, {"df1": "x_2018|3"})
check("the row the query read is marked", "--> [3]" in shown)
check("the row's own label is shown", "Chỉ tiêu=d" in shown)
check("neighbours above are shown for contrast", "   [1] " in shown and "   [2] " in shown)
check("neighbours below are shown", "   [4] " in shown and "   [5] " in shown)
check("the window stops at 2 either side", "[0]" not in shown)
check(
    "a row read twice is shown once",
    verify.touched_rows(
        'df1.iloc[3]["Số cuối năm"] - df1.iloc[3]["Số cuối năm"]', {"df1": five}, {}
    ).count("--> [3]") == 1,
)
check(
    "two rows read -> two blocks",
    verify.touched_rows('df1.iloc[1] - df1.iloc[4]', {"df1": five}, {}).count("-->") == 2,
)
check("a row position past the end is skipped",
      verify.touched_rows("df1.iloc[99]", {"df1": five}, {}) == "")
check("an unknown variable is skipped", verify.touched_rows("df9.iloc[0]", {"df1": five}, {}) == "")
check("`df1.iloc[3, 1]` is matched too", "--> [3]" in verify.touched_rows("df1.iloc[3, 1]", {"df1": five}, {}))

vprompt = verify.build_prompt("Lợi nhuận?", "df1.iloc[3]", 4.0, {"df1": five}, {}, "triệu đồng")
check("the prompt carries the question", "Lợi nhuận?" in vprompt)
check("the prompt carries the value that came out", "Kết quả: 4.0" in vprompt)
check("the prompt carries the unit the question asked for", "triệu đồng" in vprompt)
check("a query reading nothing indexable still produces a prompt",
      "không xác định được" in verify.build_prompt("q", "42.0", 42.0, {}, {}))
check("the verdict defaults to accepting", verify.Verdict().correct is True)

print("tất cả PASS")
