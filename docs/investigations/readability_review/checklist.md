# Readability refactor checklist (synthesized from the 6 sub-agent reviews)

Ordered by effort/impact (80/20, simplest-first). Each phase is meant to be
its own small PR, verified independently — see "Verification" at the bottom.
Source detail for every item lives in the sibling `*.md` files in this
directory.

## Phase 0 — Trivial, near-zero risk (do first)

Pure deletions or one-line fixes. No design decision required.

| # | Item | Source | Effort | Impact | Trade-off |
|---|------|--------|--------|--------|-----------|
| 1 | Delete `core/config.py` — unused, duplicates the fragile LLM endpoint/model literals that already caused a real incident (per `core/llm.py`'s own comment) | core_tools.md #1 | trivial | **high** — removes a live two-sources-of-truth footgun | None. It's dead; grep confirms zero importers. |
| 2 | Fix `agents/finance/config.py:143` `selection_sub_tables` — not wrapped in `field(default_factory=...)` like every sibling flag, so `SOLVE_SUB_TABLES` set at runtime is silently ignored | agent_graph.md #1 | trivial (1 line) | **high** — this is the one item that's an actual bug, not just style | None — makes it consistent with every other flag in the same file. |
| 3 | Delete dead code: `python_exec.py:exec_in_namespace`, `data/repositories.py:TableRepository`, `solve/__init__.py` unused re-exports, `pipeline/outcome.py:SolverOutcome`, `agents/base.py`'s unused `run = invoke` alias | core_tools.md #2, data_rag.md #1, pipeline_codegen.md #8/#10, agent_graph.md | trivial | medium — stops new engineers from assuming these are live paths | If `SolverOutcome` is meant to eventually be enforced, deleting it means re-adding later — cheap either way. |
| 4 | Fix missing `from pathlib import Path` in `rag/indexing/bm25.py:94` and `rag/retrievers/filters.py:58` (only works today via postponed annotations) | data_rag.md #6 | trivial | low, but real — `typing.get_type_hints()`/tooling would crash | None. |
| 5 | Fix stale comments: `state.py`'s `# load node` header (node no longer exists), `state.py`'s solver enum-in-comment (lists wrong values), `pipeline/emit.py`/`outcome.py` missing one-line cross-reference on which to use | agent_graph.md #2/#4, pipeline_codegen.md #12 | trivial | medium — removes onboarding misdirection | None. |

**Why first:** zero behavioral risk, no cross-file ripple, and #1/#2 are the
two items in the entire review that carry real *correctness* risk (not just
readability) if left alone.

## Phase 1 — Mechanical consolidation (same logic, currently duplicated)

Still low-risk (pure "point at the existing canonical copy"), slightly more
files touched per item.

| # | Item | Source | Effort | Impact | Trade-off |
|---|------|--------|--------|--------|-----------|
| 6 | Consolidate 5 duplicate `_norm()` copies onto the one already-documented-canonical version in `common/intent.py` | facts_common.md #2 | low | **high** — this exact copy-paste pattern recurs across the whole review (see #7 too) | Must confirm all 5 copies are byte-identical in behavior before swapping (reviews suggest yes, but worth a diff check). |
| 7 | Consolidate `_unit_kind` (×3), `_rank_bonus` (×2), `_candidate_table_ids`/`_candidate_first_cell`/`_candidate_query` (×2) into one shared helper each | solvers.md #5/#6/#7 | low | medium | Same as #6 — verify the copies really are identical, not subtly diverged, before merging. |
| 8 | Extract `evidence_for(names)` helper for the 3× duplicated csv-path comprehension (`pipeline/emit.py`, `nodes/codegen.py` ×2) | pipeline_codegen.md #4 | trivial | low-medium | None. |
| 9 | Consolidate duplicated "primary statement" concept (`candidates.py:PRIMARY_STATEMENT_TYPES`/`add_primary_statements` vs `rag/service.py:_PRIMARY`/`_evidence`) | data_rag.md #5 | low | medium — real risk today if one is updated and not the other | Confirm both call sites actually want identical statement-type sets (reviews imply yes). |
| 10 | Drop the unexplained `DENSE_PATH = DENSE_INDEX_PATH` alias in `evaluation/retrieval.py:54`; have the two `diag_*.py` scripts import `DENSE_INDEX_PATH` directly | core_tools.md #7 | trivial | low | None. |

**Why second:** these are "same thing, said twice" fixes — mechanical,
testable by diffing behavior before/after, and they're the theme that shows
up most often across all 6 reviews (so fixing the pattern once here makes
the remaining instances easier to spot later).

## Phase 2 — Bounded design decisions (worth doing, needs a little judgment)

| # | Item | Source | Effort | Impact | Trade-off |
|---|------|--------|--------|--------|-----------|
| 11 | Fix `SOLVER_CHAIN` duplication: `agents/finance/graph.py` hand-retypes the solver wiring order that `pipeline/router.py:SOLVER_CHAIN` already owns | pipeline_codegen.md #11 (router.py), flagged again from graph.py side | medium | **high** — this is a real correctness risk (silent drift if someone edits one and not the other), not just cosmetics | Need to check graph.py's wiring loop can actually just iterate `SOLVER_CHAIN` instead of a hand-written copy — should be safe since router.py already owns the authoritative order. |
| 12 | Collapse 3 near-identical fact-solver node functions (`make_solve_structured_facts`/`selection_facts`/`formula_facts`) in `nodes/solvers.py` into one parameterized `_run_fact_solver(...)` helper | pipeline_codegen.md #2 | medium | **high** — flagged by that review as *the* single highest-value fix; it's the pattern a new engineer hits first ("how do I add a solver") | Slightly less "obvious at a glance" per-solver code, but removes the 3-copies-can-drift risk. |
| 13 | Factor the duplicated tool-turn generation loop out of `codegen/codegen.py` and `codegen/screening.py` into a shared `_agenerate_with_tools(...)` | pipeline_codegen.md #3 | medium | medium-high — largest single duplication block found in the whole review | Touches the actual LLM-calling code path; re-run gold eval after, even though it's meant to be behavior-neutral. |
| 14 | Merge/cross-reference the two independent Vietnamese ratio-alias catalogs (`facts/metrics.py:DERIVED_ALIASES` vs `common/metric_hints.py:_HINTS[*].aliases`) | facts_common.md #1 | medium | medium | Higher risk than most items here — the two lists are "overlapping but non-identical," so merging requires deciding which phrasing wins, not just deleting a copy. Do this one carefully, or just cross-reference them with a comment instead of merging, to stay behavior-safe. |

**Why third:** these need a small amount of judgment (confirm two things are
really the same before merging, or trace a wiring path before changing it),
but the payoff is the highest of any tier — items 11 and 12 in particular
were each independently called out as "the one change to make" by their
respective reviews.

## Phase 3 — Renames (zero logic change, but touch many import sites)

Behavior-neutral, but effort scales with how many files reference the old
name — do these as their own isolated commits so a bad rename is easy to
revert.

| # | Item | Source | Effort | Impact | Trade-off |
|---|------|--------|--------|--------|-----------|
| 15 | Rename `solvers/table_linking/` → e.g. `table_profiles/` (it profiles columns/rows and holds shared candidate schema, it doesn't "link" anything); clarify `raw_table_linker.py` as an explicit facade over `raw_table_linking/` | solvers.md #1/#2 | medium-high | **high** — called the single highest-value fix in the solvers review; the current naming implies the wrong dependency direction | Most import-touching item on this list — worth doing with a mechanical rename + import-fix pass, then a full test run. |
| 16 | Rename or delete `codegen/legacy.py`'s shim (name/docstring both claim it's a deprecated path being replaced; it's actually the only live path) | pipeline_codegen.md #1 | medium | medium | Two call sites only (`nodes/codegen.py`, `nodes/verify.py`) — low blast radius. |
| 17 | Rename `pipeline/nodes/codegen.py` → `nodes/generate.py` to remove the basename collision with `codegen/codegen.py` | pipeline_codegen.md #9 | medium | medium | Purely a filename/import change; check test files that import by path. |
| 18 | Rename `metadata_v3.py` away from the `_v1`/`_v2` versioned-artifact pattern (it's an unmerged experiment, not a successor to v2) | data_rag.md #3 | low-medium | medium | Few call sites (its own script + nothing in the live pipeline) — cheap and removes a real "which one is production" trap. |

## Phase 4 — Structural splits (optional, do only if there's appetite)

Larger diffs, more test surface, genuinely lower urgency than everything
above — the reviews flagged these as real but secondary.

- Split `verify_answer` (~115 lines, 8+ early returns) into named helpers — pipeline_codegen.md #6
- Split `facts/store.py`'s bank-CSV-fallback logic into its own module — facts_common.md #4
- Split `aprepare_raw_selection_linker` (156 lines) into staged helpers — solvers.md #4
- Collapse the 18-`*_func`-kwarg DI surface in `raw_table_linking/prepare.py` into one deps object — solvers.md #3
- Split `CandidateRetriever.__init__` (~105 lines) into named steps — data_rag.md #4
- Give `preprocessing/`'s offline scripts (`metadata_enrichment.py`, `metadata_v3.py`, `statement_type_classifier.py`, `grid.py`, `header_flatten.py`) a distinct subfolder — data_rag.md #2
- Everything else in the 6 source files not listed above (dispatch-table for `formula_facts.py`, `_unexpressible` predicate split, `dataframe.py` repair-tail dedup, `pool()` rename, `deepinfra.py` cross-references, stats/report-generation dedup across preprocessing builders) — cosmetic-tier, lowest priority.

## Verification (per this repo's own convention, not new)

Even though every item above is meant to be behavior-neutral, this repo's
established norm is "never claim unchanged without re-measuring." After each
phase (not each individual item):
1. `pytest` (or whatever the current test invocation is) to catch import
   breakage from renames/deletions.
2. A gold-set run (`scripts/score_gold75.py` or equivalent) to confirm the
   score is unchanged — a refactor that silently breaks an import path inside
   a try/except (several solvers report-and-continue on exceptions) could
   regress the score without throwing.
