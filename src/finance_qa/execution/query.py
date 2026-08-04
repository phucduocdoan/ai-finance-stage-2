"""Execute + validate the code half of a submission item.

The retrieval half (`relevant_docs` / `relevant_tables`) is scored separately from
the code half (`evidence` / `pandas_query` / `answer`), so this module owns only
the second one -- but it also checks the *joins* between them, because the failure
modes there are silent: a query that reads `df2` with no matching evidence entry,
or an `answer` the LLM wrote out that does not equal what the query returns.

Two design decisions that are not obvious:

**Numbers are normalized at export time, not parsed inside the query.**
The raw CSVs hold Vietnamese-formatted strings ('1.616.048.818.116'). pandas reads
those as `str`, so `df["Năm 2015"].iloc[0] * 2` does not raise -- it *concatenates*,
and the submission carries a silently wrong float. Making the generated query parse
the format instead is not an option: the organizer runs `pandas_query` in their own
namespace, so any helper of ours would be undefined there. The rule allows shipping
"dữ liệu đã chuẩn hoá", so the shipped CSV holds real floats and the query stays
plain pandas.

**The code prompt must be built from the exported frame, never from the raw CSV or
from `header_flat`.** 71% of tables have their label column named `Unnamed: 0`
(measured over 400 sampled tables) and `header_flat` drops it entirely, so a query
written against `header_flat` indexes the wrong column. `load_frames` returns
exactly what the evaluator will see; generate the prompt from that.
"""

from __future__ import annotations

import ast
import math
import re

import pandas as pd

from finance_qa.paths import TABLES_DIR

# Whatever the query may reference. Not a sandbox -- it runs our own generated code
# -- but a hallucinated `import os` or `requests` should fail loudly here rather
# than on the organizer's machine.
SAFE_GLOBALS = {
    "__builtins__": {
        "abs": abs, "float": float, "int": int, "len": len, "max": max,
        "min": min, "round": round, "sum": sum, "sorted": sorted, "str": str,
        "list": list, "range": range, "zip": zip, "enumerate": enumerate,
    },
    "pd": pd,
}


# --------------------------------------------------------------------------- numbers

_NUM_CHARS = re.compile(r"^[\d.,]+$")


def parse_number(text: str) -> float | None:
    """'1.616.048.818.116' -> 1616048818116.0, '(1.234)' -> -1234.0, else None.

    Separator disambiguation, because the corpus mixes VN and EN formatting:
    when both '.' and ',' appear the *last* one is the decimal point; when only one
    kind appears it is a thousands separator only if the digits group in threes
    ('1.616.048' yes, '1.5' no).
    """
    t = text.strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t[:1] in "-+":
        neg, t = neg or t[0] == "-", t[1:].strip()
    if not t or not _NUM_CHARS.fullmatch(t) or not any(c.isdigit() for c in t):
        return None

    has_dot, has_comma = "." in t, "," in t
    if has_dot and has_comma:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        t = t.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        grouped = re.fullmatch(rf"\d{{1,3}}(\{sep}\d{{3}})+", t) is not None
        t = t.replace(sep, "") if grouped else t.replace(sep, ".")
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if neg else value


# A lone dash is the accounting convention for nil. Counting it as unparseable is
# what killed whole columns: SGB_..._2016_separate|8 is a real balance sheet
# ('3.514.518', '3.390.617') where enough rows were '-' to drag the parse ratio
# under the threshold, so every figure stayed a string.
NIL_MARKS = {"-", "–", "—", "nan"}


def normalize_frame(df: pd.DataFrame, min_ratio: float = 0.6) -> pd.DataFrame:
    """Convert columns that are mostly numbers into real floats, leave labels alone.

    Whole-column rather than per-cell: a column of mixed str/float is exactly the
    thing that makes a query return a plausible wrong type.
    """
    out = df.copy()
    for col in out.columns:
        raw = out[col].astype(str).str.strip()
        is_nil = raw.isin(NIL_MARKS)
        filled = raw[raw.ne("") & ~is_nil]
        if filled.empty:
            continue
        # Nil cells are excluded from the vote, then read as 0.0 once the column
        # has been judged numeric -- they are evidence of neither.
        if filled.map(parse_number).notna().mean() >= min_ratio:
            out[col] = raw.map(lambda v: 0.0 if v in NIL_MARKS else parse_number(v))
    return out


