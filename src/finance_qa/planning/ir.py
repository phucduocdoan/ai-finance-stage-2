"""Validated intermediate representation between a question and pandas code.

The LLM does two jobs only:

1. bind semantic quantities to concrete cells in the retrieved DataFrames;
2. express the calculation over symbolic binding names.

It never writes pandas.  ``compile_plan`` validates every row/column coordinate
and compiles a deliberately small formula language to one pandas expression.
This keeps planning general (lookup through filtered/nested analytics) while
making hallucinated columns and unsafe code fail before execution.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import unicodedata
from typing import Any

import pandas as pd


PLAN_PROMPT = """Bạn lập kế hoạch tính toán để trả lời câu hỏi tài chính từ các DataFrame.

CÂU HỎI: {question}

CÁC BẢNG (số ở lề trái là row_index dùng trong binding):
{tables}

Trả về một JSON object theo schema:
{{
  "bindings": [
    {{
      "id": "tên_gợi_nhớ",
      "variable": "df1",
      "row_index": 0,
      "column": "tên cột chính xác",
      "source_unit": "vnd",
      "meaning": "ý nghĩa ngắn gọn"
    }}
  ],
  "formula": "biểu thức trên các binding",
  "output_unit": "million_vnd",
  "explanation": "một câu kiểm tra logic"
}}

Ngôn ngữ formula:
- Toán tử: +, -, *, /, **; so sánh >, >=, <, <=, ==; `and`, `or`, `not`.
- Hàm scalar/list: abs(x), sum([...]), mean([...]), median([...]), min([...]), max([...]).
- Chọn nhãn: argmax({{"2021": x, "2022": y}}), argmin({{...}}).
- Lấy kết quả theo nhãn: select(key, {{"2021": a, "2022": b}}).
- Lọc: mean_where([values], [conditions]), sum_where, min_where, max_where.
- Argmax có lọc: argmax_where({{"A": x, "B": y}}, {{"A": cond_a, "B": cond_b}})
  (tương tự argmin_where).
- Đếm điều kiện đúng: count_true([conditions]).

Ví dụ cấu trúc (chỉ minh hoạ, không phải dữ liệu câu hỏi):
- lookup đổi ra triệu: bindings=[revenue], formula="revenue", output_unit="million_vnd"
- tăng trưởng: bindings=[old, new], formula="(new - old) / old * 100"
- trung bình tiền tệ: formula="mean([v2021, v2022])", output_unit="billion_vnd"
- lồng argmax rồi lấy chỉ tiêu khác:
  formula="select(argmax({{'2021': rank_2021, '2022': rank_2022}}),
                  {{'2021': answer_2021, '2022': answer_2022}})"

Ràng buộc:
- `id` là snake_case duy nhất. `variable`, `row_index`, `column` phải tồn tại đúng như bảng.
- `row_index` LUÔN là số ở LỀ TRÁI DataFrame (0, 1, 2...), không phải giá trị trong
  cột Mã số. Ví dụ Mã số 300 nằm ở lề trái 0 thì row_index là 0, tuyệt đối không phải 300.
- Mỗi binding phải có `source_unit`: vnd, million_vnd, billion_vnd, percent,
  percentage_point, count, ratio hoặc year.
- Plan phải có `output_unit`: vnd, million_vnd, billion_vnd, hundred_billion_vnd,
  trillion_vnd, percent, percentage_point, count, ratio hoặc year.
- Formula KHÔNG tự chia 1e6/1e9/1e11/1e12. Compiler tự chuẩn hoá tiền về VND từ
  source_unit rồi đổi sang output_unit đúng một lần.
- Cột `Mã số`, `Thuyết minh`, `TM`, STT thường là mã tham chiếu, không phải số tiền.
- Với báo cáo năm Y, các cột `Năm nay`/`Số cuối năm` thường là Y và
  `Năm trước`/`Số đầu năm` thường là Y-1. Phải tận dụng cột so sánh để bao phủ
  đủ mọi năm trong một giai đoạn, không mặc định mỗi bảng chỉ có một năm.
