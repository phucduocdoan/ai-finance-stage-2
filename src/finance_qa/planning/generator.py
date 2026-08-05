"""Generate the `pandas_query` for a question from its retrieved tables.

The picked tables are loaded, rendered *in full* into the prompt, and the LLM is
asked for a single pandas expression over them. Three decisions worth stating:

**The whole frame goes in the prompt, not a schema summary.** Tables here are
small (median 8 rows, p90 render 3.2k chars), so 5 picks cost ~6k tokens -- well
inside the 32k window. A schema-only prompt would force the model to guess which
row holds "Doanh thu thuần", which is exactly the step it gets wrong.

**The frame is rendered from `load_frame`, never from `header_flat`.** 71% of
tables have their label column named `Unnamed: 0`, which `header_flat` drops; a
query written against it indexes a column that does not exist.

**`answer` comes from executing the query, never from the LLM.** The two are
scored together, so a model that writes a correct query and then miscopies the
number loses both. Executing makes them consistent by construction.
"""

from __future__ import annotations

import ast
import copy
import json
import re

import pandas as pd

from finance_qa.execution.query import (
    load_frame,
    query_names,
    run_query,
    submission_csv_name,
)
from finance_qa.paths import QUESTION_METADATA_PATH, TABLE_METADATA_PATH
from finance_qa.planning.concepts import binding_concept_errors
from finance_qa.planning.ir import (
    PLAN_PROMPT,
    PLAN_REPAIR,
    binding_alignment_errors,
    compile_plan,
    parse_plan_response,
    prune_unused_bindings,
    repair_binding_alignment,
    repair_binding_column,
    repair_formula_binding_names,
    repair_repeated_select_answers,
    repair_select_answer_years,
    validate_plan,
)
from finance_qa.preprocessing.questions import detect_unit, find_years
from finance_qa.retrieval.judge import call_llm

META_PATH = TABLE_METADATA_PATH
QUESTIONS_PATH = QUESTION_METADATA_PATH

MAX_REPAIRS = 2

# Same budget shape as the judge: keep every table, shrink the biggest first.
# A table truncated to its first rows still names its columns correctly, which is
# what the query needs most.
CTX_TOKENS = 32_768
THINK_TOKENS = 8_192
CHARS_PER_TOKEN = 2.7
ROW_LADDER = (None, 60, 40, 25, 15, 8)

PROMPT = """Bạn viết biểu thức pandas để trả lời một câu hỏi tài chính từ các bảng cho sẵn.

CÂU HỎI: {question}

CÁC BẢNG (đã nạp sẵn thành DataFrame đúng tên biến ghi ở đầu mỗi bảng):
{tables}

Yêu cầu:
- Trả về MỘT biểu thức pandas duy nhất trên một dòng, không gán biến, kết quả là một SỐ.
- Chỉ dùng các biến DataFrame ở trên và `pd`. Không import, không đọc file.
- Các cột số đã được chuẩn hoá thành float (không còn dấu chấm phân cách nghìn).
- Tên cột phải copy CHÍNH XÁC như liệt kê, kể cả tên dạng 'Unnamed: 0' hay 'Số lượng.1'.
- Có thể lấy dòng bằng `.iloc[n]` theo đúng số thứ tự hiển thị ở lề trái bảng.
- Cột `Mã số`, `Thuyết minh`, `TM`, STT hoặc số La Mã thường chỉ là mã tham chiếu,
  KHÔNG phải giá trị tiền. Phải lấy cột số liệu đúng năm/kỳ.
- OCR có thể làm header nhiều dòng bị lệch. Khi một tên cột chứa chữ thay vì
  số, hãy suy ra cột số thực tế từ toàn bộ hàng, các cột `Unnamed:*`, và quan hệ
  cộng/trừ của bảng; không máy móc tin tên header.
- Khi câu hỏi có nhiều công ty, xác định biến df nào ứng với công ty nào bằng
  ticker đầu csv_path (ký tự trước '_' đầu tiên, ví dụ ABB_... → ABB).
  Với "chênh lệch A và B" hoặc "A so với B", tính A_df.value - B_df.value
  theo đúng thứ tự câu hỏi, không phụ thuộc thứ tự evidence.
- Chú ý ĐƠN VỊ: nếu câu hỏi hỏi "triệu đồng"/"tỷ đồng" mà bảng ghi bằng đồng thì phải chia.
- Quy đổi: triệu = chia 1e6, tỷ = chia 1e9, trăm tỷ = chia 1e11,
  nghìn tỷ = chia 1e12. Nếu bảng đã ghi `Triệu đồng` thì không chia lần nữa.
- Tăng trưởng = (mới - cũ) / cũ * 100; giá trị trung bình = tổng / đúng số mốc.
- Tỷ suất lợi nhuận ròng = LNST / doanh thu thuần * 100.
- D/E = nợ phải trả / vốn chủ sở hữu. Khả năng thanh toán lãi vay =
  (lợi nhuận trước thuế + |chi phí lãi vay|) / |chi phí lãi vay|.
- Với câu hỏi lồng nhau (tìm năm lớn nhất rồi lấy chỉ tiêu khác), biểu thức
  phải thực hiện cả bước chọn đó từ các DataFrame, không được nhảy thẳng
  tới con số cuối chỉ vì đã nhìn thấy bảng nào lớn nhất.
  Có thể viết một biểu thức điều kiện dạng
  `(giá_trị_cuối if pd.Series([các_giá_trị], index=[các_năm]).idxmax() == năm_đích
  else float('nan'))` để vừa chứng minh bước argmax vừa trả số cuối.
- Khi hỏi `tổng` của một bảng chi tiết, lấy đúng dòng mang nhãn `Cộng`/`Tổng`;
  không dùng cùng một `.iloc` cho nhiều năm vì số dòng chi tiết có thể thay đổi.

Chỉ in ra JSON, không giải thích:
{{"pandas_query": "..."}}"""