# --------------------------------------------------------------------------- paths

def submission_csv_name(table_id: str) -> str:
    """'AAA_..._consolidated|4' -> 'AAA_..._consolidated_table_4.csv' (rule's example)."""
    doc, pos = table_id.rsplit("|", 1)
    return f"{doc}_table_{pos}.csv"


def source_csv(table_id: str) -> Path:
    doc, pos = table_id.rsplit("|", 1)
    return TABLES_DIR / doc / f"table_{pos}.csv"


def repair_shifted_bank_header(df: pd.DataFrame) -> pd.DataFrame:
    """Repair a common bank-statement header shifted one cell to the left.

    OCR tables such as SHB 2018|5 and VIB 2020|10 have two unlabeled leading
    columns (Roman item number + row label), but pandas receives only one blank
    header. Every semantic header is consequently attached to the column on its
    left and the final year column becomes ``Unnamed``::

        Unnamed: 0 | Thuyết minh | 2020 | 2019 | Unnamed: 4
        XIII       | Lợi nhuận...|      | 4.6m | 3.3m

    The values make the shape unambiguous: column 1 is predominantly prose, not
    note references. Repairing it at export time means the query and the shipped
    CSV share clear, executable column names.
    """
    cols = [str(col) for col in df.columns]
    if len(cols) < 4:
        return df
    shifted = (
        cols[0].startswith("Unnamed:")
        and cols[1].strip().casefold() == "thuyết minh"
        and cols[-1].startswith("Unnamed:")
    )
    if not shifted:
        return df

    second = df.iloc[:, 1].astype(str).str.strip()
    filled = second[second.ne("")]
    if filled.empty or filled.map(parse_number).isna().mean() < 0.8:
        return df

    repaired = ["STT", "Chỉ tiêu", *cols[1:-1]]
    out = df.copy()
    out.columns = repaired
    return out


