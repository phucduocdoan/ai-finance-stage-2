# Solve subsystem architecture

How `src/finance_qa/modules/solve/` turns one retrieved evidence set into one
submitted `(answer, pandas_query)` pair. This is a map of the code, not a
measurement log; measurement history for individual flags lives in
[`docs/config_flags.md`](config_flags.md).

## Scope

`src/finance_qa/modules/solve/` is 60 Python files, 15,653 lines, 521 function
definitions (`def`/`async def`, module-level and nested), grouped as:

- `codegen/` — the LLM fallback that reads evidence grids and writes one
  pandas expression (`codegen.py`, `execute.py`, `expression_codegen.py`,
  `screening.py`, `verify.py`)
- `common/` — shared helpers used across solvers: column/unit detection,
  intent regexes, row lookup, the `PandasSolution` schema
- `facts/` — the normalized main-statement fact catalog and its executor
  (`structured_facts.py` is a facade re-exporting `metrics.py`, `schema.py`,
  `store.py`, `execute.py`, `planner.py`; `bank_fallback.py`, `cellexpr.py`,
  `profile_validate.py` and `table_profile.py` sit alongside it)
- `pipeline/` — the LangGraph node factories and routing that wire everything
  together (`pipeline/nodes/solvers.py`, `pipeline/nodes/generate.py`,
  `pipeline/router.py`, `pipeline/emit.py`, `pipeline/evidence.py`,
  `pipeline/outcome.py`)
- `solvers/` — the deterministic and semi-deterministic solvers themselves,
  plus two subpackages: `raw_table_linking/` (the `raw_table_linker` /
  `raw_selection_linker` internals) and `table_profiles/` (typed row/column
  linking primitives shared by the raw-table solvers)

## The eight solvers and the two axes

Two things distinguish a question: which data source can answer it, and what
shape the answer takes.

- **Data source.** The normalized fact catalog (`facts/`, built from
  `long_format.parquet`, VAS-coded rows only) or the raw CSV table for the
  page the question is about.
- **Question shape.** A single-cell lookup, a fixed-scope arithmetic
  expression (ratio, growth, diff, average, median — all over one resolved
  ticker/year scope), or a selection (argmax/argmin over a year or ticker
  axis).

The raw-CSV row of that grid is a clean one-solver-per-shape split:

| | single-cell lookup | fixed-scope arithmetic | selection |
|---|---|---|---|
| raw CSV table | `solvers/cell_locator.py` | `solvers/raw_table_linker.py` | `solvers/raw_selection_linker.py` |

Each docstring confirms its cell: `cell_locator` is "intentionally narrower
than codegen: it only handles questions that already look like one ticker,
one year, one value" (`solvers/cell_locator.py:1-7`); `raw_table_linker`
covers "questions whose scope is already fixed, but whose facts live in raw
CSV tables" (`solvers/raw_table_linker.py:1-9`); `raw_selection_linker`
"choose[s] the year/company with the largest or smallest raw-table metric"
(`solvers/raw_selection_linker.py:1-8`).

The fact-catalog row is not a clean 1:1:1 split, and the source claiming it is
would be wrong:

- `solvers/formula_facts.py` covers **both** lookup and arithmetic. Its
  `FormulaOperation` enum is `Literal["lookup", "ratio", "growth", "diff",
  "avg", "median"]` (`solvers/formula_facts.py:38`), and its own field
  description reads "lookup/ratio: one ticker and one year; growth: one
  ticker and two years..." (`solvers/formula_facts.py:111-117`). It is one
  solver spanning two columns, not two solvers.
- `solvers/selection_facts.py` covers selection: "a smaller and safer sibling
  of `structured_facts`. It only builds a plan when the question has one
  clear selection axis" (`solvers/selection_facts.py:1-7`), with "no LLM
  planner here" (same docstring).
