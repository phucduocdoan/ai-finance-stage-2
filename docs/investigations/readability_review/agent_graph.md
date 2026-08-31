# Readability / maintainability review — agent + graph subsystem

Scope: `src/finance_qa/agents/base.py`, `agents/finance/{agent,graph,config,prompts,retrieve,state,understand,utils}.py`.
Pure readability pass — no accuracy/behavior changes suggested. The dense, rationale-per-decision
comment style (measurements, historical bugs, qids) is treated as a feature of this codebase, not a
smell, and is not flagged below unless a specific comment is stale or wrong.

## Findings (most impactful first)

1. **`agents/finance/config.py:143`** — `selection_sub_tables: int = _count("SOLVE_SUB_TABLES", 6)` breaks
   the pattern every other overridable field in this dataclass uses
   (`field(default_factory=lambda: _count(...))`, e.g. lines 93-95, 134, 137, 140, 143's neighbors).
   Because it's a bare default instead of a `default_factory`, `_count(...)` runs once at class-body
   evaluation (module import time), not once per `FinanceAgentConfig()` construction — so
   `SOLVE_SUB_TABLES` set after import (e.g. in a test that mutates `os.environ` then constructs a
   fresh config) is silently ignored, unlike every sibling flag/count field.
   Direction: wrap it the same way as the other 15+ fields: `field(default_factory=lambda: _count("SOLVE_SUB_TABLES", 6))`.

2. **`agents/finance/state.py:35`** — `solver: str  # "lookup" | "repl" | "formula" | "failed"` is stale.
   The actual strings written to this field (see `modules/solve/pipeline/nodes/solvers.py` calls into
   `emit_solver_result`) are the current solver-chain node names — `cell_locator`, `raw_table_linker`,
   `raw_selection_linker`, `selection_facts`, `structured_facts`, `selection`, etc. — none of which match
   the comment's `"lookup"/"repl"/"formula"/"failed"` set. A new engineer reading `state.py` first (as the
   type contract for the whole graph) will look for the wrong values downstream.
   Direction: update the comment to point at `SOLVER_CHAIN` in `modules/solve/pipeline/router.py` as the
   source of truth, rather than enumerating values inline where they can drift again.

3. **`agents/finance/graph.py:79-91`** — the `SolveState` docstring says `codegen_prompt` and
   `evidence_tables` are "both dropped from the record written by the runner," which is true only at the
   top level. The same information is deliberately re-persisted one level down, inside
   `diag["evidence_tables"]` (written by `emit.py`'s `emit_result`/`emit_solver_result`, and read back by
   most `scripts/gate_*.py` consumers and `nodes/verify.py:103`). As written, the comment reads as if
   `evidence_tables` disappears entirely, when in fact there are two fields with the same name at two
   nesting depths serving two different lifetimes (in-graph vs. persisted). This is exactly the kind of
   fact a newcomer needs stated explicitly, since grepping for `evidence_tables` turns up both without
   distinguishing them.
   Direction: extend the docstring to say the info survives via `diag["evidence_tables"]`, or rename one
   of the two to avoid the same name meaning two different things at two levels.

4. **`agents/finance/state.py:27`** — the `# ── load node ──` section header no longer names a real node.
   `graph.py`'s own module docstring (lines 19-24) explains the evidence-loading step was folded into
   `generate_pandas` (`load_evidence`, sliced by `codegen_budget`); there is no node called "load" in
   `build_graph`. A reader skimming `state.py` to learn "which node fills which key" will search the graph
   for a `load` node and not find one.
   Direction: retitle the section to name the actual owner (`generate_pandas` / `load_evidence`).

5. **`agents/finance/graph.py:95-108`**, cross-checked against `tests/test_solve_units.py:611` and
   `tests/test_profile_validate.py:14` — `make_verify_answer`/`make_profile_validate` are labelled
   "compatibility wrapper[s] for the moved node factory," implying `modules/solve/pipeline/nodes/verify.py`
   is now the canonical home. In practice, one test still imports the wrapper from `graph.py` while a
   sibling test imports the real function directly from `nodes/verify.py` — i.e. the codebase itself
   hasn't settled on one canonical import path, so "compatibility wrapper" reads as aspirational rather
   than descriptive of current usage.
   Direction: pick one canonical location (most likely `nodes/verify.py`, since that's where the docstring
   points), align both tests to it, and either delete the `graph.py` wrappers or explicitly mark them
   deprecated-only-for-external-callers.

6. **`agents/finance/prompts.py:11-24` vs. `agents/finance/understand.py:38-46`** — the question-intent
   schema (`tickers`, `years`, `metric`, `operation`, `doc_type`, `multi_year`, `multi_company`,
   `unit_hint`, `answer_shape`) is defined twice with no shared source of truth: once as a Vietnamese JSON
   comment block inside the prompt string, once as the `UnderstandIntent` Pydantic model. Nothing ties
   them together, so adding/renaming a field in one and forgetting the other fails silently (the model
   would just ignore or default the field; the LLM would just never see it documented).
   Direction: at minimum add a comment in each file pointing at the other as the paired definition; ideally
   generate the prompt's field list from the Pydantic model (or add a test asserting the two field-name
   sets match) so they can't drift.