def repair_shifted_multilevel_header(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct a legacy-extracted two-row header with a spanned group.

    The old HTML extractor ignored ``rowspan``/``colspan``.  For a source header
    such as ``3 fixed columns | Số cuối năm (span 5) | Số đầu năm``, it emitted
    the five subheaders at columns 0..4 as the first data row and left columns
    5..8 anonymous.  This repair is intentionally structural: it only fires when
    the dimensions, named group/final columns, trailing anonymous columns, and
    a text-only continuation row all agree.
    """
    if df.empty or len(df.columns) < 5:
        return df
    cols = [str(col) for col in df.columns]
    first = [str(value).strip() for value in df.iloc[0]]
    subheaders = [value for value in first if value]
    if len(subheaders) < 2:
        return df
    if first[: len(subheaders)] != subheaders or any(first[len(subheaders) :]):
        return df
    if any(parse_number(value) is not None for value in subheaders):
        return df

    # One final standalone top-level column follows the spanned group.
    group_start = len(cols) - len(subheaders) - 1
    if group_start < 1 or group_start + 1 >= len(cols):
        return df
    group_name = cols[group_start]
    final_name = cols[group_start + 1]
    if not (
        "số cuối" in group_name.casefold()
        and "số đầu" in final_name.casefold()
        and all(col.startswith("Unnamed:") for col in cols[group_start + 2 :])
    ):
        return df

    leaf_columns = [*cols[:group_start], *subheaders, final_name]
    if len({column.casefold() for column in leaf_columns}) == len(leaf_columns):
        # Leaf labels are easier for the planner and retain all semantics when
        # unique. Prefix only when flattening would create ambiguous columns.
        repaired_columns = leaf_columns
    else:
        repaired_columns = [
            *cols[:group_start],
            *(f"{group_name} | {subheader}" for subheader in subheaders),
            final_name,
        ]
    if len(repaired_columns) != len(cols):
        return df
    out = df.iloc[1:].reset_index(drop=True).copy()
    out.columns = repaired_columns
    return out


def load_frame(table_id: str) -> pd.DataFrame:
    """The exact frame the evaluator will see for this table."""
    raw = pd.read_csv(source_csv(table_id), dtype=str, keep_default_na=False)
    repaired = repair_shifted_bank_header(raw)
    repaired = repair_shifted_multilevel_header(repaired)
    return normalize_frame(repaired)


# --------------------------------------------------------------------------- exec

def query_names(query: str) -> set[str]:
    """Free variable names the query reads, so evidence can be checked against it."""
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        tree = ast.parse(query)
    assigned = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    known = set(SAFE_GLOBALS) | set(SAFE_GLOBALS["__builtins__"])
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    } - assigned - known


def run_query(query: str, frames: dict[str, pd.DataFrame]) -> float:
    """eval() the expression form; fall back to exec() + `answer` for statement form.

    The organizer's example is an expression, so an expression is what we emit; the
    fallback exists so a multi-statement draft can still be executed while debugging.
    """
    namespace = dict(frames)
    try:
        result = eval(compile(query, "<query>", "eval"), SAFE_GLOBALS, namespace)
    except SyntaxError:
        exec(compile(query, "<query>", "exec"), SAFE_GLOBALS, namespace)
        if "answer" not in namespace:
            raise ValueError("multi-statement query must assign `answer`")
        result = namespace["answer"]

    if hasattr(result, "item") and getattr(result, "size", 1) == 1:
        result = result.item()
    value = float(result)
    if not math.isfinite(value):
        raise ValueError(f"query returned non-finite {value!r}")
    return value


# --------------------------------------------------------------------------- validate

def validate(item: dict, rel_tol: float = 1e-6) -> list[str]:
    """Every consistency rule the submission format implies. [] means clean."""
    errs: list[str] = []
    add = errs.append

    if not isinstance(item.get("id"), int):
        add("id phải là integer")
    if not isinstance(item.get("question"), str) or not item["question"].strip():
        add("question rỗng")

    docs = item.get("relevant_docs") or []
    tables = item.get("relevant_tables") or []
    evidence = item.get("evidence") or []
    query = item.get("pandas_query") or ""
    if not docs:
        add("relevant_docs rỗng")
    if not tables:
        add("relevant_tables rỗng")
    if not evidence:
        add("evidence rỗng")
    if not query.strip():
        add("pandas_query rỗng")

    table_ids = set()
    for tid in tables:
        if "|" not in tid:
            add(f"relevant_tables sai định dạng: {tid!r}")
            continue
        doc = tid.rsplit("|", 1)[0]
        if doc not in docs:
            add(f"table {tid} thuộc doc không có trong relevant_docs")
        if not source_csv(tid).exists():
            add(f"table {tid} không tồn tại trong corpus")
        table_ids.add(tid)

    frames: dict[str, pd.DataFrame] = {}
    declared: set[str] = set()
    for ev in evidence:
        var, path = ev.get("variable", ""), ev.get("csv_path", "")
        if not var.isidentifier():
            add(f"variable {var!r} không hợp lệ")
        if var in declared:
            add(f"variable {var!r} bị trùng")
        declared.add(var)
        if not path.startswith("data/"):
            add(f"csv_path phải bắt đầu bằng 'data/': {path!r}")
        name = path.split("/")[-1]
        match = [t for t in table_ids if submission_csv_name(t) == name]
        if not match:
            add(f"evidence {name!r} không khớp bất kỳ relevant_tables nào")
            continue
        try:
            frames[var] = load_frame(match[0])
        except Exception as exc:  # noqa: BLE001 - surfaced as a validation error
            add(f"không đọc được CSV của {match[0]}: {exc}")

    used = query_names(query) if query.strip() else set()
    for name in sorted(used - declared):
        add(f"query dùng {name!r} nhưng không có evidence tương ứng")
    for name in sorted(declared - used):
        add(f"evidence khai báo {name!r} nhưng query không dùng")

    if errs:
        return errs
    try:
        value = run_query(query, frames)
    except Exception as exc:  # noqa: BLE001 - the whole point is to report it
        return [f"query chạy lỗi: {type(exc).__name__}: {exc}"]

    answer = item.get("answer")
    if not isinstance(answer, (int, float)) or isinstance(answer, bool):
        add(f"answer phải là số, đang là {answer!r}")
    elif not math.isclose(float(answer), value, rel_tol=rel_tol):
        add(f"answer={answer!r} khác kết quả chạy query={value!r}")
    return errs
