# Readability review: solve pipeline + codegen

Scope: `modules/solve/pipeline/{emit,evidence,outcome,router}.py`,
`modules/solve/pipeline/nodes/{codegen,solvers,verify}.py`,
`modules/solve/codegen/{codegen,execute,legacy,screening,verify}.py`.

Reviewed for readability/maintainability only — no accuracy/behavior changes
suggested. The project's WHY-comments (measured tradeoffs, qid-linked bug
history) are treated as an asset, not flagged.

1. **`codegen/legacy.py:1-6`** (and its callers `pipeline/nodes/codegen.py:8`,
   `pipeline/nodes/verify.py:8`) — This module is a pure re-export shim over
   `codegen.codegen`, but its docstring claims the purpose is to let "new
   plan-based codegen sit beside it" — that never happened, nothing else
   implements the alternative, and `solve/__init__.py:16` imports the same
   symbol directly from `codegen.codegen`, bypassing this shim entirely. The
   name "legacy" now reads backwards (it's the only, current, live path, not
   a deprecated one), and the docstring's stated rationale is stale/false.
   Suggest either deleting the shim and importing `codegen.codegen` directly
   at the two call sites, or renaming it (e.g. `expression_codegen.py`) and
   rewriting the docstring to state what's actually true today.

2. **`pipeline/nodes/solvers.py:185-304`** — `make_solve_structured_facts`,
   `make_solve_selection_facts`, `make_solve_formula_facts` are ~35-line
   near-duplicates: identical try/except shape, identical call into
   `answered(...)` with the same eight keyword arguments, differing only in
   which `asolve_*` function is invoked, the exception type, and the
   solver-name string. Extract a single
   `_run_fact_solver(state, solver_name, fn, error_type)` helper parameterized
   over those three differences; the risk today is one copy silently
   drifting from the other two.

3. **`codegen/codegen.py:253-347` (`agenerate`) vs `codegen/screening.py:277-347`
   (`agenerate_screening`)** — The tool-turn loop (bind_tools, submit
   detection, "no calls → nudge" branch, transcript/calls_made bookkeeping) is
   copy-pasted almost verbatim between the two functions; only the submitted
   Pydantic model and system prompt differ. The comment in `screening.py:273-276`
   says this is "reused verbatim," but only the constants/`_run_tool` are
   actually imported — the ~30-line loop body itself is duplicated. This is
   the largest real duplication found in this subsystem. Worth factoring the
   loop into a shared `_agenerate_with_tools(system, submit_model, ...)` that
   both functions call.

4. **`pipeline/emit.py:29-31` vs `pipeline/nodes/codegen.py:31-34` and `:72-75`**
   — The exact same list comprehension
   (`{"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"} for var, tid in names.items()`)
   is written three separate times across two files. Extract one
   `evidence_for(names) -> list[dict]` helper (e.g. in `evidence.py`) and use
   it in all three places.

5. **`codegen/screening.py:29-39`** — imports underscore-prefixed "private"
   names (`_SCOPE_HEADERS_ONLY`, `_SCOPE_WITH_GRIDS`, `_TOOLS_SYSTEM`,
   `_run_tool`) directly from `codegen.py`. The leading underscore signals
   "internal to this module," but a sibling module treats them as public API.
   Either drop the underscores to mark these as intentionally shared, or move
   them into a small shared internal file (e.g. `_tool_loop.py`) that both
   `codegen.py` and `screening.py` import from as peers.

6. **`pipeline/nodes/verify.py:61-177` (`verify_answer`)** — handles at least
   five distinct scenarios in sequence: config-off short-circuit, "query
   never ran" short-circuit, screening observe-only, narrow-solver
   observe-only (with its own nested evidence-loading fallback), and the real
   verify+revise flow — all via early `return`/`return {**drop, ...}`
   statements interleaved with heavy commentary. ~115 lines with 8+ early
   returns is hard to hold in your head. Splitting into named helpers (e.g.
   `_narrow_solver_prompt(state, config)`, `_observe_only(state, verdict, drop)`,
   `_revise_and_reexecute(...)`) — each keeping its own comment block — would
   let a reader skim the top-level function as a sequence of named steps.

7. **`pipeline/nodes/solvers.py:307-361` (`solve_raw_table_linker`) vs
   `:364-419` (`solve_raw_selection_linker`)** — structurally identical
   except `solve_raw_selection_linker` computes `table_ids = append_unique(...)`
   and passes it to `emit_solver_result`, while `solve_raw_table_linker` never
   touches `table_ids`. Every other deliberate asymmetry in this codebase
   gets a one-line comment explaining it; this one doesn't, so a new engineer
   can't tell if it's intentional or an oversight. Either add the reason or
   make the two functions consistent.

8. **`solve/__init__.py:16-20`** — `PandasSolution`, `aexecute`, `agenerate`
   are re-exported here as the package's public surface, but nothing in
   `src/` actually imports `finance_qa.modules.solve` (all real call sites
   reach into `solve.codegen.execute` / `solve.codegen.legacy` /
   `solve.codegen.codegen` directly). Either wire real callers through it, or
   delete it.

9. **`pipeline/nodes/codegen.py` (whole file) vs `codegen/codegen.py` (whole
   file)** — Two unrelated files share the basename `codegen.py`: one is the
   LangGraph node wiring (`make_generate_pandas`, `make_execute_and_repair`,
   `asub_value`), the other is the actual LLM-calling implementation
   (`CODEGEN_SYSTEM`, `agenerate`, tool loop). Any grep for "codegen.py" is
   ambiguous without the full path. Renaming the node-wiring file to
   something like `nodes/generate.py` would remove the collision.

10. **`pipeline/outcome.py:15-21` (`SolverOutcome`)** — declared as "the
    diagnostic contract stored at `diag[solver_name]`" but never used as an
    actual type annotation anywhere (grep confirms zero usages beyond its own
    definition and `__all__`). Either start annotating the diag payload
    builders with it, or drop it and fold its meaning into the module
    docstring as prose.

11. **`pipeline/router.py:14-21, 42-58`** — `SOLVER_CHAIN` is a
    `list[tuple[str, str, str]]` (flag attr name, node name, diag key)
    unpacked positionally in three different places. The three roles are
    easy to swap by accident when adding a new solver to the chain since
    nothing but position tells you which slot is which. A small
    `NamedTuple("SolverStep", flag, node, diag_key)` would make each
    unpacking self-documenting at negligible cost.

12. **`pipeline/emit.py` vs `pipeline/outcome.py`** — two independent "a
    solver succeeded" builders: `emit_result`/`emit_solver_result` (used by
    codegen-shaped solvers) and `answered` (used by fact-based solvers). The
    split is reasonable given the two solver families genuinely differ, but
    neither module's docstring says so — a new engineer adding solver #7 has
    to reverse-engineer which builder to reach for. A one-paragraph note in
    either docstring would close that gap cheaply.

## Overall impression

The WHY-comments are consistently strong throughout this subsystem — the
codegen/execute/verify files read like a lab notebook of measured tradeoffs,
and that is a real asset, not noise. The readability drag is structural
duplication: the same "wrap an `asolve_*` call in try/except and forward to
`answered(...)`" shape is written out by hand three times in
`nodes/solvers.py`, and the tool-turn generation loop is copy-pasted between
plain and screening codegen.

**If only one change could be made:** collapse the three near-identical
fact-solver node functions in `nodes/solvers.py` into one parameterized
helper (item 2) — it's the highest-frequency pattern a new engineer needs to
understand first ("how do I add a new solver to this graph"), and today that
answer is scattered across three copies that can silently drift out of sync.
