"""Run the query, repair it at most twice, then apply the unit conversion.

Order matters: repair first, scale last. Repair fixes *execution* errors, which
are about pandas syntax and indexing; scaling is deterministic and cannot fail,
so putting it after repair keeps the model's attention on the one thing it is
being asked to fix. The submitted `pandas_query` is the scaled string, because
the grader re-executes it and must reproduce the submitted answer.
"""
from __future__ import annotations

import ast
import re
from typing import Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen.codegen import CODEGEN_SYSTEM
from finance_qa.modules.solve.common.context import page_text
from finance_qa.modules.solve.common.intent import (
    DIFF_CUE_LOOSE,
    GROWTH_CUE,
    MAGNITUDE_BLOCK,
    MAGNITUDE_METRIC,
    MIN_MARKER,
    PAID_OUT,
    SELECTION_MARKER,
    SIGNED_METRIC,
    YEAR_ANSWER_MARKER,
    YEAR_MENTION,
    intent_norm,
)
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution
from finance_qa.modules.solve.common.units import (
    detect_unit,
    resolve_source_unit,
    scale_expression,
    strip_scale_factor,
    unit_from_hint,
)
from finance_qa.modules.tools.python_exec import run_query

MAX_REPAIRS = 2

# Control-arm temperature. Not 0.0, because without `repair_history` the repair
# prompt differs from the generation prompt by one appended error line, so at
# temperature 0 the model re-emits the identical query: all 8 questions that died
# on the 60-question gold set logged the *same* error twice more and never varied.
#
# That reading of the symptom was wrong. The cause is not sampling: `_arepair`
# built a fresh two-message prompt on every attempt, so attempt 2 never saw
# attempt 1's query or error and had no way to know it was repeating itself.
# Measured on the gold94 runs, noise at 0.3 does not fix it — of the questions
# that entered the loop, the error was byte-identical across every attempt for 5
# of 8 (base1), 5 of 7 (base2) and 4 of 7 (fanout), q381 and q396 three times over.
REPAIR_TEMPERATURE = 0.3

# History arm. With the attempts block below, the prompt genuinely changes between
# attempts — it grows by one failed query each time — so the reason to inject noise
# is gone and the retry can be as reproducible as the first call.
HISTORY_TEMPERATURE = 0.0

_DF_VAR = re.compile(r"\bdf\d+\b")

REPAIR_SYSTEM = CODEGEN_SYSTEM + """

The previous query failed to execute. Fix the pandas query. Do not change the
evidence table you read from. The error is followed by the true shape and the
true column names of every dataframe the query touched — the fixed query must
index by a name from that list, copied character for character."""


def _blank_cell_error(exc: Exception) -> bool:
    """Is this the failure where the query found a cell holding no number?

    Three shapes of the same mistake: the cell is empty (`nan`), the cell holds
    text (`'V.19.'`, `'Đang hoạt động'`, `'1,23%'`), or arithmetic ran against a
    column that is text. Naming the column list back at the model does not help
    here — the column it used exists, it is the *cell* that is unusable.
    """
    if isinstance(exc, (TypeError, ValueError)):
        return any(
            token in str(exc)
            for token in ("non-finite", "could not convert string to float",
                          "did not contain a loop", "not supported for the input types",
                          "unsupported operand")
        )
    return False


def _row_dump(solution: PandasSolution, frames: Mapping[str, pd.DataFrame]) -> str:
    """The row the model said it was aiming at, cell by cell.

    This is the single largest hole in the repair loop: over a 1012-question run
    `ValueError: query returned non-finite nan` was logged 91 times, more than
    every other execution error combined, and it names neither the row nor the
    value. The repair had nothing to work from and re-emitted the query it had
    just written — measured, the error was byte-identical on all three attempts
    for 56 of the 79 questions that ended at 0.0.
    """
    frame = frames.get(solution.table_variable)
    if frame is None:
        return ""
    try:
        row = frame.iloc[int(str(solution.target_row).strip())]
    except (TypeError, ValueError, IndexError):
        return ""  # a label-indexed or multi-cell query: the dump would be a guess
    cells = [
        f"{str(col)!r}={'(rỗng)' if pd.isna(val) or not str(val).strip() else repr(str(val).strip())}"
        for col, val in row.items()
    ]
    return (
        f"Hàng bạn đã đọc, {solution.table_variable}.iloc[{solution.target_row}], "
        f"chứa: {'; '.join(cells)}"
    )