REPAIR = """Biểu thức vừa rồi chạy lỗi.

BIỂU THỨC: {query}
LỖI: {error}

Sửa lại dựa đúng vào các bảng ở trên. Chỉ in ra JSON:
{{"pandas_query": "..."}}"""

VERIFY = """Biểu thức sau đã chạy được, nhưng chạy được chưa có nghĩa là đúng.

BIỂU THỨC: {query}
KẾT QUẢ CHẠY: {answer}

Hãy kiểm tra lại từ đầu theo CÂU HỎI và CÁC BẢNG:
1. Đúng dòng chỉ tiêu, đúng công ty/năm/kỳ và đúng cột giá trị; không lấy nhầm
   `Mã số`, `Thuyết minh`, `TM`, STT hay số La Mã.
2. Đúng phép tính, thứ tự trừ, số mốc khi lấy trung bình, và mọi bước chọn
   trung gian của câu hỏi lồng nhau.
3. Đúng đơn vị đích. Đặc biệt: `trăm tỷ` chia 1e11, `nghìn tỷ` chia 1e12;
   cột đã ghi `Triệu đồng` thì không chia 1e6.
   Nếu câu hỏi nói `trung bình` N mốc thì biểu thức bắt buộc `.mean()` hoặc chia N.
4. Nếu header OCR bị lệch, dùng các giá trị trong hàng và quy luật cộng/trừ để
   xác định cột thực, kể cả khi cột đó mang tên `Unnamed:*`.

Nếu biểu thức đúng thì trả lại nguyên văn; nếu sai thì sửa. Chỉ in JSON:
{{"pandas_query": "..."}}"""


def _captions() -> dict[str, str]:
    """table_id -> one-line title, for the units/context the frame itself omits."""
    caps: dict[str, str] = {}
    with META_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            title = " / ".join(
                x for x in (r.get("section_title"), r.get("note_title")) if x
            )
            caps[f"{r['report_id']}|{r['table_pos']}"] = title
    return caps


_CAPTIONS: dict[str, str] | None = None


def caption(table_id: str) -> str:
    global _CAPTIONS
    if _CAPTIONS is None:
        _CAPTIONS = _captions()
    return _CAPTIONS.get(table_id, "")


def render_tables(
    frames: dict[str, pd.DataFrame], table_ids: dict[str, str], rows: int | None
) -> str:
    blocks = []
    for var, df in frames.items():
        shown = df if rows is None else df.head(rows)
        note = "" if rows is None or len(df) <= rows else f"  ... còn {len(df) - rows} dòng"
        title = caption(table_ids[var])
        year_match = re.search(r"financial_statements_(20\d{2})", table_ids[var])
        period = ""
        if year_match:
            report_year = int(year_match.group(1))
            period = (
                f"  — report_year={report_year}; Năm nay/Số cuối năm≈{report_year}; "
                f"Năm trước/Số đầu năm≈{report_year - 1}"
            )
        blocks.append(
            f"### {var}  ({table_ids[var]}){'  — ' + title if title else ''}{period}\n"
            f"{shown.to_string()}{note}"
        )
    return "\n\n".join(blocks)


