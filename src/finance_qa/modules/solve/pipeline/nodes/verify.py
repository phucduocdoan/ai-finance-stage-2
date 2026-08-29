"""Verification and profile-diagnostic nodes for the solve pipeline."""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.solve.codegen.execute import aexecute
from finance_qa.modules.solve.codegen.expression_codegen import build_prompt
from finance_qa.modules.solve.codegen.verify import arevise, averify
from finance_qa.modules.solve.facts.profile_validate import validate_profile_selection
from finance_qa.modules.solve.pipeline.emit import emit_result
from finance_qa.modules.solve.pipeline.evidence import codegen_budget, load_evidence


State = Mapping[str, Any]


# The narrow solvers (cell_locator, formula_facts, raw_table_linker,
# selection_facts, raw_selection_linker, structured_facts) each say, in their own
# comment, that they leave `codegen_prompt` empty so verify_answer passes
# through — which meant diag["verify"] was empty for every one of them. Measured
# on a full 1012-question run: present for 495 of 520 codegen answers, 0 of 492
# answers from the other five solvers combined, so half the corpus carried no
# quality signal at all. True keeps that half a *measurement* only: `averify`
# runs and diag["verify"] gets filled in, but `arevise` never does, because none
# of those solvers build the table_ids/evidence bookkeeping a kept revision
# would need — a revision that silently miswrote that would ship a wrong answer
# instead of falling back, which is what happens on the codegen path below.
VERIFY_NARROW_SOLVERS_OBSERVE_ONLY = True


def _narrow_solver_prompt(
    state: State,
    config: FinanceAgentConfig,
    *,
    observe_narrow: bool,
    query: str,
    frames: dict,
    names: dict,
    drop: dict,
) -> tuple[dict | None, str, dict, dict]:
    """Build a codegen prompt for narrow solvers, which leave it empty.

    Returns `(early_return, prompt, frames, names)`: `early_return` is the dict
    `verify_answer` should return immediately, or None to keep going.
    """
    if not observe_narrow or not query:
        return drop, "", frames, names
    if not frames:
        # Those three solvers leave `frames`/`names` at `{}` (see their
        # own returns above), so without this the checker was shown a
        # bare question and no table at all — it judged qid18 (gold
        # 2077.87) wrong for a right answer, because it had nothing to
        # check the number against. Loaded the same way `generate_pandas`
        # does, from the ids the solver actually used rather than a new
        # limit, so the grids match what produced the answer.
        evidence_ids = state.get("evidence_tables") or state.get("table_ids") or []
        _, max_tables = codegen_budget(state, config)
        names, frames, _ = load_evidence(evidence_ids, max_tables)
        if not frames:
            # Nothing to show the checker even after trying to load it —
            # a verdict here would be the verifier grading a blank page,
            # so the signal is recorded as missing rather than negative.
            return (
                {
                    **drop,
                    "diag": {
                        **(state.get("diag") or {}),
                        "verify": {"skipped": "no_evidence"},
                    },
                },
                "", frames, names,
            )
    prompt = build_prompt(state["question"], frames, names)
    return None, prompt, frames, names


def _observe_only(state: State, verdict, drop: dict) -> dict:
    # Observe-only: record the verdict, never touch the answer.
    return {
        **drop,
        "diag": {
            **(state.get("diag") or {}),
            "verify": {"correct": verdict.correct, "reason": verdict.reason},
        },
    }


async def _revise_and_reexecute(
    state: State,
    query: str,
    prompt: str,
    frames: dict,
    names: dict,
    verdict,
    *,
    config: FinanceAgentConfig,
    revise_func,
    execute_func,
    emit_func,
    drop: dict,
) -> dict:
    diag = {"verify": {"correct": False, "reason": verdict.reason, "before": query}}
    try:
        revised = await revise_func(prompt, query, verdict.reason)
        result = await execute_func(
            revised, prompt, frames,
            question=state["question"], unit_hint=state.get("unit_hint") or "",
            names=names, tickers=state.get("tickers") or [],
            max_repairs=config.max_repairs,
            repair_history=config.repair_history,
        )
    except Exception as exc:  # noqa: BLE001
        return {**drop, "errors": list(state.get("errors") or []) + [f"revise: {exc}"]}
    if result["diag"].get("failed"):
        return {**drop, "diag": {**(state.get("diag") or {}), **diag, "verify_kept": False}}
    return {**emit_func(state, result, {**diag, "verify_kept": True}), **drop}