- `facts/structured_facts.py` is **not** the fact-catalog lookup cell. Its
  docstring calls it "deliberately narrower than the raw-grid codegen path"
  and says it "handles... especially selection questions across years or
  companies" (`facts/structured_facts.py:1-7`). More precisely: its
  *executor* schema (`StructuredPlan.operation`, `facts/schema.py:16-19`)
  still declares `lookup`/`ratio`/`growth`/`diff`/`avg`/`median` alongside
  `argmax`/`argmin`/`conditional_select`/`filter_aggregate`, but its
  *LLM-facing planner* schema only ever fills a selection plan: `PlannerPlan
  = StructuredSelectionPlan | UnsupportedStructuredPlan`
  (`facts/schema.py:296-299`) has no plain-lookup branch, and the heuristic
  fallback used when the LLM call fails always returns `supported=False`
  (`facts/planner.py:95-117`). `capability_router.py` labels it accordingly:
  `_structured_facts_decision`'s trace reason is literally `"planner-gated
  main-statement selection"` (`solvers/capability_router.py:161-168`). So in
  practice `structured_facts` is a third, broader, off-by-default solver in
  the **selection** column: an LLM-planned, wider-coverage counterpart to the
  deterministic `selection_facts`, not a counterpart to `cell_locator`.

So the fact-catalog row reads: `formula_facts` (lookup + arithmetic),
`selection_facts` (selection, deterministic), `structured_facts` (selection,
LLM-planned, off by default). `codegen/` is the LLM fallback that every
question can reach if nothing above answers it — it does not sit in one cell,
it covers all of them by not being scoped to one data source or shape at all.

`solvers/decompose.py` is not a grid cell either. It is a fan-out strategy for
selection-shaped questions: split the axis into elements, ask one codegen
sub-question per element (`rank_metric`, optionally `filter_metric`, then
`answer_metric` at the winner), and let Python do the argmax/argmin
(`solvers/decompose.py:1-30`, `pick` at `solvers/decompose.py:256-`). Read
literally, "layered on the selection column" over-states it: the sub-questions
it issues always go through `codegen.agenerate` + `execute.aexecute`
(`pipeline/nodes/generate.py:135-160`, `asub_value`), never through
`selection_facts` or `raw_selection_linker`. It is better described as a
fan-out layered on **codegen**, reached only for selection-shaped questions
and only after every solver in the chain below has declined.

## Routing: three places, one that decides

Routing is described in three files. Only one of them drives execution.

**`pipeline/router.py` decides dispatch at runtime.** `SOLVER_CHAIN`
(`pipeline/router.py:14-21`) is the ordered list `cell_locator ->
formula_facts -> raw_table_linker -> selection_facts -> raw_selection_linker
-> structured_facts`. `make_solver_router` (`pipeline/router.py:34-58`)
builds one LangGraph conditional edge per chain position: after each solver
node, if that solver marked its `diag` entry done, go to `verify_answer`;
otherwise walk the remaining chain and dispatch to the first one whose
`config.<flag>` is true; if none remain, call `selection_route`.
`selection_route` (`pipeline/router.py:24-31`) sends the question to
`solve_selection` when `config.selection_decompose` is set and the question
has a selection axis, otherwise to `generate_pandas` (codegen).
`route_after_selection` (`pipeline/router.py:61-63`) sends a completed
fan-out to `verify_answer`, and an inconclusive one to `generate_pandas`. This
machinery is wired into the live graph in `agents/finance/graph.py:132-136`,
which builds one conditional-edge set per `after in [None, *SOLVER_CHAIN
nodes]` and attaches `solve_selection`'s own conditional edges.

**`pipeline/nodes/solvers.py` holds the node bodies the router dispatches
to**, not routing logic. `make_solve_selection` / `solve_selection`
(`pipeline/nodes/solvers.py:54-182`) is the fan-out executor described above:
it re-derives the axis with its own `axis_of` call, runs the ranking and
(optional) filter sub-questions concurrently, picks a winner, and answers the
final sub-question at that winner. It is reached only through
`selection_route`; nothing in this file decides whether to reach it.