def describe_error(
    exc: Exception,
    query: str,
    frames: Mapping[str, pd.DataFrame],
    solution: PandasSolution | None = None,
) -> str:
    """The failure as the repair call needs to see it.

    `str(exc)` alone is what made the loop a no-op: a `KeyError` arrives as the
    bare string `'2018'` — no exception type, no indication that the problem is a
    column name, no list of the names that do exist. Every repair got that, and
    every repair answered with the query it had just written.
    """
    lines = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, KeyError):
        lines.append("(không có cột hay nhãn nào mang tên này)")
    if solution is not None and _blank_cell_error(exc):
        dump = _row_dump(solution, frames)
        if dump:
            lines.append(dump)
        lines.append(
            "Ô bạn đọc không chứa số. Chọn ô khác: cùng chỉ tiêu nhưng ở cột số "
            "liệu khác, hoặc hàng khác mang đúng nhãn chỉ tiêu mà câu hỏi cần. "
            "Không ép kiểu, không bịa số."
        )
    for var in sorted(set(_DF_VAR.findall(query))):
        frame = frames.get(var)
        if frame is None:
            lines.append(f"{var}: biến này không tồn tại")
            continue
        columns = ", ".join(repr(str(col)) for col in frame.columns)
        lines.append(
            f"{var}: {frame.shape[0]} hàng x {frame.shape[1]} cột; "
            f"chỉ có các cột [{columns}]; vị trí hàng hợp lệ 0..{frame.shape[0] - 1}"
        )
    return "\n".join(lines)


def _attempts_block(attempts: Sequence[tuple[str, str]]) -> str:
    """Every query already tried and why it failed, most recent one in full.

    The earlier entries keep only the first line of `describe_error` — the rest of
    it is the shape and column list of the same dataframes, which does not change
    between attempts, so repeating it three times would spend prompt budget on
    dilution. What the model is missing is the *queries it has already spent*, and
    those are one line each.
    """
    lines = []
    for i, (query, detail) in enumerate(attempts, 1):
        body = detail if i == len(attempts) else (detail.splitlines() or [""])[0]
        lines.append(f"Lần {i} — truy vấn đã chạy:\n{query or '(rỗng)'}\nLỗi:\n{body}")
    lines.append(
        "Tất cả các truy vấn trên đã chạy và đều lỗi. Đừng nộp lại bất kỳ truy vấn "
        "nào trong số đó — hãy đọc một ô khác."
    )
    return "\n\n".join(lines)


async def _arepair(
    prompt: str, attempts: Sequence[tuple[str, str]], *, history: bool
) -> PandasSolution:
    """One repair call. With `history`, it sees every attempt; without, only the last.

    The attempts are rendered into the user message rather than replayed as an
    AIMessage/ToolMessage exchange because `with_structured_output` returns the
    parsed object and discards the raw reply — a reconstructed tool-call turn would
    be invented, not recorded. A plain block carries the same facts.
    """
    query, detail = attempts[-1]
    if history:
        user = f"{prompt}\n\n{_attempts_block(attempts)}"
        temperature = HISTORY_TEMPERATURE
    else:
        user = (
            f"{prompt}\n\n"
            f"Truy vấn trước đó:\n{query}\n\n"
            f"Lỗi khi chạy:\n{detail}"
        )
        temperature = REPAIR_TEMPERATURE
    model = get_chat_model(thinking=False, max_tokens=1024, temperature=temperature)
    result = await model.with_structured_output(
        PandasSolution, method=STRUCTURED_METHOD
    ).ainvoke([SystemMessage(content=REPAIR_SYSTEM), HumanMessage(content=user)])
    if not isinstance(result, PandasSolution):
        result = PandasSolution.model_validate(result)
    return result