def make_verify_answer(
    config: FinanceAgentConfig,
    *,
    verify_func=None,
    revise_func=None,
    execute_func=None,
    emit_func=None,
    observe_narrow: bool | None = None,
):
    """Check the cell the query read, and rewrite the query once if it is wrong.

    This is the only node that can reach the largest failure bucket. Repair fires
    on exceptions, and a query that reads the wrong row raises none: measured on
    the 73 gold questions, 5 queries threw and ~34 returned a clean wrong number.

    Two guards keep a check that is itself a model call from costing more than it
    wins. The rewrite is kept only when it executes *and* moves the answer, so a
    revision that dies falls back to the original instead of shipping 0.0; and
    there is exactly one round, with no re-verification of the rewrite, because a
    verifier that can veto its own replacement will loop on the questions where it
    is the one that is wrong.
    """
    verify_func = verify_func or averify
    revise_func = revise_func or arevise
    execute_func = execute_func or aexecute
    emit_func = emit_func or emit_result
    if observe_narrow is None:
        observe_narrow = VERIFY_NARROW_SOLVERS_OBSERVE_ONLY

    async def verify_answer(state: State) -> dict:
        query = state.get("pandas_query") or ""
        frames = state.get("frames") or {}
        names = state.get("names") or {}
        prompt = state.get("codegen_prompt") or ""
        drop = {"codegen_prompt": ""}  # prompt text, not a result
        if not config.verify_answer:
            return drop
        # A query that never ran has no cell to check, and the verifier shown one
        # reads the 0.0 as an answer and approves it (qid280). Repair already had
        # three attempts at this one; a fourth under a different prompt is not a
        # different idea.
        if (state.get("diag") or {}).get("units", {}).get("failed"):
            return drop

        # A screening answer is checked but never rewritten. `arevise` submits a
        # `PandasSolution`, which by construction cannot hold a filter, so the
        # only rewrite it can offer is the flat shape this class already fails
        # at — and the rewrite is kept on "it executed", not on "it is more
        # right". Measured on the first flag-on run of the 29 labelled screening
        # questions: `compose` produced a `pd.Series` plan for 19 of them and
        # only 3 survived to the record, the other 16 having been revised back
        # into a single expression with no execution error to justify it. With
        # `SOLVE_VERIFY_ANSWER=0` the plan survived on 3 of 4 spot-checked ids.
        screening = bool((state.get("diag") or {}).get("screening_solver"))
        # A narrow solver never built a codegen prompt (see the comment above),
        # so there is nothing to show the checker unless one is built here — the
        # same question + evidence grids codegen would have shown, empty for the
        # three solvers (formula_facts, selection_facts, structured_facts) that
        # answer from the fact catalog rather than a loaded table.
        narrow = not prompt
        if narrow:
            early, prompt, frames, names = _narrow_solver_prompt(
                state, config,
                observe_narrow=observe_narrow, query=query, frames=frames, names=names, drop=drop,
            )
            if early is not None:
                return early
        elif not frames or not prompt:
            return drop

        try:
            verdict, _ = await verify_func(
                prompt, query, float(state.get("answer") or 0.0),
                frames, names, unit_hint=state.get("unit_hint") or "",
            )
        except Exception as exc:  # noqa: BLE001 - a failed check is not a failed answer
            return {**drop, "errors": list(state.get("errors") or []) + [f"verify: {exc}"]}

        if narrow or screening:
            return _observe_only(state, verdict, drop)

        if verdict.correct:
            return {**drop, "diag": {**(state.get("diag") or {}), "verify": {"correct": True}}}

        if not verdict.reason.strip():
            # A false verdict without an objection is not actionable. Letting
            # `arevise` run anyway turns the verifier into a second generator,
            # and q919 regressed that way: the original mixed-unit average was
            # correct, while the empty-reason rewrite dropped the per-table
            # thousand->VND factors.
            return {
                **drop,
                "diag": {
                    **(state.get("diag") or {}),
                    "verify": {
                        "correct": False,
                        "reason": "",
                        "skipped": "empty_reason",
                    },
                    "verify_kept": False,
                },
            }

        return await _revise_and_reexecute(
            state, query, prompt, frames, names, verdict,
            config=config, revise_func=revise_func, execute_func=execute_func, emit_func=emit_func, drop=drop,
        )

    return verify_answer


def make_profile_validate(config: FinanceAgentConfig):
    """Attach TableProfile-based diagnostics to the final answer state."""

    def profile_validate(state: State) -> dict:
        if not config.profile_validate:
            return {}
        try:
            diag = validate_profile_selection(
                state,
                frames=state.get("frames") or {},
                names=state.get("names") or {},
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must not change answers
            diag = {
                "done": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "query_cells": [],
                "findings": [],
                "summary": {"strong": 0, "weak": 0, "info": 0},
            }
        return {
            "diag": {
                **(state.get("diag") or {}),
                "profile_validate": diag,
            },
        }

    return profile_validate


__all__ = [
    "VERIFY_NARROW_SOLVERS_OBSERVE_ONLY",
    "make_profile_validate",
    "make_verify_answer",
]