**`solvers/capability_router.py` is diagnostic only.** Its own module
docstring says so: "deliberately diagnostic: it mirrors the graph's current
fail-closed solver order without deciding answers or replacing solver guards"
(`solvers/capability_router.py:1-7`). `capability_trace`
(`solvers/capability_router.py:23-78`) computes an `order` list from the
same eight-name sequence (embedded at `solvers/capability_router.py:64-74`)
filtered to `enabled`, plus a `decisions` map, and writes it into
`diag.capability_router` via the `trace_capabilities` node
(`pipeline/nodes/solvers.py:383-403`, wired at `agents/finance/graph.py:116`
and `:131`, one hop before the real routing starts at
`agents/finance/graph.py:134`). It never gates a node.

Three things about `capability_trace` worth knowing before reading it as a
per-question log: `enabled` on every decision is `config.<flag>` passed
through verbatim from `make_trace_capabilities`
(`pipeline/nodes/solvers.py:390-399`), so it is fixed for the whole run and
cannot vary per question. `_structured_facts_decision(*, enabled)` does not
receive `state` at all (`solvers/capability_router.py:161-168`), so its
`attempt` is always `True` once enabled; the only thing that varies per
question is nothing. `_selection_decision` does receive `state`
(`solvers/capability_router.py:171-190`), but only `attempt`, `axis` and
`elements` vary by question; `enabled` still does not.

## Config gating

Every solver except `codegen` is gated by one boolean field on
`FinanceAgentConfig` (`agents/finance/config.py`), overridable by an
environment variable read once at construction (`_flag`,
`agents/finance/config.py:21-24`). `codegen` has no field: it is the
unconditional fallback, hardcoded `enabled: True` in
`capability_router.py:56-60` and reached whenever `SOLVER_CHAIN` and
`selection_route` both fall through.

| solver | config field | env var | default |
|---|---|---|---|
| `cell_locator` | `cell_locator` | `SOLVE_CELL_LOCATOR` | on |
| `codegen` | (none — unconditional fallback) | — | on |
| `formula_facts` | `formula_facts` | `SOLVE_FORMULA_FACTS` | on |
| `raw_selection_linker` | `raw_selection_linker` | `SOLVE_RAW_SELECTION_LINKER` | on |
| `raw_table_linker` | `raw_table_linker` | `SOLVE_RAW_TABLE_LINKER` | on |
| `selection_facts` | `selection_facts` | `SOLVE_SELECTION_FACTS` | on |
| `structured_facts` | `structured_facts` | `SOLVE_STRUCTURED_FACTS` | off |
| `selection_decompose` | `selection_decompose` | `SOLVE_DECOMPOSE` | off |

(`agents/finance/config.py:50`, `:53`, `:60-62`, `:74-76`, `:80-82`,
`:104-106`, `:140`.) `structured_facts` and `selection_decompose` are the two
off-by-default entries; every other gated solver defaults on. A handful of
solvers also carry their own sub-flags (`raw_table_linker_planner`,
`*_planner_thinking`, `raw_table_linker_ratio_groups`) — see
[`docs/config_flags.md`](config_flags.md) for those and for the measurements
behind each default.

## The codegen path

`codegen/` is what every question falls through to once `SOLVER_CHAIN` and
`selection_decompose` (if enabled) have both declined. Three files carry the
flow:

- **`codegen/codegen.py`** — "One LLM call: read the evidence grids, emit one
  pandas expression" (`codegen/codegen.py:1-16`). `build_prompt`
  (`codegen/codegen.py:121-145`) renders every evidence table into a grid
  block (optionally with metric hints and a table profile) under
  `CODEGEN_SYSTEM` (`codegen/codegen.py:64-118`), which instructs the model
  to index by `.iloc[...]` position, copy column headers character for
  character, and report the value's `source_unit` and `target_unit` without
  scaling it itself. `agenerate` (re-exported, not separately defined here)
  is the call that turns that prompt into a `PandasSolution`.
