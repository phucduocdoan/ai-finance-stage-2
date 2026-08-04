"""Checks for exec_query.py, run against real corpus tables (no fixtures).

  .venv_bge/bin/python tests/test_query_execution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.execution.query import load_frame, parse_number, run_query, validate
from finance_qa.paths import TABLES_DIR

TID = "AAA_financial_statements_2015_consolidated|4"   # BÁO CÁO KQKD hợp nhất
CSV = "data/AAA_financial_statements_2015_consolidated_table_4.csv"
# Doanh thu thuần 2015, in đủ trong bảng: 1.614.548.947.901
QUERY = (
    'float(df1.loc[df1["CHÍ TIÊU"].str.contains("Doanh thu thuần", case=False, '
    'na=False), "Năm 2015"].iloc[0])'
)
TRUTH = 1_614_548_947_901.0

fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'ok  ' if cond else 'FAIL'} {name}{'  -- ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


def item(**over) -> dict:
    base = {
        "id": 1,
        "question": "Doanh thu thuần của AAA năm 2015 là bao nhiêu?",
        "answer": TRUTH,
        "relevant_docs": [TID.rsplit("|", 1)[0]],
        "relevant_tables": [TID],
        "evidence": [{"variable": "df1", "csv_path": CSV}],
        "pandas_query": QUERY,
    }
    return {**base, **over}


# --- number parsing -----------------------------------------------------------
for text, want in [
    ("1.616.048.818.116", 1_616_048_818_116.0),   # VN thousands
    ("1,616,048,818,116", 1_616_048_818_116.0),   # EN thousands
    ("(1.234)", -1234.0),                          # accounting negative
    ("-1.234", -1234.0),
    ("1.234,56", 1234.56),                         # VN decimal
    ("1,234.56", 1234.56),                         # EN decimal
    ("1,5", 1.5),                                  # bare decimal, not 3-grouped
    ("12,5%", None),                               # not a plain number
    ("", None),
    ("Doanh thu", None),
]:
    got = parse_number(text)
    check(f"parse_number({text!r})", got == want, f"got {got!r}, want {want!r}")

# --- normalization ------------------------------------------------------------
df = load_frame(TID)
check("cột tiền thành float", str(df["Năm 2015"].dtype).startswith("float"),
      str(df["Năm 2015"].dtype))
# not `== object`: pandas 3 gives the label column StringDtype, which is still text.
check("cột nhãn giữ nguyên text",
      not str(df["CHÍ TIÊU"].dtype).startswith(("float", "int")),
      str(df["CHÍ TIÊU"].dtype))

# A real balance sheet whose figures stayed strings until '-' (accounting nil) was
# excluded from the parse-ratio vote. Regression guard for that column-wide failure.
nil_df = load_frame("SGB_financial_statements_2016_separate|8")
check("cột lẫn dấu '-' vẫn thành float",
      str(nil_df["31/12/2016"].dtype).startswith("float"),
      str(nil_df["31/12/2016"].dtype))
check("giá trị thật không bị mất", nil_df["31/12/2016"].iloc[0] == 3_514_518.0,
      repr(nil_df["31/12/2016"].iloc[0]))
check("'-' đọc thành 0.0", (nil_df["31/12/2016"] == 0.0).any())

# Bank statements with two unlabeled leading columns used to shift every header
# left: the note number looked like the 2018 value and the real 2018 value looked
# like 2017. The exported/evaluated frame must repair that structure.
bank_df = load_frame("SHB_financial_statements_2018_consolidated|5")
check("sửa header bank bị lệch",
      list(bank_df.columns[:4]) == ["STT", "Chỉ tiêu", "Thuyết minh", "2018Triệu VND"],
      repr(list(bank_df.columns)))
check("giá trị bank nằm đúng cột năm",
      bank_df.loc[5, "2018Triệu VND"] == 713_942.0,
      repr(bank_df.loc[5, "2018Triệu VND"]))

# A two-row HTML header with rowspan/colspan was serialized left-aligned by the
# legacy extractor.  The first data row is really the subheader and the ending
# balance sits in an anonymous column unless load_frame reconstructs the spans.
rollforward_df = load_frame("FTS_financial_statements_2018|22")
ending_column = "Số cuối kỳ"
check("khôi phục header hai tầng bị lệch",
      ending_column in rollforward_df.columns,
      repr(list(rollforward_df.columns)))
check("số cuối kỳ nằm đúng cột semantic",
      ending_column in rollforward_df.columns
      and rollforward_df.loc[6, ending_column] == 190_150_000.0,
      repr(rollforward_df.tail(1)))

# --- happy path ---------------------------------------------------------------
check("query chạy đúng số", run_query(QUERY, {"df1": df}) == TRUTH)
check("validate item hợp lệ", validate(item()) == [], str(validate(item())))

# --- multi-statement fallback -------------------------------------------------
multi = 'x = df1["Năm 2015"].iloc[2]\nanswer = float(x)'
check("exec() fallback cho nhiều câu lệnh", run_query(multi, {"df1": df}) == TRUTH)

# --- each failure mode is actually caught -------------------------------------
cases = {
    "answer lệch kết quả": item(answer=123.0),
    "csv_path không bắt đầu bằng data/": item(
        evidence=[{"variable": "df1", "csv_path": "tables/x.csv"}]),
    "query dùng df2 không khai báo": item(
        pandas_query=QUERY.replace("iloc[0])", 'iloc[0]) - df2["Năm 2015"].iloc[0]')),
    "evidence thừa không được dùng": item(
        evidence=[{"variable": "df1", "csv_path": CSV},
                  {"variable": "df2", "csv_path": CSV}]),
    "table không thuộc relevant_docs": item(relevant_docs=["SOMETHING_ELSE"]),
    "table không tồn tại": item(
        relevant_docs=["AAA_financial_statements_2015_consolidated"],
        relevant_tables=["AAA_financial_statements_2015_consolidated|99999"]),
    "cột sai -> query lỗi": item(pandas_query='float(df1["Năm 2099"].iloc[0])'),
    "answer là chuỗi": item(answer="1614548947901"),
}
for name, bad in cases.items():
    errs = validate(bad)
    check(f"bắt được: {name}", bool(errs), errs[0] if errs else "KHÔNG BÁO LỖI")

# --- the silent-concat bug this module exists to prevent ----------------------
import pandas as pd  # noqa: E402

raw = pd.read_csv(
    TABLES_DIR / TID.rsplit("|", 1)[0] / "table_4.csv",
    dtype=str, keep_default_na=False,
)
check("CSV thô vẫn là chuỗi (lý do phải chuẩn hoá)",
      isinstance(raw["Năm 2015"].iloc[0], str))
check("nhân 2 trên CSV thô ra chuỗi nối, không crash",
      raw["Năm 2015"].iloc[0] * 2 == raw["Năm 2015"].iloc[0] * 2
      and not isinstance(raw["Năm 2015"].iloc[0] * 2, float))

print()
print(f"{len(fails)} FAIL" if fails else "tất cả PASS")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