7. **`agents/finance/graph.py:132-137`** — the conditional-edge wiring loop
   (`for after in [None, "solve_single_cell", ...]`) uses a bare `None` as a sentinel meaning "the first
   route, out of `trace_capabilities`," and un-sentinels it via `after or "trace_capabilities"`. The
   sentinel's meaning is only explained in `make_solver_router`'s docstring in a different file
   (`modules/solve/pipeline/router.py:34-39`); nothing in `graph.py` itself tells the reader why `None` is
   in a list of otherwise all-string node names.
   Direction: add a one-line comment at the loop in `graph.py` (not just in `router.py`) stating that
   `None` stands for "before any solver has run," since this is the one piece of graph topology that isn't
   self-evident from the edge list alone.

8. **`agents/finance/retrieve.py:12` vs. `agents/finance/understand.py:113`** — the two simplest, most
   parallel node factories in the package (each: read a few `FinanceState` keys, return a partial update)
   type their parameter and return value differently: `retrieve(state: Mapping[str, Any]) -> dict[str, Any]`
   vs. `understand(state: FinanceState) -> dict`. Neither typing is wrong, but the inconsistency means a
   reader can't tell, from the signature alone, whether "every node takes `FinanceState`" is a convention
   or a coincidence — worth checking before writing a new node function shaped like an outlier.
   Direction: standardize on `state: FinanceState -> dict[str, Any]` for every node factory in this
   package (that's the real contract both functions honor).

9. **`agents/finance/utils.py:1`** — the module docstring, "Pure helpers shared across agent nodes,"
   overstates the module's actual audience: `slot_round_robin` and `year_round_robin` are consumed only by
   `modules/solve/pipeline/evidence.py` (outside this package), not by any node inside `agents/finance/`.
   Only `expand_years` is used by a node in this package (`understand.py:141`). A reader looking for the
   caller of the round-robin helpers inside `agents/finance/` won't find one.
   Direction: either move `slot_round_robin`/`year_round_robin` next to their real caller
   (`modules/solve/pipeline/evidence.py`, which already carries the codegen-budget rationale comments for
   them), or adjust the docstring to say "used by understand.py directly, and by the codegen budget logic
   in modules/solve/pipeline."

10. **`agents/finance/understand.py:131`** — `except Exception as e:` catches everything from the
    structured-output LLM call (network errors, schema-validation errors, a bug in `UnderstandIntent`
    itself) into one fallback branch with one generic error string. Every other non-obvious decision in
    this file gets a rationale comment explaining why it's shaped the way it is; this one doesn't, so a
    reader can't tell if the breadth is deliberate (any failure here should degrade gracefully) or just
    the default "wrap it in try/except" reflex.
    Direction: add a short comment stating the intent (e.g. "any failure here should degrade to the
    rule-based ticker guess rather than crash the graph"), matching this file's own convention elsewhere.

11. **`agents/finance/graph.py:183-194`** — the `__all__` list re-exports a long tail of names imported
    from `modules/solve/pipeline/*` purely for pass-through (`SOLVER_CHAIN`, `codegen_budget`,
    `load_evidence`, `make_solve_formula_facts`, `make_solve_raw_selection_linker`, ...), none of which are
    used inside `graph.py` itself. This turns the graph-topology file into a de facto public-API
    aggregator for the whole solve pipeline, blurring "this file builds the graph" against "this file is
    the package's import surface."
    Direction: if downstream scripts/tests need these names, consider re-exporting them from a dedicated
    `__init__.py`/`api.py` so `graph.py`'s own import list reflects only what it uses to build the graph.

## Overall impression

The subsystem is, on balance, well above average for readability: the rationale-heavy comments in
`graph.py`, `utils.py`, and `understand.py` do real work (they answer "why this and not the obvious
alternative," with numbers), `base.py`/`agent.py`/`retrieve.py` are small and easy to hold in your head,
and the four-node-one-LLM-call framing in `graph.py`'s module docstring is a genuinely good map for a
newcomer. The friction that remains is concentrated in a handful of places where the code evolved (a node
was removed, a solver taxonomy was renamed, one field's persistence path was split into two) and the
nearby comment/type/test didn't get updated to match — items 1-5 above. If only one change could be made,
it would be **item 1** (the `selection_sub_tables` config-field inconsistency): it's the one place where
the drift is a silent behavioral trap rather than just a stale explanation, and it sits in the file new
engineers are told to treat as the authoritative reference for every other flag in the pipeline.