def build_prompt(question: str, frames, table_ids) -> str:
    budget = int((CTX_TOKENS - THINK_TOKENS) * CHARS_PER_TOKEN * 0.95)
    for rows in ROW_LADDER:
        prompt = PROMPT.format(
            question=question, tables=render_tables(frames, table_ids, rows)
        )
        if len(prompt) <= budget:
            return prompt
    return prompt


def build_plan_prompt(question: str, frames, table_ids) -> str:
    budget = int((CTX_TOKENS - THINK_TOKENS) * CHARS_PER_TOKEN * 0.95)
    for rows in ROW_LADDER:
        prompt = PLAN_PROMPT.format(
            question=question, tables=render_tables(frames, table_ids, rows)
        )
        if len(prompt) <= budget:
            return prompt
    return prompt


def parse_query(raw: str) -> str:
    """Pull a query from JSON, but never mistake trailing prose for executable code."""
    raw = raw.split("</think>")[-1].strip()
    match = re.search(r'"pandas_query"\s*:\s*("(?:[^"\\]|\\.)*")', raw, re.S)
    if match:
        return json.loads(match.group(1)).strip()
    # A fenced one-line expression is a common harmless format violation. Free-form
    # prose is not: the old "take the last line" fallback submitted sentences such
    # as "But the user's original query tried that and" as pandas code.
    fences = re.findall(r"```(?:python)?\s*(.*?)```", raw, re.S | re.I)
    for body in reversed(fences):
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if len(lines) == 1:
            return lines[0]
    return ""


def _evidence(names: dict[str, str], query: str) -> list[dict[str, str]]:
    """Declare only frames the final query actually reads."""
    used = query_names(query)
    return [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
        if var in used
    ]


def semantic_errors(
    question: str,
    query: str,
    answer: float,
    frames: dict[str, pd.DataFrame],
) -> list[str]:
    """Cheap invariants visible from the question but not from successful eval()."""
    q = question.casefold()
    errors: list[str] = []

    if "trung bình" in q:
        n_points = len(re.findall(r"\b(?:19|20)\d{2}\b", question))
        has_average = ".mean(" in query or "len(" in query
        if n_points > 1:
            has_average = has_average or re.search(
                rf"/\s*(?:float\()?{n_points}(?:\.0)?\)?(?:\D|$)", query
            ) is not None
        if not has_average:
            errors.append(
                f"câu hỏi lấy trung bình {n_points} mốc nhưng query chưa chia {n_points}"
            )

    # A multi-period nested question must compute its intermediate selection.
    # Merely reading the final year's table can coincidentally return the right
    # number on an eval case while encoding none of the question's logic.
    years = find_years(question)
    if len(years) > 1:
        direction = None
        if "cao nhất" in q or "lớn nhất" in q:
            direction = "max"
        elif "thấp nhất" in q or "nhỏ nhất" in q:
            direction = "min"
        if direction and not re.search(
            rf"\.(?:idx)?{direction}\s*\(|\b"
            rf"{'nlargest' if direction == 'max' else 'nsmallest'}\s*\(",
            query,
        ):
            errors.append(
                f"câu hỏi chọn năm có giá trị {direction} nhưng query chưa thực hiện "
                f"phép chọn {direction} trên các năm. "
                f"Phải dùng: formula=\"select(arg{direction}({{'2021': rank_2021, ...}}), "
                f"{{'2021': answer_2021, ...}})\" với rank_* binding chỉ tiêu xếp hạng "
                f"và answer_* binding kết quả câu hỏi."
            )

    return errors


_QUESTION_CONTEXTS: dict[str, dict] | None = None


def question_context(question: str) -> dict:
    global _QUESTION_CONTEXTS
    if _QUESTION_CONTEXTS is None:
        with QUESTIONS_PATH.open(encoding="utf-8") as fh:
            _QUESTION_CONTEXTS = {
                record["question"]: record
                for line in fh
                if (record := json.loads(line))
            }
    return _QUESTION_CONTEXTS.get(question, {})


def plan_order_errors(
    question: str,
    plan: dict,
    table_ids: dict[str, str],
) -> list[str]:
    """Enforce A-B ordering for a two-company difference from enriched entities."""
    if "chênh lệch" not in question.casefold():
        return []
    tickers = question_context(question).get("tickers") or []
    if len(tickers) != 2:
        return []
    try:
        body = ast.parse(plan["formula"], mode="eval").body
    except (KeyError, SyntaxError, TypeError):
        return []
    if not (
        isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Sub)
        and isinstance(body.left, ast.Name)
        and isinstance(body.right, ast.Name)
    ):
        return []
    by_id = {binding.get("id"): binding for binding in plan.get("bindings", [])}
    left = by_id.get(body.left.id, {}).get("variable")
    right = by_id.get(body.right.id, {}).get("variable")
    if left not in table_ids or right not in table_ids:
        return []
    actual = [table_ids[left].split("_", 1)[0], table_ids[right].split("_", 1)[0]]
    if actual == tickers:
        return []
    if actual == list(reversed(tickers)):
        return [
            f"chênh lệch phải theo thứ tự câu hỏi {tickers[0]} - {tickers[1]}, "
            f"formula đang là {actual[0]} - {actual[1]}"
        ]
    return []