- **`codegen/expression_codegen.py`** — a 25-line adapter
  (`codegen/expression_codegen.py`) that re-exports `codegen.codegen`'s
  `CODEGEN_SYSTEM`, `MAX_TOKENS`, `FindRows`, `ShowTable`, `agenerate` and
  `build_prompt` for the pipeline nodes to import. Its own docstring: "the
  current, only live codegen path in production — not a legacy fallback."
- **`codegen/execute.py`** — "Run the query, repair it at most twice, then
  apply the unit conversion" (`codegen/execute.py:1-8`). `aexecute`
  (`codegen/execute.py:550-603`) calls `arun_with_repair`
  (`codegen/execute.py:207-245`) first: it executes `solution.pandas_query`,
  and on an exception asks `_arepair` for a new query, up to `MAX_REPAIRS = 2`
  additional attempts (`codegen/execute.py:44`). Only once a query executes
  does `aexecute` call `apply_units` (`codegen/execute.py:476-547`, invoked
  at `codegen/execute.py:579`) to convert the raw cell value from its
  detected `source_unit` to the question's `target_unit`, strip any scale
  factor the model wrote into its own query, and apply a magnitude/percent
  transform where the question calls for one. Repair fixes execution errors;
  scaling is deterministic and runs after, once, on whichever query survived
  repair — see the ordering rationale in `codegen/execute.py:1-8`.

`codegen/screening.py` and `codegen/verify.py` also live in this package
(screening-shaped filter-then-aggregate questions, gated by
`config.screening_solver`; and the post-execution "did this query read the
right cell" check used by the `verify_answer` node) but are outside what this
section was asked to cover in detail.

## Where to start reading

To follow one question end to end, in this order:

1. **`src/finance_qa/agents/finance/graph.py`** — `build_graph` is the
   topology: `understand -> retrieve -> trace_capabilities -> [SOLVER_CHAIN]
   -> generate_pandas -> execute_and_repair -> verify_answer ->
   profile_validate`. The module docstring (`agents/finance/graph.py:1-42`)
   explains why there is one path plus one selection branch, and what each
   node cost or bought when measured.
2. **`src/finance_qa/modules/solve/pipeline/router.py`** — `SOLVER_CHAIN` and
   `make_solver_router` are the actual dispatch logic behind step 1's
   bracketed chain.
3. **`src/finance_qa/modules/solve/pipeline/nodes/solvers.py`** — the node
   bodies each `SOLVER_CHAIN` entry and `solve_selection` run; read
   `_run_fact_solver` and `_run_linked_solver` first, since every fact/raw
   solver node is a thin wrapper around one of those two.
4. **One solver docstring matching the question you care about** —
   `solvers/cell_locator.py`, `solvers/formula_facts.py`,
   `solvers/raw_table_linker.py`, `solvers/selection_facts.py`,
   `solvers/raw_selection_linker.py`, or `facts/structured_facts.py`.
5. **`src/finance_qa/modules/solve/codegen/codegen.py`** — where every
   question ends up if nothing above claimed it.

## Open questions

- `facts/bank_fallback.py`, `facts/cellexpr.py` and `facts/profile_validate.py`
  were not read in enough depth to describe here; `facts/cellexpr.py` is
  referenced from `README.md` as the fix that made fact solvers emit a real
  cell read instead of the answer itself, but its own mechanics are not
  covered by this document.
- `solvers/table_profiles/` and `facts/table_profile.py` are two different
  things with confusingly similar names (typed linking primitives for raw
  solvers vs. a descriptive profile of one evidence table used in codegen
  prompts). Both are named above; neither is documented in depth here.
