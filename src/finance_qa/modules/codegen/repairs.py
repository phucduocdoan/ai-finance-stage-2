"""Deterministic repair passes that fix common planner mistakes.

Each function takes a plan dict (and optionally frames/table_ids) and returns
(repaired_plan, list_of_change_descriptions).  They never raise; a plan that
cannot be repaired is returned unchanged with an empty change list.
"""

from __future__ import annotations

import ast
import copy
import re
import unicodedata
from typing import Any

import pandas as pd

from finance_qa.modules.codegen.table_profile import (
    _AGG_LABELS,
    _CURRENT_COL_MARKERS,
    _PRIOR_COL_MARKERS,
)
from finance_qa.modules.codegen.ir import (
    OUTPUT_DIVISORS,
    SOURCE_MULTIPLIERS,
    UNIT_HINT_MAP,
    _FUNCTIONS,
    _formula_names,
    question_context,
)
from finance_qa.modules.data.preprocessing.questions import detect_unit, find_years
from finance_qa.modules.tools.numeric import parse_number


# ---------------------------------------------------------------------------
# Column-name repairs
# ---------------------------------------------------------------------------

_UNIT_SUFFIX_RE = re.compile(
    r"\s*(?:VND|Triệu VND|Nghìn VND|Tỷ VND|Triệu đồng|Nghìn đồng|%/năm|/năm)\s*$",
    re.IGNORECASE,
)


def _col_key(col: str) -> str:
    """Strip trailing unit annotation, collapse whitespace, casefold."""
    return re.sub(r"\s+", " ", _UNIT_SUFFIX_RE.sub("", col).strip()).casefold()


def repair_binding_column(
    plan: dict[str, Any], frames: dict[str, pd.DataFrame]
) -> tuple[dict[str, Any], list[str]]:
    """Rebind a column the model named by its leaf to the flattened header.

    Three matching passes, each only applied when exactly one column matches:
    1. Leaf exact match.
    2. Full-name unit-normalised match.
    3. Leaf unit-normalised match.
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

        str_cols = [c for c in df.columns if isinstance(c, str)]
        want_exact = column.strip().casefold()

        matches = [c for c in str_cols if c.rsplit(" | ", 1)[-1].strip().casefold() == want_exact]
        label = "leaf match"

        if len(matches) != 1:
            want_key = _col_key(column)
            matches = [c for c in str_cols if _col_key(c) == want_key]
            label = "unit-norm match"

        if len(matches) != 1:
            want_leaf_key = _col_key(column.rsplit(" | ", 1)[-1])
            matches = [c for c in str_cols if _col_key(c.rsplit(" | ", 1)[-1]) == want_leaf_key]
            label = "leaf unit-norm match"

        if len(matches) == 1:
            changes.append(f"{binding.get('id')}: column {column!r} -> {matches[0]!r} ({label})")
            binding["column"] = matches[0]
    return repaired, changes


# ---------------------------------------------------------------------------
# Formula / binding-id repairs
# ---------------------------------------------------------------------------

def _fold_identifier(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    return "".join(
        char for char in unicodedata.normalize("NFKD", value)
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

    changes: list[str] = []

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


def prune_unused_bindings(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove bindings the formula does not reference."""
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
    after = [b for b in before if b.get("id") in used]
    removed = [b.get("id") for b in before if b.get("id") not in used]
    repaired["bindings"] = after
    return repaired, [f"removed unused binding {bid}" for bid in removed]


# ---------------------------------------------------------------------------
# Select / argmax repairs
# ---------------------------------------------------------------------------

def _expression_claimed_years(
    expression: ast.AST, bindings: dict[str, dict[str, Any]]
) -> set[int]:
    names = {node.id for node in ast.walk(expression) if isinstance(node, ast.Name)}
    return {
        int(year)
        for name in names
        for year in re.findall(
            r"(?<!\d)(20\d{2})(?!\d)",
            f"{name} {bindings.get(name, {}).get('meaning', '')}",
        )
    }