def repair_plan_order(
    question: str,
    plan: dict,
    table_ids: dict[str, str],
) -> tuple[dict, str | None]:
    """Swap a direct B-A formula when enriched entity order says A-B."""
    errors = plan_order_errors(question, plan, table_ids)
    if not errors:
        return plan, None
    body = ast.parse(plan["formula"], mode="eval").body
    if not (
        isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Sub)
        and isinstance(body.left, ast.Name)
        and isinstance(body.right, ast.Name)
    ):
        return plan, None
    repaired = copy.deepcopy(plan)
    repaired["formula"] = f"{body.right.id} - {body.left.id}"
    return repaired, errors[0]


def plan_contract_errors(
    question: str,
    plan: dict,
    table_ids: dict[str, str] | None = None,
) -> list[str]:
    """Check plan result shape and multi-period coverage against enriched metadata."""
    context = question_context(question)
    hint = context.get("unit_hint") or detect_unit(question)
    expected_units = {
        "đồng": {"vnd"},
        "triệu": {"million_vnd"},
        "tỷ": {"billion_vnd"},
        "trăm tỷ": {"hundred_billion_vnd"},
        "nghìn tỷ": {"trillion_vnd"},
        "phần trăm": {"percent", "percentage_point"},
        "lần": {"ratio"},
        "count": {"count"},
    }.get(hint)
    errors = []
    output_unit = plan.get("output_unit")
    if expected_units and output_unit not in expected_units:
        errors.append(
            f"output_unit={output_unit!r} không khớp đơn vị câu hỏi {hint!r}; "
            f"phải thuộc {sorted(expected_units)}"
        )

    years = context.get("years") or find_years(question)
    formula = plan.get("formula", "")
    is_multi_period_op = len(years) > 1 and re.search(
        r"\b(argmax|argmin|mean|sum|max|min)(?:_where)?\s*\(", formula
    )
    if is_multi_period_op:
        plan_text = " ".join(
            [formula]
            + [
                f"{binding.get('id', '')} {binding.get('meaning', '')} "
                f"{binding.get('column', '')}"
                for binding in plan.get("bindings", [])
            ]
        )
        missing = [year for year in years if str(year) not in plan_text]
        if missing:
            errors.append(
                "plan chưa bao phủ các năm đã hỏi: "
                + ", ".join(str(year) for year in missing)
            )

    # A binding's claimed year must agree with the report period represented by
    # its selected column. This rejects plans that relabel one 2020 cell as 2016,
    # which otherwise looks syntactically valid and can satisfy a text-only year
    # coverage check.
    if table_ids:
        current_markers = ("năm nay", "số cuối năm", "cuối năm", "cuối kỳ", "kỳ này")
        previous_markers = ("năm trước", "số đầu năm", "đầu năm", "đầu kỳ", "kỳ trước")
        for binding in plan.get("bindings", []):
            if not isinstance(binding, dict):
                continue
            variable = binding.get("variable")
            table_id = table_ids.get(variable, "")
            report_match = re.search(r"financial_statements_(20\d{2})", table_id)
            if not report_match:
                continue
            report_year = int(report_match.group(1))
            column = str(binding.get("column", ""))
            column_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", column)}
            column_folded = column.casefold()
            if len(column_years) == 1:
                inferred_year = next(iter(column_years))
            elif any(marker in column_folded for marker in previous_markers):
                inferred_year = report_year - 1
            elif any(marker in column_folded for marker in current_markers):
                inferred_year = report_year
            else:
                continue
            claimed_text = f"{binding.get('id', '')} {binding.get('meaning', '')}"
            claimed_years = {
                int(year) for year in re.findall(r"\b(20\d{2})\b", claimed_text)
            }
            if claimed_years and inferred_year not in claimed_years:
                errors.append(
                    f"binding {binding.get('id')!r} ghi năm {sorted(claimed_years)} "
                    f"nhưng cột {column!r} của report {report_year} biểu diễn năm "
                    f"{inferred_year}"
                )
    return errors


