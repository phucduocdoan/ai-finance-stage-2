"""Decide sign/magnitude and apply the unit conversion exactly once.

Part of the `codegen.execute` facade: see `execute/__init__.py`.
"""
from __future__ import annotations

import ast
from typing import Mapping, Sequence

import pandas as pd

from finance_qa.modules.solve.codegen.execute.execute_count import canonical_count, is_count_query
from finance_qa.modules.solve.codegen.execute.execute_repair import _DF_VAR
from finance_qa.modules.solve.codegen.execute.execute_year import project_year
from finance_qa.modules.solve.common.context import page_text
from finance_qa.modules.solve.common.intent import (
    DIFF_CUE_LOOSE,
    GROWTH_CUE,
    MAGNITUDE_BLOCK,
    MAGNITUDE_METRIC,
    PAID_OUT,
    SELECTION_MARKER,
    SIGNED_METRIC,
    YEAR_MENTION,
    intent_norm,
)
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.solve.common.units import (
    detect_unit,
    resolve_source_unit,
    scale_expression,
    strip_scale_factor,
    unit_from_hint,
)


def between_two_companies(normalized: str, tickers: Sequence[str]) -> bool:
    """Is this a difference between two companies in a single period?

    Kept for the analysis scripts that still reference it
    (`scripts/dev/gate_sign_replay.py`, `scripts/dev/patch_sign_submission.py`) but no
    longer consulted by `as_magnitude`: see the "was" paragraph there for why.
    A difference *across periods* is a different shape: q623 ("cuối năm 2023 và
    cuối năm 2022") means 2023 minus 2022, so flipping the sign flips the
    meaning. That is what the year count separates.

    Two guards earn their keep. `SELECTION_MARKER` drops screening questions
    (q417, q418, q445), where "cao hơn" trips `DIFF_CUE_LOOSE` but the answer is
    one company's ratio, and that ratio may legitimately be negative. The
    normalized text must come from `intent_norm`, not `norm`: "công ty cổ phần"
    matches `SELECTION_MARKER`'s `cong ty co\\b` alternative otherwise.
    """
    if len({str(t).upper().strip() for t in tickers if str(t).strip()}) < 2:
        return False
    if SELECTION_MARKER.search(normalized):
        return False
    if len(set(YEAR_MENTION.findall(normalized))) > 1:
        return False
    return bool(DIFF_CUE_LOOSE.search(normalized))


def as_magnitude(question: str, target_row: str, tickers: Sequence[str] = ()) -> bool:
    """Does this question want the amount rather than the signed cell?

    `cell_locator.value_transform` has answered this for the narrow solvers all
    along; codegen never asked. That is why q526 submits −83.790.676.915 for a
    cell printed `(83.790.676.915)` while gold is positive: the parenthesised
    expense parses to a negative and nothing on this path undoes it.

    Every solver reaches this one call (`graph.py` runs each of them through
    `aexecute`), and `abs` here wraps the *whole* query, so it also fixes what
    the per-term `value_transform` cannot: an average of amounts paid out.

    This used to also force the magnitude for `between_two_companies()` — a
    two-company "chênh lệch", where `abs(a) - abs(b)` is still negative — on the
    theory that which company the question names first is arbitrary, so gold
    always wants the magnitude. That was measured against three questions (q774,
    q777, q894) from `artifacts/eval_clean/`, an internal Claude-labeled proxy set
    whose own docstring (`scripts/dev/score_clean_eval.py`) warns it disagrees with
    real BTC gold specifically on ambiguous questions. `docs/label_calibration_
    2026-08-23.md` already found q774 to be exactly that: two independent re-label
    passes both read −204503 (VIB minus SHB, the question's own order), against
    the one proxy label of +204503 that justified this rule. Separately,
    `data/eval/manual15_gold.jsonl` and `unbiased60_gold.jsonl` — hand-checked
    against the source tables, not Claude-labeled — carry q744, q752, and q759,
    three more two-company differences, all with *negative* gold, each annotated
    "per question order", and in each case codegen already computed that exact
    signed value before this rule's `abs()` flipped it to the wrong sign. Four
    real, checkable data points and zero survive in favor of "always positive";
    the sign here is not arbitrary, it is the order the question names the two
    companies in, and codegen already gets that order right on its own.
    """
    normalized = intent_norm(question)
    if PAID_OUT.search(normalized):
        return True
    text = f"{question} {target_row}"
    if SIGNED_METRIC.search(text) or not MAGNITUDE_METRIC.search(text):
        return False
    return not (
        DIFF_CUE_LOOSE.search(normalized)
        or GROWTH_CUE.search(normalized)
        or MAGNITUDE_BLOCK.search(normalized)
    )