- Chỉ binding những ô thực sự cần. Không chép giá trị ô hoặc đáp án thành hằng số.
- Hằng số trong formula chỉ dùng cho bản thân công thức, ví dụ nhân 100 khi tính
  phần trăm. Không dùng 1e6/1e9/1e11/1e12 để đổi đơn vị tiền trong formula.
- Với câu hỏi lồng/lọc, formula phải thể hiện đủ bước lọc/chọn; không nhảy thẳng tới kết quả.
- `trung bình` phải dùng mean; `tổng` dùng sum; tăng trưởng dùng (mới-cũ)/cũ*100.
- Với "chênh lệch A so với B" hoặc "giữa A và B", giữ thứ tự xuất hiện: A - B.
  Khi câu hỏi có nhiều công ty, xác định df nào ứng với công ty nào bằng ticker
  đầu tên bảng (ký tự trước dấu '_' đầu tiên trong tên bảng hiển thị ở header).
  Đặt `id` binding theo ticker: `acb_revenue_2022`, `mbb_service_net_2022`.
  Điều này giúp kiểm tra thứ tự trừ: binding ticker_A - binding ticker_B.
- Ưu tiên bảng báo cáo chính cho chỉ tiêu tổng hợp: bảng cân đối kế toán,
  báo cáo kết quả kinh doanh, lưu chuyển tiền tệ thường có tiêu đề in hoa như
  "BẢNG CÂN ĐỐI", "KẾT QUẢ KINH DOANH", "LƯU CHUYỂN". Các bảng thuyết minh
  (note) có chỉ tiêu phân tích chi tiết, không phải con số tổng cuối cùng.
  Dấu hiệu bảng note: tiêu đề có "Thuyết minh", "phân tích", nhiều hàng phân mục
  (các loại hình vay, ngành nghề, tài sản thế chấp…), tên cột phức tạp như
  "Giá trị ghi sổ/Số có khả năng trả nợ", "Lãi suất bình quân".
  Khi cùng một chỉ tiêu xuất hiện ở cả bảng chính lẫn bảng note, luôn lấy từ
  bảng chính (tên cột đơn giản: "Số cuối năm", "Năm nay", "31/12/20XX").
- Với bảng phân loại chi tiết (nhiều hàng phân mục con), giá trị tổng hợp
  thường là dòng đầu tiên (row_index=0 hoặc 1) hoặc dòng có nhãn "Cộng"/
  "Tổng cộng". Không dùng row_index của một hàng phân mục làm đại diện tổng.

Formula registry tài chính chung (khi đúng ngữ cảnh báo cáo chính):
- tỷ suất lợi nhuận ròng = LNST / doanh thu thuần * 100 (mã số 60 / 10)
- D/E = nợ phải trả / vốn chủ sở hữu (mã số 300 / 400)
- khả năng thanh toán lãi vay = (lợi nhuận trước thuế + abs(chi phí lãi vay)) /
  abs(chi phí lãi vay) (mã số 50 và 23)
- hệ số thanh toán hiện hành = tài sản ngắn hạn / nợ ngắn hạn (mã số 100 / 310)
- vốn cổ phần = vốn góp của chủ sở hữu/cổ phiếu theo mệnh giá; không phải tổng
  vốn chủ sở hữu và không phải thặng dư vốn cổ phần

Chỉ in JSON, không markdown."""


PLAN_REPAIR = """Kế hoạch vừa rồi không hợp lệ.

KẾ HOẠCH HIỆN TẠI (đã qua các sửa chữa deterministic; giữ nguyên mọi phần
không liên quan trực tiếp tới lỗi):
{previous_plan}

LỖI:
{errors}