def repair_plan_output_unit(question: str, plan: dict) -> tuple[dict, str | None]:
    """Use an unambiguous unit stated by the question as the output contract."""
    context = question_context(question)
    hint = context.get("unit_hint") or detect_unit(question)
    expected_units = {
        "đồng": {"vnd"},
        "triệu": {"million_vnd"},
        "tỷ": {"billion_vnd"},
        "trăm tỷ": {"hundred_billion_vnd"},
        "nghìn tỷ": {"trillion_vnd"},
        "phần trăm": {"percent", "percentage_point"},
        "lần": {"ratio"},
        "count": {"count"},
    }.get(hint)
    if not expected_units or len(expected_units) != 1:
        return plan, None
    expected = next(iter(expected_units))
    actual = plan.get("output_unit")
    if actual == expected:
        return plan, None
    repaired = copy.deepcopy(plan)
    repaired["output_unit"] = expected
    return repaired, f"output_unit {actual!r} -> {expected!r} từ đơn vị trong câu hỏi"


def _prior_period_column(frame: pd.DataFrame, current: str, target_year: int) -> str | None:
    explicit = [col for col in frame.columns if str(target_year) in str(col)]
    if len(explicit) == 1:
        return str(explicit[0])
    current_markers = ("năm nay", "số cuối năm", "cuối năm", "cuối kỳ", "kỳ này")
    previous_markers = ("năm trước", "số đầu năm", "đầu năm", "đầu kỳ", "kỳ trước")
    if not any(marker in current.casefold() for marker in current_markers):
        return None
    candidates = [
        str(col)
        for col in frame.columns
        if any(marker in str(col).casefold() for marker in previous_markers)
    ]
    return candidates[0] if len(candidates) == 1 else None