async def arun_with_repair(
    solution: PandasSolution,
    prompt: str,
    frames: Mapping[str, pd.DataFrame],
    *,
    max_repairs: int = MAX_REPAIRS,
    repair_history: bool = False,
) -> tuple[PandasSolution, float | None, list[str]]:
    """Execute ``solution.pandas_query``, repairing on error.

    Returns ``(solution, raw_value, errors)`` where ``solution`` is the last one
    attempted and ``raw_value`` is the cell value *before* unit conversion, or
    None if every attempt failed.
    """
    errors: list[str] = []
    # Every (query, failure) the loop has spent, which is not what the run record
    # keeps: the column dump is a few hundred chars per attempt and belongs in the
    # prompt, not in the JSONL. Accumulated rather than overwritten so the repair
    # call can see what it has already tried — see `REPAIR_TEMPERATURE`.
    attempts: list[tuple[str, str]] = []
    for attempt in range(max_repairs + 1):
        query = (solution.pandas_query or "").strip()
        if not query:
            errors.append("codegen: pandas_query rỗng")
            attempts.append((query, "Truy vấn rỗng — hãy viết một biểu thức pandas."))
        else:
            try:
                return solution, float(run_query(query, dict(frames))), errors
            except Exception as exc:  # noqa: BLE001 - the repair loop's input
                errors.append(f"execute[{attempt}]: {type(exc).__name__}: {exc}")
                attempts.append((query, describe_error(exc, query, frames, solution)))
        if attempt == max_repairs:
            break
        try:
            solution = await _arepair(prompt, attempts, history=repair_history)
        except Exception as exc:  # noqa: BLE001 - repair itself can fail
            errors.append(f"repair[{attempt}]: {exc}")
            break
    return solution, None, errors


def between_two_companies(normalized: str, tickers: Sequence[str]) -> bool:
    """Is this a difference between two companies in a single period?

    Kept for the analysis scripts that still reference it
    (`scripts/gate_sign_replay.py`, `scripts/patch_sign_submission.py`) but no
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
    whose own docstring (`scripts/score_clean_eval.py`) warns it disagrees with
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


# `max(a, b, c)` where each argument reads exactly one frame. Deliberately not a
# general expression parser: the whole guard rests on knowing which *year* won, and
# that is only well defined when each argument belongs to one year's table.
_SELECT_CALL = re.compile(r"^\s*(max|min)\s*\((?P<args>.+)\)\s*$", re.S)
_ROUND_CALL = re.compile(r"^\s*round\s*\((?P<args>.+)\)\s*$", re.S)
_FRAME_REF = re.compile(r"\bdf\d+\b")
_YEAR_IN_ID = re.compile(r"_(20\d\d)_")
_YEAR_ANYWHERE = re.compile(r"\b(?:19|20)\d\d\b")


def _split_args(args: str) -> list[str] | None:
    """Top-level comma split. None if the brackets do not balance."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(args):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            parts.append(args[start:i])
            start = i + 1
    parts.append(args[start:])
    return [p.strip() for p in parts if p.strip()] if depth == 0 else None


def _unwrap_round(query: str) -> str:
    """Look through the `round(expr, 2)` codegen wraps almost everything in.

    978 of the 1,012 queries in the v8 run start with `round(`, and `_SELECT_CALL` is
    anchored, so `project_year` matched none of them and never fired once. q866 submits
    `round(max(...), 2)` and answered with an amount.
    """
    call = _ROUND_CALL.match(query.strip())
    if not call:
        return query
    args = _split_args(call.group("args"))
    if args is None or len(args) > 2:
        return query
    if len(args) == 2 and not args[1].lstrip("-").isdigit():
        return query
    return args[0]


def _year_of(term: str, table_id: str) -> str | None:
    """The year the winning term speaks for.

    The column name wins over the report id, because a 2023 report carries a
    "Năm trước" column holding 2022 and the report id would then name the wrong
    year. Neither is trusted blindly — `project_year` checks the result against the
    years the question actually lists.
    """
    in_column = _YEAR_ANYWHERE.findall(term)
    if in_column:
        return in_column[-1]
    found = _YEAR_IN_ID.search(table_id)
    return found.group(1) if found else None