Trả về TOÀN BỘ JSON plan sau khi chỉ sửa binding/formula gây lỗi. Không dựng lại
các binding đã hợp lệ và không đổi row/column của phần không bị nêu trong lỗi.
Chỉ in JSON đúng schema."""


SOURCE_UNITS = {
    "vnd",
    "million_vnd",
    "billion_vnd",
    "percent",
    "percentage_point",
    "count",
    "ratio",
    "year",
}

OUTPUT_UNITS = SOURCE_UNITS | {"hundred_billion_vnd", "trillion_vnd"}

SOURCE_MULTIPLIERS = {
    "vnd": 1.0,
    "million_vnd": 1e6,
    "billion_vnd": 1e9,
    "percent": 1.0,
    "percentage_point": 1.0,
    "count": 1.0,
    "ratio": 1.0,
    "year": 1.0,
}

OUTPUT_DIVISORS = {
    "vnd": 1.0,
    "million_vnd": 1e6,
    "billion_vnd": 1e9,
    "hundred_billion_vnd": 1e11,
    "trillion_vnd": 1e12,
    "percent": 1.0,
    "percentage_point": 1.0,
    "count": 1.0,
    "ratio": 1.0,
    "year": 1.0,
}

MONEY_UNITS = {
    "vnd",
    "million_vnd",
    "billion_vnd",
    "hundred_billion_vnd",
    "trillion_vnd",
}
MONEY_SCALES = {1e6, 1e9, 1e11, 1e12}


def parse_plan_response(raw: str) -> dict[str, Any] | None:
    """Find the first JSON object after an optional Qwen think block."""
    raw = raw.split("</think>")[-1].strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            value, _ = decoder.raw_decode(raw[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _formula_names(formula: str) -> set[str]:
    tree = ast.parse(formula, mode="eval")
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _valid_binding_id(value: object) -> bool:
    """Accept lowercase snake_case identifiers, including Vietnamese letters."""
    return (
        isinstance(value, str)
        and value.isidentifier()
        and not value.startswith("_")
        and value == value.casefold()
        and all(char == "_" or char.isalnum() for char in value)
    )


_FUNCTIONS = {
    "abs",
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "argmax",
    "argmin",
    "select",
    "mean_where",
    "sum_where",
    "min_where",
    "max_where",
    "argmax_where",
    "argmin_where",
    "count_true",
    "true",
    "false",
}

_QUESTION_STOPWORDS = {
    "bao",
    "nhiêu",
    "của",
    "trong",
    "ngoài",
    "năm",
    "cuối",
    "đầu",
    "công",
    "ty",
    "ngân",
    "hàng",
    "phần",
    "tính",
    "giữa",
    "với",
    "theo",
    "đơn",
    "đồng",
    "triệu",
    "tỷ",
    "vào",
    "tại",
    "được",
    "là",
}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", text.casefold())
        if len(token) > 2 and token not in _QUESTION_STOPWORDS
    }


def _binding_tokens(
    question_tokens: set[str], binding: dict[str, Any], row_texts: list[str]
) -> set[str]:
    """Prefer a concrete binding meaning; fall back to the broader question.

    Combining both vocabularies makes sibling components contaminate each
    other.  For net margin, question words about ``lợi nhuận`` made the revenue
    binding prefer a profit row.  A meaning is useful only when at least two of
    its tokens occur together in some row; generic meanings such as ``value
    2024`` therefore retain question-based matching.
    """
    meaning_tokens = _tokens(str(binding.get("meaning", "")))
    best_meaning_overlap = max(
        (len(meaning_tokens & _tokens(text)) for text in row_texts), default=0
    )
    return meaning_tokens if best_meaning_overlap >= 2 else question_tokens


def binding_alignment_errors(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> list[str]:
    """Flag a selected row when another row matches the question much better.

    This is an audit signal, not an automatic rewrite. It catches semantic slips
    such as selecting "Thu nhập lãi thuần" when the question says "Lãi thuần từ
    hoạt động dịch vụ", then gives the planner concrete alternative row indices.
    Derived metrics whose row labels are absent from the question are left alone.
    """
    question_tokens = _tokens(question)
    if not question_tokens:
        return []
    errors = []
    for binding in plan.get("bindings", []):
        if not isinstance(binding, dict) or binding.get("variable") not in frames:
            continue
        row_index = binding.get("row_index")
        df = frames[binding["variable"]]
        if not isinstance(row_index, int) or not 0 <= row_index < len(df):
            continue
        row_texts = [
            " ".join(str(value) for value in row if isinstance(value, str))
            for _, row in df.iterrows()
        ]
        wanted = _binding_tokens(question_tokens, binding, row_texts)
        selected_text = row_texts[row_index]
        if "tổng" in question.casefold() and selected_text.strip().casefold() in {"cộng", "tổng"}:
            continue
        scores = [len(wanted & _tokens(text)) for text in row_texts]
        selected_score = scores[row_index]
        best_score = max(scores, default=0)
        if best_score < 3 or best_score < selected_score + 2:
            continue
        alternatives = sorted(range(len(df)), key=lambda pos: scores[pos], reverse=True)[:3]
        rendered = "; ".join(
            f"row {pos} (score {scores[pos]}): {row_texts[pos][:120]!r}"
            for pos in alternatives
        )
        errors.append(
            f"binding {binding.get('id')!r} chọn row {row_index} chỉ khớp "
            f"{selected_score} từ, có dòng khớp {best_score} từ: {rendered}"
        )
    return errors


def repair_binding_alignment(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], list[str]]:
    """Move a binding only when one alternative row is uniquely much stronger."""
    question_tokens = _tokens(question)
    repaired = copy.deepcopy(plan)
    changes = []
    for binding in repaired.get("bindings", []):
        if not isinstance(binding, dict) or binding.get("variable") not in frames:
            continue
        row_index = binding.get("row_index")
        df = frames[binding["variable"]]
        if not isinstance(row_index, int) or not 0 <= row_index < len(df):
            continue
        row_texts = [
            " ".join(str(value) for value in row if isinstance(value, str))
            for _, row in df.iterrows()
        ]
        wanted = _binding_tokens(question_tokens, binding, row_texts)
        selected_text = row_texts[row_index]
        if "tổng" in question.casefold() and selected_text.strip().casefold() in {"cộng", "tổng"}:
            continue
        scores = [len(wanted & _tokens(text)) for text in row_texts]
        best_score = max(scores, default=0)
        best_rows = [pos for pos, score in enumerate(scores) if score == best_score]
        if (
            len(best_rows) == 1
            and best_score >= 3
            and best_score >= scores[row_index] + 2
        ):
            best = best_rows[0]
            changes.append(
                f"{binding.get('id')}: row {row_index} -> {best} "
                f"(lexical score {scores[row_index]} -> {best_score})"
            )
            binding["row_index"] = best
    return repaired, changes


def repair_binding_column(
    plan: dict[str, Any], frames: dict[str, pd.DataFrame]
) -> tuple[dict[str, Any], list[str]]:
    """Rebind a column the model named by its leaf to the flattened header.

    `load_frame` joins a hierarchical header with ' | ' (e.g. a "Số cuối năm"
    group over a "Số cuối năm" closing column becomes 'Số cuối năm | Số cuối
    năm'), but the model names the leaf it reads off the page ('Số cuối năm').
    Exact-match validation then rejects the binding and the whole plan falls back
    to unguarded direct code, losing the unit and order repairs.

    Only rebind when exactly one column carries that leaf: an ambiguous leaf is a
    real choice the model must make, so it is left to fail into the repair loop
    rather than guessed here.
    """
    repaired = copy.deepcopy(plan)
    bindings = repaired.get("bindings")
    if not isinstance(bindings, list):
        return plan, []
    changes = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        variable = binding.get("variable")
        column = binding.get("column")
        if variable not in frames or not isinstance(column, str):
            continue
        df = frames[variable]
        if column in df.columns:
            continue
        want = column.strip().casefold()
        matches = [
            c
            for c in df.columns
            if isinstance(c, str) and c.rsplit(" | ", 1)[-1].strip().casefold() == want
        ]
        if len(matches) == 1:
            changes.append(
                f"{binding.get('id')}: column {column!r} -> {matches[0]!r} (leaf match)"
            )
            binding["column"] = matches[0]
    return repaired, changes


def prune_unused_bindings(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove planner scratch bindings that the final symbolic formula does not use."""
    formula = plan.get("formula")
    if not isinstance(formula, str):
        return plan, []
    try:
        used = _formula_names(formula)
    except SyntaxError:
        return plan, []
    repaired = copy.deepcopy(plan)
    before = repaired.get("bindings", [])
    if not isinstance(before, list):
        return plan, []
    after = [binding for binding in before if binding.get("id") in used]
    removed = [binding.get("id") for binding in before if binding.get("id") not in used]
    repaired["bindings"] = after
    return repaired, [f"removed unused binding {binding_id}" for binding_id in removed]


def _fold_identifier(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    ).casefold()


def repair_formula_binding_names(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Resolve formula/binding identifiers that differ only by diacritics."""
    formula = plan.get("formula")
    if not isinstance(formula, str):
        return plan, []
    binding_ids = {
        binding.get("id")
        for binding in plan.get("bindings", [])
        if isinstance(binding.get("id"), str)
    }
    by_folded: dict[str, list[str]] = {}
    for binding_id in binding_ids:
        by_folded.setdefault(_fold_identifier(binding_id), []).append(binding_id)
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return plan, []

    changes = []

    class NameRepair(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
            if node.id in binding_ids or node.id in _FUNCTIONS:
                return node
            candidates = by_folded.get(_fold_identifier(node.id), [])
            if len(candidates) != 1:
                return node
            replacement = candidates[0]
            changes.append(f"formula id {node.id!r} -> {replacement!r}")
            return ast.copy_location(ast.Name(id=replacement, ctx=node.ctx), node)

    repaired_tree = NameRepair().visit(tree)
    if not changes:
        return plan, []
    ast.fix_missing_locations(repaired_tree)
    repaired = copy.deepcopy(plan)
    repaired["formula"] = ast.unparse(repaired_tree)
    return repaired, changes


def repair_repeated_select_answers(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Turn a repeated answer map into an assertion for its claimed period.

    ``select(argmax(ranks), {'2017': answer_2022, ..., '2022': answer_2022})``
    only pretends to depend on argmax.  If every answer expression is identical
    and its bindings claim exactly one year, retain only that key.  Selection
    then succeeds only when the computed key is genuinely that year.
    """
    formula = plan.get("formula")
    if not isinstance(formula, str):
        return plan, []
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return plan, []
    body = tree.body
    if not (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "select"
        and len(body.args) == 2
        and isinstance(body.args[1], ast.Dict)
        and len(body.args[1].values) > 1
    ):
        return plan, []
    answer_map = body.args[1]
    dumps = {ast.dump(value, include_attributes=False) for value in answer_map.values}
    if len(dumps) != 1:
        return plan, []

    by_id = {binding.get("id"): binding for binding in plan.get("bindings", [])}
    answer_names = {
        node.id for node in ast.walk(answer_map.values[0]) if isinstance(node, ast.Name)
    }
    claimed_years = {
        int(year)
        for name in answer_names
        for year in re.findall(
            r"\b(20\d{2})\b",
            f"{name} {by_id.get(name, {}).get('meaning', '')}",
        )
    }
    if len(claimed_years) != 1:
        return plan, []
    claimed_key = str(next(iter(claimed_years)))
    matching = [
        index
        for index, key in enumerate(answer_map.keys)
        if isinstance(key, ast.Constant) and str(key.value) == claimed_key
    ]
    if len(matching) != 1:
        return plan, []
    index = matching[0]
    answer_map.keys = [answer_map.keys[index]]
    answer_map.values = [answer_map.values[index]]
    repaired = copy.deepcopy(plan)
    repaired["formula"] = ast.unparse(tree)
    return repaired, [f"select answer map restricted to claimed year {claimed_key}"]


def _expression_claimed_years(
    expression: ast.AST, bindings: dict[str, dict[str, Any]]
) -> set[int]:
    names = {node.id for node in ast.walk(expression) if isinstance(node, ast.Name)}
    return {
        int(year)
        for name in names
        for year in re.findall(
            r"\b(20\d{2})\b",
            f"{name} {bindings.get(name, {}).get('meaning', '')}",
        )
    }


def repair_select_answer_years(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Drop select branches whose key contradicts the answer binding period."""
    formula = plan.get("formula")
    if not isinstance(formula, str):
        return plan, []
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return plan, []
    body = tree.body
    if not (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "select"
        and len(body.args) == 2
        and isinstance(body.args[1], ast.Dict)
    ):
        return plan, []
    bindings = {
        binding.get("id"): binding
        for binding in plan.get("bindings", [])
        if isinstance(binding, dict)
    }
    answer_map = body.args[1]
    keep = []
    removed = []
    for index, (key, value) in enumerate(zip(answer_map.keys, answer_map.values)):
        if not isinstance(key, ast.Constant):
            keep.append(index)
            continue
        key_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", str(key.value))}
        claimed_years = _expression_claimed_years(value, bindings)
        if key_years and claimed_years and key_years.isdisjoint(claimed_years):
            removed.append(str(key.value))
        else:
            keep.append(index)
    if not removed or not keep:
        return plan, []
    answer_map.keys = [answer_map.keys[index] for index in keep]
    answer_map.values = [answer_map.values[index] for index in keep]
    repaired = copy.deepcopy(plan)
    repaired["formula"] = ast.unparse(tree)
    return repaired, ["removed select branches with mismatched answer years: " + ", ".join(removed)]


def _selection_dependency_errors(
    tree: ast.AST, bindings: dict[str, dict[str, Any]]
) -> list[str]:
    """Reject a select whose many branches are the identical expression."""
    body = tree.body if isinstance(tree, ast.Expression) else tree
    if not (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "select"
        and len(body.args) == 2
        and isinstance(body.args[1], ast.Dict)
        and len(body.args[1].values) > 1
    ):
        return []
    values = {
        ast.dump(value, include_attributes=False) for value in body.args[1].values
    }
    errors = []
    if len(values) == 1:
        errors.append(
            "select map lặp cùng một đáp án cho mọi key nên kết quả không thực sự "
            "phụ thuộc bước chọn"
        )
    for key, value in zip(body.args[1].keys, body.args[1].values):
        if not isinstance(key, ast.Constant):
            continue
        key_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", str(key.value))}
        claimed_years = _expression_claimed_years(value, bindings)
        if key_years and claimed_years and key_years.isdisjoint(claimed_years):
            errors.append(
                f"select key {key.value!r} dùng đáp án được binding gắn năm "
                f"{sorted(claimed_years)}"
            )
    return errors


def _numeric_constant(node: ast.AST) -> float | None:
    """Return a literal number without evaluating names or arbitrary syntax."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if not isinstance(node.value, bool):
            return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _numeric_constant(node.operand)
        if value is not None:
            return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        base = _numeric_constant(node.left)
        exponent = _numeric_constant(node.right)
        if base is not None and exponent is not None:
            try:
                return base**exponent
            except (OverflowError, ZeroDivisionError):
                return None
    return None


def _formula_unit_conversion_errors(tree: ast.AST, output_unit: object) -> list[str]:
    """Reject currency scaling that would duplicate compiler conversion."""
    if output_unit not in MONEY_UNITS:
        return []
    reciprocal_scales = {1 / scale for scale in MONEY_SCALES}
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        if isinstance(node.op, ast.Div):
            divisor = _numeric_constant(node.right)
            if divisor is not None and abs(divisor) in MONEY_SCALES:
                return [
                    "formula tự đổi đơn vị tiền; compiler đã chuẩn hoá source_unit "
                    "và output_unit"
                ]
        if isinstance(node.op, ast.Mult):
            constants = {
                abs(value)
                for child in (node.left, node.right)
                if (value := _numeric_constant(child)) is not None
            }
            if constants & (MONEY_SCALES | reciprocal_scales):
                return [
                    "formula tự đổi đơn vị tiền; compiler đã chuẩn hoá source_unit "
                    "và output_unit"
                ]
    return []


def validate_plan(plan: object, frames: dict[str, pd.DataFrame]) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan phải là JSON object"]
    bindings = plan.get("bindings")
    formula = plan.get("formula")
    output_unit = plan.get("output_unit")
    if not isinstance(bindings, list) or not bindings:
        errors.append("bindings phải là list không rỗng")
        bindings = []
    if not isinstance(formula, str) or not formula.strip():
        errors.append("formula phải là string không rỗng")
        formula = ""
    if output_unit not in OUTPUT_UNITS:
        errors.append(f"output_unit không hợp lệ: {output_unit!r}")

    ids: set[str] = set()
    for i, binding in enumerate(bindings):
        prefix = f"bindings[{i}]"
        if not isinstance(binding, dict):
            errors.append(f"{prefix} phải là object")
            continue
        binding_id = binding.get("id")
        variable = binding.get("variable")
        row = binding.get("row_index")
        column = binding.get("column")
        source_unit = binding.get("source_unit")
        if not _valid_binding_id(binding_id):
            errors.append(f"{prefix}.id không phải snake_case hợp lệ")
        elif binding_id in ids:
            errors.append(f"binding id bị trùng: {binding_id}")
        else:
            ids.add(binding_id)
        if variable not in frames:
            errors.append(f"{prefix}.variable không tồn tại: {variable!r}")
            continue
        df = frames[variable]
        if not isinstance(row, int) or isinstance(row, bool) or not 0 <= row < len(df):
            errors.append(f"{prefix}.row_index ngoài phạm vi 0..{len(df) - 1}: {row!r}")
        if not isinstance(column, str) or column not in df.columns:
            errors.append(f"{prefix}.column không tồn tại trong {variable}: {column!r}")
        elif isinstance(row, int) and not isinstance(row, bool) and 0 <= row < len(df):
            value = df.iloc[row][column]
            if not pd.api.types.is_number(value) or pd.isna(value):
                errors.append(
                    f"{prefix} trỏ tới ô không phải số: "
                    f"{variable}.iloc[{row}][{column!r}]={value!r}"
                )
        if source_unit not in SOURCE_UNITS:
            errors.append(f"{prefix}.source_unit không hợp lệ: {source_unit!r}")
        elif (
            isinstance(column, str)
            and "triệu" in column.casefold()
            and source_unit != "million_vnd"
        ):
            errors.append(
                f"{prefix}.column ghi Triệu nhưng source_unit={source_unit!r}, "
                "phải là 'million_vnd'"
            )

    if formula:
        try:
            tree = ast.parse(formula, mode="eval")
            names = {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            }
        except SyntaxError as exc:
            errors.append(f"formula sai cú pháp: {exc.msg}")
        else:
            unknown = names - ids - _FUNCTIONS
            if unknown:
                errors.append("formula dùng tên không khai báo: " + ", ".join(sorted(unknown)))
            used = names & ids
            if not used:
                errors.append("formula không dùng binding nào")
            unused = ids - used
            if unused:
                errors.append("bindings không được formula dùng: " + ", ".join(sorted(unused)))
            errors.extend(_formula_unit_conversion_errors(tree, output_unit))
            errors.extend(_selection_dependency_errors(tree, {b["id"]: b for b in bindings if isinstance(b.get("id"), str)}))
    return errors


class _Compiler:
    """Compile the small symbolic formula language; reject every other AST node."""

    def __init__(self, bindings: dict[str, dict[str, Any]]):
        self.bindings = bindings

    def compile(self, node: ast.AST) -> str:
        method = getattr(self, f"c_{type(node).__name__}", None)
        if method is None:
            raise ValueError(f"formula không cho phép {type(node).__name__}")
        return method(node)

    def c_Expression(self, node: ast.Expression) -> str:
        return self.compile(node.body)

    def c_Name(self, node: ast.Name) -> str:
        if node.id == "true":
            return "True"
        if node.id == "false":
            return "False"
        if node.id not in self.bindings:
            raise ValueError(f"tên không phải binding: {node.id}")
        binding = self.bindings[node.id]
        cell = (
            f"{binding['variable']}.iloc[{binding['row_index']}]"
            f"[{binding['column']!r}]"
        )
        multiplier = SOURCE_MULTIPLIERS[binding["source_unit"]]
        return cell if multiplier == 1 else f"({cell} * {multiplier!r})"

    def c_Constant(self, node: ast.Constant) -> str:
        if not isinstance(node.value, (str, int, float, bool)):
            raise ValueError(f"hằng số không được phép: {node.value!r}")
        return repr(node.value)

    def c_List(self, node: ast.List) -> str:
        return "[" + ", ".join(self.compile(x) for x in node.elts) + "]"

    def c_Tuple(self, node: ast.Tuple) -> str:
        return "[" + ", ".join(self.compile(x) for x in node.elts) + "]"

    def c_Dict(self, node: ast.Dict) -> str:
        pairs = [
            f"{self.compile(key)}: {self.compile(value)}"
            for key, value in zip(node.keys, node.values)
            if key is not None
        ]
        if len(pairs) != len(node.values):
            raise ValueError("dict unpack không được phép")
        return "{" + ", ".join(pairs) + "}"

    _BINOPS = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.Pow: "**",
        ast.Mod: "%",
    }

    def c_BinOp(self, node: ast.BinOp) -> str:
        symbol = self._BINOPS.get(type(node.op))
        if symbol is None:
            raise ValueError(f"toán tử không được phép: {type(node.op).__name__}")
        return f"({self.compile(node.left)} {symbol} {self.compile(node.right)})"

    def c_UnaryOp(self, node: ast.UnaryOp) -> str:
        symbols = {ast.UAdd: "+", ast.USub: "-", ast.Not: "not "}
        symbol = symbols.get(type(node.op))
        if symbol is None:
            raise ValueError(f"toán tử một ngôi không được phép: {type(node.op).__name__}")
        return f"({symbol}{self.compile(node.operand)})"

    def c_BoolOp(self, node: ast.BoolOp) -> str:
        symbol = " and " if isinstance(node.op, ast.And) else " or "
        return "(" + symbol.join(self.compile(x) for x in node.values) + ")"

    _CMPOPS = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    def c_Compare(self, node: ast.Compare) -> str:
        parts = [self.compile(node.left)]
        for op, comparator in zip(node.ops, node.comparators):
            symbol = self._CMPOPS.get(type(op))
            if symbol is None:
                raise ValueError(f"so sánh không được phép: {type(op).__name__}")
            parts.extend((symbol, self.compile(comparator)))
        return "(" + " ".join(parts) + ")"

    @staticmethod
    def _series(value: str, dtype: str = "float") -> str:
        return f"pd.Series({value}, dtype={dtype!r})"

    def c_Call(self, node: ast.Call) -> str:
        if node.keywords or not isinstance(node.func, ast.Name):
            raise ValueError("chỉ cho phép gọi hàm tên đơn giản, không có keyword")
        name = node.func.id
        args = [self.compile(arg) for arg in node.args]
        if name == "abs" and len(args) == 1:
            return f"abs({args[0]})"
        if name in {"sum", "mean", "median", "min", "max"} and len(args) == 1:
            method = {"min": "min", "max": "max"}.get(name, name)
            return f"{self._series(args[0])}.{method}()"
        if name in {"argmax", "argmin"} and len(args) == 1:
            method = "idxmax" if name == "argmax" else "idxmin"
            return f"{self._series(args[0])}.{method}()"
        if name == "select" and len(args) == 2:
            return f"{self._series(args[1])}.loc[{args[0]}]"
        if name == "count_true" and len(args) == 1:
            return f"{self._series(args[0], 'bool')}.sum()"
        if name in {"mean_where", "sum_where", "min_where", "max_where"} and len(args) == 2:
            method = name.removesuffix("_where")
            values = self._series(args[0])
            mask = self._series(args[1], "bool")
            return f"{values}[{mask}].{method}()"
        if name in {"argmax_where", "argmin_where"} and len(args) == 2:
            method = "idxmax" if name == "argmax_where" else "idxmin"
            values = self._series(args[0])
            mask = self._series(args[1], "bool")
            return f"{values}[{mask}].{method}()"
        raise ValueError(f"hàm hoặc số đối số không hợp lệ: {name}/{len(args)}")


def compile_plan(plan: dict[str, Any], frames: dict[str, pd.DataFrame]) -> str:
    errors = validate_plan(plan, frames)
    if errors:
        raise ValueError("; ".join(errors))
    bindings = {binding["id"]: binding for binding in plan["bindings"]}
    tree = ast.parse(plan["formula"], mode="eval")
    expression = _Compiler(bindings).compile(tree)
    divisor = OUTPUT_DIVISORS[plan["output_unit"]]
    return expression if divisor == 1 else f"({expression} / {divisor!r})"