def repair_prior_year_coverage(
    question: str,
    plan: dict,
    frames: dict[str, pd.DataFrame],
) -> tuple[dict, list[str]]:
    """Expand missing rank years from a next-year comparative column.

    This only handles an explicit argmax/argmin dictionary and only clones a
    year when every binding in the next-year expression has one unambiguous
    prior-period column in the same frame.
    """
    years = sorted(set(question_context(question).get("years") or find_years(question)))
    if len(years) < 2 or not isinstance(plan.get("formula"), str):
        return plan, []
    try:
        tree = ast.parse(plan["formula"], mode="eval")
    except SyntaxError:
        return plan, []
    body = tree.body
    selection = body.args[0] if (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "select"
        and body.args
    ) else body
    if not (
        isinstance(selection, ast.Call)
        and isinstance(selection.func, ast.Name)
        and selection.func.id in {"argmax", "argmin"}
        and len(selection.args) == 1
        and isinstance(selection.args[0], ast.Dict)
    ):
        return plan, []
    rank_map = selection.args[0]
    entries: dict[int, ast.AST] = {}
    for key, value in zip(rank_map.keys, rank_map.values):
        if not isinstance(key, ast.Constant) or not str(key.value).isdigit():
            return plan, []
        entries[int(key.value)] = value

    repaired = copy.deepcopy(plan)
    bindings = {binding["id"]: binding for binding in repaired.get("bindings", [])}
    added_bindings = []
    added_years = []
    for target_year in years:
        if target_year in entries or target_year + 1 not in entries:
            continue
        source_year = target_year + 1
        source_expression = copy.deepcopy(entries[source_year])
        replacements: dict[str, str] = {}
        clones = []
        failed = False
        for node in ast.walk(source_expression):
            if not isinstance(node, ast.Name) or node.id not in bindings:
                continue
            source = bindings[node.id]
            frame = frames.get(source.get("variable"))
            if frame is None:
                failed = True
                break
            column = _prior_period_column(frame, str(source.get("column", "")), target_year)
            if column is None:
                failed = True
                break
            new_id = re.sub(
                rf"(?<!\d){source_year}(?!\d)", str(target_year), node.id
            )
            if new_id == node.id:
                new_id = f"{node.id}_{target_year}"
            if new_id in bindings and new_id not in replacements.values():
                failed = True
                break
            clone = copy.deepcopy(source)
            clone["id"] = new_id
            clone["column"] = column
            clone["meaning"] = re.sub(
                rf"(?<!\d){source_year}(?!\d)",
                str(target_year),
                str(source.get("meaning", "")),
            )
            replacements[node.id] = new_id
            clones.append(clone)
        if failed or not replacements:
            continue

        class RenameBindings(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
                replacement = replacements.get(node.id)
                if replacement is None:
                    return node
                return ast.copy_location(ast.Name(id=replacement, ctx=node.ctx), node)

        entries[target_year] = RenameBindings().visit(source_expression)
        for clone in clones:
            bindings[clone["id"]] = clone
            added_bindings.append(clone)
        added_years.append(target_year)

    if not added_years:
        return plan, []
    rank_map.keys = [ast.Constant(str(year)) for year in sorted(entries)]
    rank_map.values = [entries[year] for year in sorted(entries)]
    ast.fix_missing_locations(tree)
    repaired["formula"] = ast.unparse(tree)
    repaired["bindings"].extend(added_bindings)
    return repaired, [
        "expanded prior-year rank coverage: "
        + ", ".join(str(year) for year in added_years)
    ]


def _binding_period_year(binding: dict, table_ids: dict[str, str]) -> int | None:
    table_id = table_ids.get(binding.get("variable"), "")
    report_match = re.search(r"financial_statements_(20\d{2})", table_id)
    if not report_match:
        return None
    report_year = int(report_match.group(1))
    column = str(binding.get("column", ""))
    explicit = {int(year) for year in re.findall(r"\b(20\d{2})\b", column)}
    if len(explicit) == 1:
        return next(iter(explicit))
    folded = column.casefold()
    if any(
        marker in folded
        for marker in ("năm trước", "số đầu năm", "đầu năm", "đầu kỳ", "kỳ trước")
    ):
        return report_year - 1
    if any(
        marker in folded
        for marker in ("năm nay", "số cuối năm", "cuối năm", "cuối kỳ", "kỳ này")
    ):
        return report_year
    return None


def repair_select_answer_periods(
    plan: dict,
    table_ids: dict[str, str],
) -> tuple[dict, list[str]]:
    """Drop answer-map branches contradicted by their actual report columns."""
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
    bindings = {binding.get("id"): binding for binding in plan.get("bindings", [])}
    answer_map = body.args[1]
    keep = []
    removed = []
    for index, (key, value) in enumerate(zip(answer_map.keys, answer_map.values)):
        if not isinstance(key, ast.Constant):
            keep.append(index)
            continue
        key_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", str(key.value))}
        actual_years = {
            year
            for node in ast.walk(value)
            if isinstance(node, ast.Name) and node.id in bindings
            if (year := _binding_period_year(bindings[node.id], table_ids)) is not None
        }
        if key_years and actual_years and key_years.isdisjoint(actual_years):
            removed.append(str(key.value))
        else:
            keep.append(index)
    if not removed or not keep:
        return plan, []
    answer_map.keys = [answer_map.keys[index] for index in keep]
    answer_map.values = [answer_map.values[index] for index in keep]
    repaired = copy.deepcopy(plan)
    repaired["formula"] = ast.unparse(tree)
    return repaired, [
        "removed select branches inconsistent with report periods: "
        + ", ".join(removed)
    ]


def repair_non_numeric_bindings(
    plan: dict,
    frames: dict[str, pd.DataFrame],
    table_ids: dict[str, str],
) -> tuple[dict, list[str]]:
    """Move a non-numeric binding to one unique semantic/period equivalent.

    Three-stage search:
    1. Semantic+period search across all frames (original, requires score >= 3).
    2. If that finds nothing: same search with score >= 1 as last resort.
    3. If still nothing: scan same column ±5 rows for the nearest numeric cell.
       This handles sparse tables where a summary cell is simply blank for one
       column but the adjacent row has the real value.

    The year-in-binding-id gate is relaxed: if no year is claimed we skip the
    period filter so a binding without a year in its meaning can still be repaired
    via stages 2 and 3.
    """
    repaired = copy.deepcopy(plan)
    changes = []
    for binding in repaired.get("bindings", []):
        variable = binding.get("variable")
        row_index = binding.get("row_index")
        column = binding.get("column")
        if variable not in frames or not isinstance(row_index, int):
            continue
        frame = frames[variable]
        if column not in frame.columns or not 0 <= row_index < len(frame):
            continue
        value = frame.iloc[row_index][column]
        if pd.api.types.is_number(value) and not pd.isna(value):
            continue

        claimed_years = {
            int(year)
            for year in re.findall(
                r"\b(20\d{2})\b",
                f"{binding.get('id', '')} {binding.get('meaning', '')}",
            )
        }
        target_year = next(iter(claimed_years)) if len(claimed_years) == 1 else None
        wanted = {
            token
            for token in re.findall(r"\w+", str(binding.get("meaning", "")).casefold())
            if len(token) > 2 and not token.isdigit()
        }

        def _is_numeric(v) -> bool:
            return pd.api.types.is_number(v) and not pd.isna(v)

        # Stage 1 & 2: semantic search across all frames
        candidates: list[tuple[int, str, int, str]] = []
        for candidate_variable, candidate_frame in frames.items():
            row_texts = [
                " ".join(
                    str(item).casefold()
                    for item in row
                    if isinstance(item, str) and item.strip()
                )
                for _, row in candidate_frame.iterrows()
            ]
            row_scores = [len(wanted & set(re.findall(r"\w+", text))) for text in row_texts]
            for candidate_column in candidate_frame.columns:
                cand_binding = {"variable": candidate_variable, "column": str(candidate_column)}
                period = _binding_period_year(cand_binding, table_ids)
                if target_year is not None and period != target_year:
                    continue
                for candidate_row, score in enumerate(row_scores):
                    if score >= 1 and _is_numeric(candidate_frame.iloc[candidate_row][candidate_column]):
                        candidates.append((score, candidate_variable, candidate_row, str(candidate_column)))

        # Filter to score >= 3 first; fall back to score >= 1 if nothing found
        strong = [c for c in candidates if c[0] >= 3]
        pool = strong if strong else candidates

        new_variable, new_row, new_column = variable, row_index, column
        found = False
        if pool:
            best_score = max(c[0] for c in pool)
            best = [c for c in pool if c[0] == best_score]
            # Tie-break: prefer same variable, then closest row
            same_var = [c for c in best if c[1] == variable]
            finalists = same_var if same_var else best
            if len(finalists) == 1:
                _, new_variable, new_row, new_column = finalists[0]
                found = True
            elif len(finalists) > 1:
                # Pick the one nearest the original row_index
                _, new_variable, new_row, new_column = min(
                    finalists, key=lambda c: abs(c[2] - row_index)
                )
                found = True

        # Stage 3: fallback — nearest numeric cell in same column, same frame
        if not found and column in frame.columns:
            for offset in range(1, min(6, len(frame))):
                for candidate_row in (row_index - offset, row_index + offset):
                    if 0 <= candidate_row < len(frame) and _is_numeric(frame.iloc[candidate_row][column]):
                        new_row = candidate_row
                        found = True
                        break
                if found:
                    break

        if found and (new_variable, new_row, new_column) != (variable, row_index, column):
            changes.append(
                f"{binding.get('id')}: non-numeric {variable}.row {row_index} "
                f"-> {new_variable}.row {new_row}, column {new_column!r}"
            )
            binding["variable"] = new_variable
            binding["row_index"] = new_row
            binding["column"] = new_column
    return repaired, changes


def generate(
    question: str,
    table_ids: list[str],
    thinking: bool = False,
    verify: bool = True,
    review_thinking: bool = True,
) -> dict:
    """question + picked tables -> {pandas_query, answer, evidence, error}.

    `error` is non-empty when even the repaired query would not run; the caller
    decides what to submit for that question rather than having that policy here.
    """
    # Sort by table_pos ascending so primary statements (low pos) get df1/df2 and
    # note/breakdown tables (high pos) get later variables. The model consistently
    # trusts earlier-listed frames, and primary statements have the summary totals.
    def _pos(tid: str) -> int:
        try:
            return int(tid.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            return 999
    table_ids = sorted(table_ids, key=_pos)
    names = {f"df{i}": tid for i, tid in enumerate(table_ids, 1)}
    frames = {var: load_frame(tid) for var, tid in names.items()}

    # Primary path: a validated symbolic plan. The model binds cells and writes a
    # formula over binding ids; deterministic code owns pandas generation.
    plan_base = build_plan_prompt(question, frames, names)
    plan_prompt = plan_base
    plan_error = ""
    last_plan = None
    plan_attempts = 0
    for attempt in range(MAX_REPAIRS + 1):
        plan_attempts += 1
        plan_thinking = thinking or attempt == 1
        raw = call_llm(
            plan_prompt,
            thinking=plan_thinking,
            max_tokens=8192 if plan_thinking else 4096,
        )
        plan = parse_plan_response(raw)
        last_plan = plan
        if plan is None:
            errors = ["LLM không trả về JSON plan"]
        else:
            plan_adjustments = []
            plan, changes = repair_formula_binding_names(plan)
            plan_adjustments.extend(changes)
            plan, changes = repair_binding_column(plan, frames)
            plan_adjustments.extend(changes)
            plan, changes = repair_repeated_select_answers(plan)
            plan_adjustments.extend(changes)
            plan, changes = repair_select_answer_years(plan)
            plan_adjustments.extend(changes)
            plan, changes = repair_select_answer_periods(plan, names)
            plan_adjustments.extend(changes)
            plan, changes = prune_unused_bindings(plan)
            plan_adjustments.extend(changes)
            plan, changes = repair_non_numeric_bindings(plan, frames, names)
            plan_adjustments.extend(changes)
            errors = validate_plan(plan, frames)
            if not errors:
                plan, changes = repair_prior_year_coverage(question, plan, frames)
                plan_adjustments.extend(changes)
                errors = validate_plan(plan, frames)
            if not errors:
                plan, changes = repair_binding_alignment(question, plan, frames)
                plan_adjustments.extend(changes)
                errors = binding_alignment_errors(question, plan, frames)
            if not errors:
                errors = binding_concept_errors(question, plan, frames)
            if not errors:
                plan, change = repair_plan_output_unit(question, plan)
                if change:
                    plan_adjustments.append(change)
            if not errors:
                plan, change = repair_plan_order(question, plan, names)
                if change:
                    plan_adjustments.append(change)
                errors = plan_order_errors(question, plan, names)
            if not errors:
                errors = plan_contract_errors(question, plan, names)
            if not errors:
                try:
                    query = compile_plan(plan, frames)
                    answer = run_query(query, frames)
                    errors = semantic_errors(question, query, answer, frames)
                except Exception as exc:  # noqa: BLE001 - sent back for repair
                    errors = [f"{type(exc).__name__}: {exc}"]
        if not errors:
            return {
                "pandas_query": query,
                "answer": answer,
                "evidence": _evidence(names, query),
                "error": "",
                "attempts": plan_attempts,
                "verified": True,
                "planner": True,
                "plan": plan,
                "plan_adjustments": plan_adjustments,
            }
        plan_error = "; ".join(errors)
        plan_prompt = plan_base + "\n\n" + PLAN_REPAIR.format(
            previous_plan=(
                json.dumps(plan, ensure_ascii=False, indent=2)
                if isinstance(plan, dict)
                else "(không parse được plan)"
            ),
            errors="\n".join(f"- {error}" for error in errors)
        )

    # Compatibility fallback while the planner is being evaluated. Keeping this
    # path explicit lets the caller measure planner coverage instead of silently
    # treating a direct-code answer as a successful plan.
    base_prompt = build_prompt(question, frames, names)
    prompt = base_prompt
    query, error = "", "không gọi được LLM"
    attempts = 0
    for attempt in range(MAX_REPAIRS + 1):
        attempts += 1
        call_thinking = thinking or attempt == 1
        raw = call_llm(
            prompt,
            thinking=call_thinking,
            max_tokens=8192 if call_thinking else None,
        )
        query = parse_query(raw)
        if not query:
            error = "LLM không trả về JSON có biểu thức"
            prompt = base_prompt + "\n\n" + REPAIR.format(query="(trống)", error=error)
            continue
        try:
            answer = run_query(query, frames)
            if not (query_names(query) & frames.keys()):
                raise ValueError("query không đọc DataFrame nào")
            issues = semantic_errors(question, query, answer, frames)
            if issues:
                raise ValueError("; ".join(issues))
        except Exception as exc:  # noqa: BLE001 - fed back to the model verbatim
            error = f"{type(exc).__name__}: {exc}"
            prompt = (
                base_prompt
                + "\n\n"
                + REPAIR.format(query=query, error=error)
            )
            continue
        break
    else:
        return {
            "pandas_query": query,
            "answer": 0.0,
            "evidence": _evidence(names, query) if query else [],
            "error": error,
            "attempts": attempts,
            "verified": False,
            "planner": False,
            "planner_error": plan_error,
            "planner_attempts": plan_attempts,
            "failed_plan": last_plan,
        }

    if verify:
        attempts += 1
        review_raw = call_llm(
            base_prompt + "\n\n" + VERIFY.format(query=query, answer=answer),
            thinking=review_thinking,
            max_tokens=8192 if review_thinking else None,
        )
        reviewed_query = parse_query(review_raw)
        if reviewed_query:
            try:
                reviewed_answer = run_query(reviewed_query, frames)
                if not (query_names(reviewed_query) & frames.keys()):
                    raise ValueError("query không đọc DataFrame nào")
            except Exception:
                # A semantic reviewer must not turn an executable draft into a
                # broken submission. Runtime repair already happened above.
                pass
            else:
                query, answer = reviewed_query, reviewed_answer

    return {
        "pandas_query": query,
        "answer": answer,
        "evidence": _evidence(names, query),
        "error": "",
        "attempts": attempts,
        "verified": verify,
        "planner": False,
        "planner_error": plan_error,
        "planner_attempts": plan_attempts,
        "failed_plan": last_plan,
    }