def project_year(
    query: str,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    question: str,
) -> tuple[str, str] | None:
    """Turn `max(<2019 cell>, <2022 cell>)` into a query that answers *which year*.

    A "năm nào" question wants a year and codegen submits the winning cell's value
    instead: on the 1,012-question run all 28 such questions answer with an amount,
    which is wrong by definition. `raw_selection_linker` has had the answer all
    along — it emits `(<cell>) * 0 + <year>`, keeping the year inside the *query* so
    that re-executing the submission still yields it. codegen never asked, exactly
    as it never asked `cell_locator` about expense signs.

    Returns `(query, year)` or None. None is the common case and is meant to be:
    the rewrite only fires when the winning year is unambiguous, which means the
    query is a `max`/`min` of single-frame terms, bare or under codegen's `round`
    wrapper, *and* the year it lands on is one the question actually names. That last
    check is what stops a "Năm trước" column from answering 2022 for a question
    about 2023.
    """
    if not YEAR_ANSWER_MARKER.search(intent_norm(question)):
        return None
    call = _SELECT_CALL.match(_unwrap_round(query).strip())
    if not call:
        return None
    args_text = call.group("args").strip()
    # The model writes both `max(a, b)` and `max([a, b])`; q978 is the second form
    # and was silently skipped, because its commas sit one bracket deep. Stripping a
    # wrapping pair is safe: for `max([a, b], [c, d])` the remainder no longer
    # balances and `_split_args` rejects it rather than mis-splitting.
    if args_text.startswith("[") and args_text.endswith("]"):
        args_text = args_text[1:-1]
    args = _split_args(args_text)
    if not args or len(args) < 2:
        return None

    values: dict[str, float] = {}
    for term in args:
        refs = set(_FRAME_REF.findall(term))
        if len(refs) != 1:  # a term spanning two years names no single year
            return None
        try:
            values[term] = float(run_query(term, dict(frames)))
        except Exception:  # noqa: BLE001 - one unreadable cell voids the comparison
            return None
    if len(values) != len(args):
        return None

    pick = min if MIN_MARKER.search(intent_norm(question)) else max
    winner = pick(values, key=lambda term: values[term])
    year = _year_of(winner, names.get(_FRAME_REF.search(winner).group(0), ""))
    if not year or year not in set(_YEAR_ANYWHERE.findall(question)):
        return None
    return f"({winner}) * 0 + {year}", year


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


async def aexecute(
    solution: PandasSolution,
    prompt: str,
    frames: Mapping[str, pd.DataFrame],
    *,
    question: str,
    unit_hint: str = "",
    names: Mapping[str, str] | None = None,
    tickers: Sequence[str] = (),
    max_repairs: int = MAX_REPAIRS,
    repair_history: bool = False,
) -> dict:
    """Full execute-and-repair step. Returns the answer, final query and diag."""
    solution, raw, errors = await arun_with_repair(
        solution, prompt, frames, max_repairs=max_repairs, repair_history=repair_history
    )
    if raw is None:
        # 0.0 with the last query attached: the query is still worth submitting
        # because execution is scored on re-running it, and a query that errors
        # for us may still be the graded one that matters. Never submit a bare
        # float literal — that forfeits the execution objective outright.
        return {
            "answer": 0.0,
            "pandas_query": solution.pandas_query.strip() or "0.0",
            "solution": solution,
            "errors": errors,
            "diag": {"failed": True},
        }

    query, diag = apply_units(
        solution, frames, question=question, unit_hint=unit_hint, names=names,
        tickers=tickers,
    )
    try:
        answer = float(run_query(query, dict(frames)))
    except Exception as exc:  # noqa: BLE001 - scaling should never break a query
        errors.append(f"scale: {exc}")
        return {
            "answer": raw,
            "pandas_query": solution.pandas_query.strip(),
            "solution": solution,
            "errors": errors,
            "diag": {**diag, "scale_failed": True},
        }

    return {
        "answer": answer,
        "pandas_query": query,
        "solution": solution,
        "errors": errors,
        # `raw_value` is the query as the *model* wrote it, so it still carries any
        # factor listed in `model_factors_stripped`.
        "diag": {**diag, "raw_value": raw, "repairs": len(errors)},
    }


__all__ = [
    "HISTORY_TEMPERATURE", "MAX_REPAIRS", "REPAIR_TEMPERATURE", "aexecute",
    "apply_units", "arun_with_repair", "as_magnitude", "between_two_companies",
    "describe_error", "project_year",
]