def _is_data_ratio(query: str) -> bool:
    """Does the query divide two data-bearing subexpressions -- a genuine ratio?

    `conversion_factor` never scales a ratio to a percent (see `units.py`): that
    arithmetic is the model's job, and it is unreliable at it exactly where the
    expression is composed rather than a single division. q955 averages four
    per-ticker ratios, ``((a1/b1) + (a2/b2) + (a3/b3) + (a4/b4)) / 4``, and gold
    is 54.66 against a submitted 0.5466 -- the model wrote the four inner
    divisions but not the outer ``* 100``.

    Only a division whose *both* sides reference a table frame counts: the outer
    ``/ 4`` above divides by a bare count, not by data, and must not trip this --
    an already percent-valued average like ``(df1.iloc[2] + df2.iloc[3]) / 2``
    would otherwise be rescaled a second time.
    """
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        and _DF_VAR.search(ast.unparse(node.left)) and _DF_VAR.search(ast.unparse(node.right))
        for node in ast.walk(tree)
    )


def _already_scaled_to_percent(query: str) -> bool:
    """Does the query's top-level operation already multiply by 100?

    Checked so a model that *did* remember its own `* 100` (as most do) is not
    rescaled a second time by the guard above.
    """
    try:
        tree = ast.parse(query, mode="eval").body
    except SyntaxError:
        return False
    if not (isinstance(tree, ast.BinOp) and isinstance(tree.op, ast.Mult)):
        return False
    return any(isinstance(side, ast.Constant) and side.value in (100, 100.0) for side in (tree.left, tree.right))


def apply_units(
    solution: PandasSolution,
    frames: Mapping[str, pd.DataFrame],
    *,
    question: str,
    unit_hint: str = "",
    names: Mapping[str, str] | None = None,
    tickers: Sequence[str] = (),
) -> tuple[str, dict]:
    """Convert the value's unit exactly once. Returns ``(query, diag)``.

    Exactly once is the whole job. The model was doing it too — writing
    ``/ 1e11`` into its own query and mislabelling the source unit on top — so the
    conversion landed twice and the answer came out 1e15 away from gold. So the
    model's arithmetic is stripped, and its `source_unit` is honoured only when it
    says the value is not money.

    The source unit is read from the table (banner cell, column name, or the
    "Đơn vị tính" line on the page). The target unit comes from the question,
    because that is where "bao nhiêu triệu đồng" is written; the model's
    `target_unit` is the fallback.
    """
    frame = frames.get(solution.table_variable)
    table_id = (names or {}).get(solution.table_variable, "")
    detected, where = (None, "")
    if frame is not None:
        detected, where = detect_unit(
            frame, solution.target_column or None, page_text(table_id) if table_id else ""
        )

    source, fallback = resolve_source_unit(detected, solution.source_unit)
    target = unit_from_hint(question) or unit_from_hint(unit_hint) or solution.target_unit or "unknown"
    raw_query, removed = strip_scale_factor(solution.pandas_query)
    # A year is not a quantity, so this returns before both transforms below: there
    # is no unit to convert and no sign to take a magnitude of. Stripping the
    # model's own factors first is what lets `max(...) * 1e-9` still be recognised.
    picked = project_year(raw_query, frames, names or {}, question)
    if picked is not None:
        query, year = picked
        return query, {
            "source_unit": source,
            "source_unit_from": where or fallback,
            "model_source_unit": solution.source_unit,
            "target_unit": "year",
            "scaled": False,
            "magnitude_abs": False,
            "year_answer": year,
            "model_factors_stripped": removed,
        }
    # A count is not a quantity either, for the same reason: no unit to convert,
    # and no sign to take a magnitude of. The rewrite goes into the *query* so the
    # grader's re-execution reproduces the submitted answer.
    if is_count_query(raw_query):
        query = canonical_count(raw_query) or raw_query
        return query, {
            "source_unit": source,
            "source_unit_from": where or fallback,
            "model_source_unit": solution.source_unit,
            "target_unit": "count",
            "scaled": False,
            "magnitude_abs": False,
            "count_recounted": query != raw_query,
            "model_factors_stripped": removed,
        }
    # `abs` goes inside the scale factor, and into the *query* rather than onto the
    # number, because the execution objective re-runs the submitted string: a
    # magnitude applied outside it would make the two metrics disagree.
    magnitude = as_magnitude(question, solution.target_row, tickers)
    inner = f"abs({raw_query})" if magnitude else raw_query
    percent_scaled = (
        target == "percent"
        and _is_data_ratio(raw_query)
        and not _already_scaled_to_percent(raw_query)
    )
    if percent_scaled:
        inner = f"({inner}) * 100"
    query = scale_expression(inner, source, target)
    return query, {
        "source_unit": source,
        "source_unit_from": where or fallback,
        "model_source_unit": solution.source_unit,
        "target_unit": target,
        "scaled": query != inner,
        "percent_scaled": percent_scaled,
        "magnitude_abs": magnitude,
        "model_factors_stripped": removed,
    }