def repair_repeated_select_answers(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Collapse a select map where every branch has the identical expression."""
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
        index for index, key in enumerate(answer_map.keys)
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


def repair_select_answer_periods(
    plan: dict[str, Any],
    table_ids: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
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
        "removed select branches inconsistent with report periods: " + ", ".join(removed)
    ]


# ---------------------------------------------------------------------------
# Binding alignment repairs (token-based row matching)
# ---------------------------------------------------------------------------

_QUESTION_STOPWORDS = {
    "bao", "nhiêu", "của", "trong", "ngoài", "năm", "cuối", "đầu",
    "công", "ty", "ngân", "hàng", "phần", "tính", "giữa", "với",
    "theo", "đơn", "đồng", "triệu", "tỷ", "vào", "tại", "được", "là",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"\w+", text.casefold())
        if len(token) > 2 and token not in _QUESTION_STOPWORDS
    }


def _binding_tokens(
    question_tokens: set[str], binding: dict[str, Any], row_texts: list[str]
) -> set[str]:
    meaning_tokens = _tokens(str(binding.get("meaning", "")))
    best_meaning_overlap = max(
        (len(meaning_tokens & _tokens(text)) for text in row_texts), default=0
    )
    return meaning_tokens if best_meaning_overlap >= 2 else question_tokens


def binding_alignment_errors(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    indicator: str = "",
) -> list[str]:
    """Flag a selected row when another row matches the question much better."""
    question_tokens = _tokens(indicator) if indicator else _tokens(question)
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
        if any(t in question.casefold() for t in ("tổng cộng", "tổng", "cộng")) \
                and selected_text.strip().casefold() in _AGG_LABELS:
            continue
        column = binding.get("column")
        scores = [len(wanted & _tokens(text)) for text in row_texts]
        selected_score = scores[row_index]
        # Only consider rows that have a numeric value in the same column as true alternatives.
        # A non-numeric row (section header) with a higher lexical score is not a valid
        # alternative — repair_binding_alignment already refuses to move there (F8).
        def _row_is_numeric(pos: int) -> bool:
            if column not in df.columns:
                return False
            v = df.iloc[pos][column]
            return bool(pd.api.types.is_number(v) and not pd.isna(v))

        numeric_scores = [s if _row_is_numeric(i) else 0 for i, s in enumerate(scores)]
        best_score = max(numeric_scores, default=0)
        cross_candidates: list[tuple[int, str, int, str]] = []
        for cand_var, cand_df in frames.items():
            if cand_var == binding["variable"] or column not in cand_df.columns:
                continue
            for cand_row, cand_series in cand_df.iterrows():
                cand_value = cand_series[column]
                if not (pd.api.types.is_number(cand_value) and not pd.isna(cand_value)):
                    continue
                cand_text = " ".join(str(value) for value in cand_series if isinstance(value, str))
                score = len(wanted & _tokens(cand_text))
                if score > best_score:
                    cross_candidates = [(score, cand_var, cand_row, cand_text)]
                    best_score = score
                elif score == best_score and score > 0:
                    cross_candidates.append((score, cand_var, cand_row, cand_text))
        if best_score < 3 or best_score < selected_score + 2:
            continue
        alternatives = sorted(
            [i for i in range(len(df)) if _row_is_numeric(i)],
            key=lambda pos: scores[pos], reverse=True
        )[:3]
        rendered_parts = [
            f"row {pos} (score {scores[pos]}): {row_texts[pos][:120]!r}"
            for pos in alternatives
        ]
        rendered_parts.extend(
            f"{var}.row {pos} (score {score}): {text[:120]!r}"
            for score, var, pos, text in cross_candidates[:3]
        )
        rendered = "; ".join(rendered_parts)
        errors.append(
            f"binding {binding.get('id')!r} chọn row {row_index} chỉ khớp "
            f"{selected_score} từ, có dòng khớp {best_score} từ: {rendered}"
        )
    return errors


def repair_binding_alignment(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    indicator: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Move a binding only when one alternative row is uniquely much stronger."""
    question_tokens = _tokens(indicator) if indicator else _tokens(question)
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
        # Skip alignment check when the question asks for a total and the selected row IS a total row
        question_wants_total = any(t in question.casefold() for t in ("tổng cộng", "tổng", "cộng"))
        if question_wants_total and selected_text.strip().casefold() in _AGG_LABELS:
            continue
        scores = [len(wanted & _tokens(text)) for text in row_texts]
        best_score = max(scores, default=0)
        best_rows = [(binding["variable"], pos) for pos, score in enumerate(scores) if score == best_score]
        selected_score = scores[row_index]
        column = binding.get("column")
        for cand_var, cand_df in frames.items():
            if cand_var == binding["variable"] or column not in cand_df.columns:
                continue
            for cand_row, cand_series in cand_df.iterrows():
                cand_value = cand_series[column]
                if not (pd.api.types.is_number(cand_value) and not pd.isna(cand_value)):
                    continue
                cand_text = " ".join(str(value) for value in cand_series if isinstance(value, str))
                score = len(wanted & _tokens(cand_text))
                if score > best_score:
                    best_score = score
                    best_rows = [(cand_var, cand_row)]
                elif score == best_score:
                    best_rows.append((cand_var, cand_row))
        unique_winner = len(best_rows) == 1 and best_score >= 3 and best_score >= selected_score + 2
        # When selected row matches nothing (score=0), any clearly better row wins even if tied
        clear_miss = selected_score == 0 and best_score >= 3
        if unique_winner or clear_miss:
            best_var, best = min(
                best_rows,
                key=lambda item: (item[0] != binding["variable"], abs(item[1] - row_index), item[1]),
            )
            # Don't move to a row with no numeric value in the target column — repair_non_numeric
            # already moved the binding away from such rows; reverting here creates a cycle.
            best_df = frames[best_var]
            if column in best_df.columns:
                best_val = best_df.iloc[best][column]
                if not (pd.api.types.is_number(best_val) and not pd.isna(best_val)):
                    continue
            # Skip if target slot is already occupied by another binding (would create X - X = 0).
            occupied = {
                (b.get("variable"), b.get("row_index"), b.get("column"))
                for b in repaired.get("bindings", [])
                if b is not binding
            }
            if (best_var, best, column) in occupied:
                continue
            changes.append(
                f"{binding.get('id')}: {binding.get('variable')}.row {row_index} -> {best_var}.row {best} "
                f"(lexical score {selected_score} -> {best_score})"
            )
            binding["variable"] = best_var
            binding["row_index"] = best
    return repaired, changes


# ---------------------------------------------------------------------------
# Non-numeric cell repair
# ---------------------------------------------------------------------------

def _binding_period_year(binding: dict[str, Any], table_ids: dict[str, str]) -> int | None:
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
    if any(m in folded for m in _PRIOR_COL_MARKERS):
        return report_year - 1
    if any(m in folded for m in _CURRENT_COL_MARKERS):
        return report_year
    return None


def repair_non_numeric_bindings(
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    table_ids: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Move a non-numeric binding to the nearest semantic/period equivalent.

    Three-stage search:
    1. Semantic+period search across all frames (score >= 3).
    2. Same search with score >= 1 as fallback.
    3. Scan same column ±5 rows for the nearest numeric cell.
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
        # Vietnamese/English-format number strings ('100.000.000', '1,139,000',
        # '(7.483)') are valid numbers — don't move the binding; let the executor
        # handle conversion. Reuse the canonical parser (same as normalize_frame) so
        # OCR-concatenated garbage ('54.478.466.506524.297.268') is NOT mistaken for
        # a number, and EN-format / accounting-negative values are not relocated.
        if isinstance(value, str) and parse_number(value) is not None:
            continue

        claimed_years = {
            int(year) for year in re.findall(
                r"\b(20\d{2})\b",
                f"{binding.get('id', '')} {binding.get('meaning', '')}",
            )
        }
        target_year = next(iter(claimed_years)) if len(claimed_years) == 1 else None
        wanted = {
            token for token in re.findall(r"\w+", str(binding.get("meaning", "")).casefold())
            if len(token) > 2 and not token.isdigit()
        }

        def _is_numeric(v) -> bool:
            return pd.api.types.is_number(v) and not pd.isna(v)

        candidates: list[tuple[int, str, int, str]] = []
        for cand_var, cand_frame in frames.items():
            row_texts = [
                " ".join(str(item).casefold() for item in row if isinstance(item, str) and item.strip())
                for _, row in cand_frame.iterrows()
            ]
            row_scores = [len(wanted & set(re.findall(r"\w+", text))) for text in row_texts]
            for cand_col in cand_frame.columns:
                cand_binding = {"variable": cand_var, "column": str(cand_col)}
                period = _binding_period_year(cand_binding, table_ids)
                if target_year is not None and period != target_year:
                    continue
                for cand_row, score in enumerate(row_scores):
                    if score >= 1 and _is_numeric(cand_frame.iloc[cand_row][cand_col]):
                        candidates.append((score, cand_var, cand_row, str(cand_col)))

        strong = [c for c in candidates if c[0] >= 3]
        pool = strong if strong else candidates

        # Exclude candidates that would duplicate an already-valid binding (e.g.
        # df2.row0 → df1.row3 when df1.row3 already exists → X - X = 0).
        occupied = {
            (b.get("variable"), b.get("row_index"), b.get("column"))
            for b in repaired.get("bindings", [])
            if b is not binding
        }
        pool = [c for c in pool if (c[1], c[2], c[3]) not in occupied]

        new_variable, new_row, new_column = variable, row_index, column
        found = False
        if pool:
            best_score = max(c[0] for c in pool)
            best = [c for c in pool if c[0] == best_score]
            same_var = [c for c in best if c[1] == variable]
            finalists = same_var if same_var else best
            if len(finalists) >= 1:
                _, new_variable, new_row, new_column = min(
                    finalists, key=lambda c: abs(c[2] - row_index)
                )
                found = True

        if not found and column in frame.columns:
            for offset in range(1, len(frame)):
                for cand_row in (row_index - offset, row_index + offset):
                    if 0 <= cand_row < len(frame) and _is_numeric(frame.iloc[cand_row][column]):
                        new_row = cand_row
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


# ---------------------------------------------------------------------------
# Output-unit and order repairs
# ---------------------------------------------------------------------------

def repair_plan_output_unit(question: str, plan: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Use an unambiguous unit stated by the question as the output contract."""
    context = question_context(question)
    hint = context.get("unit_hint") or detect_unit(question)
    expected_units = UNIT_HINT_MAP.get(hint)
    if not expected_units or len(expected_units) != 1:
        return plan, None
    expected = next(iter(expected_units))
    actual = plan.get("output_unit")
    if actual == expected:
        return plan, None
    repaired = copy.deepcopy(plan)
    repaired["output_unit"] = expected
    return repaired, f"output_unit {actual!r} -> {expected!r} từ đơn vị trong câu hỏi"


def repair_plan_order(
    question: str,
    plan: dict[str, Any],
    table_ids: dict[str, str],
) -> tuple[dict[str, Any], str | None]:
    """Swap a direct B-A formula when enriched entity order says A-B."""
    if "chênh lệch" not in question.casefold():
        return plan, None
    tickers = question_context(question).get("tickers") or []
    if len(tickers) != 2:
        return plan, None
    try:
        body = ast.parse(plan["formula"], mode="eval").body
    except (KeyError, SyntaxError, TypeError):
        return plan, None
    if not (
        isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Sub)
        and isinstance(body.left, ast.Name)
        and isinstance(body.right, ast.Name)
    ):
        return plan, None
    by_id = {binding.get("id"): binding for binding in plan.get("bindings", [])}
    left = by_id.get(body.left.id, {}).get("variable")
    right = by_id.get(body.right.id, {}).get("variable")
    if left not in table_ids or right not in table_ids:
        return plan, None
    actual = [table_ids[left].split("_", 1)[0], table_ids[right].split("_", 1)[0]]
    if actual == tickers or actual != list(reversed(tickers)):
        return plan, None
    repaired = copy.deepcopy(plan)
    repaired["formula"] = f"{body.right.id} - {body.left.id}"
    return repaired, (
        f"chênh lệch phải theo thứ tự câu hỏi {tickers[0]} - {tickers[1]}, "
        f"formula đang là {actual[0]} - {actual[1]}"
    )


# ---------------------------------------------------------------------------
# Prior-year coverage repair
# ---------------------------------------------------------------------------

def _prior_period_column(frame: pd.DataFrame, current: str, target_year: int) -> str | None:
    explicit = [col for col in frame.columns if str(target_year) in str(col)]
    if len(explicit) == 1:
        return str(explicit[0])
    if not any(marker in current.casefold() for marker in _CURRENT_COL_MARKERS):
        return None
    candidates = [
        str(col) for col in frame.columns
        if any(marker in str(col).casefold() for marker in _PRIOR_COL_MARKERS)
    ]
    return candidates[0] if len(candidates) == 1 else None


def repair_prior_year_coverage(
    question: str,
    plan: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], list[str]]:
    """Expand missing rank years from a next-year comparative column."""
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
            new_id = re.sub(rf"(?<!\d){source_year}(?!\d)", str(target_year), node.id)
            if new_id == node.id:
                new_id = f"{node.id}_{target_year}"
            if new_id in bindings and new_id not in replacements.values():
                failed = True
                break
            clone = copy.deepcopy(source)
            clone["id"] = new_id
            clone["column"] = column
            clone["meaning"] = re.sub(
                rf"(?<!\d){source_year}(?!\d)", str(target_year),
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
        "expanded prior-year rank coverage: " + ", ".join(str(year) for year in added_years)
    ]
