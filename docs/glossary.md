# Glossary

Domain vocabulary for this finance tabular QA codebase. Every entry points at
a real usage so the definition can be checked against the code it describes.
Vietnamese terms are kept as headwords because that is how they appear in
code, prompts, and data; the definition is in English.

Entries are alphabetical.

### answer accuracy / execution accuracy / F2

The three leaderboard metrics, defined in the competition rules
(`docs/competition/Thể lệ Stage 2.pdf`, section VII). Table retrieval (50% of
the score) is scored by macro-averaged Precision, Recall, and F2 = (5 x P x R)
/ (4P + R) over `relevant_tables`. Answer accuracy is the share of questions
whose `answer` matches gold within the competition's tolerance. Execution
accuracy is the share of `pandas_query` values that both run and return the
right number — it can differ from answer accuracy when a post-processing step
(see `below-floor rescale`) edits both `answer` and `pandas_query` by the same
factor, since execution accuracy re-runs the query independently
(`scripts/rescale_below_floor.py:26-28`).

### arm

Used in two related but distinct senses. In `docs/config_flags.md` (e.g.
`docs/config_flags.md:124`, `docs/config_flags.md:130`, `docs/config_flags.md:297`)
an arm is one side of a measured A/B comparison — "treatment arm" or "control
arm" for a single config flag. In `scripts/fill_from_arms.py:9-10,25-26` an arm
is one candidate run file passed to the script, ranked by trust order; the
first arm whose answer is not "certainly wrong" wins that cell
(`scripts/fill_from_arms.py:25-26`). Both senses mean "one variant among
several being compared," but the comparison is a flag's on/off state in the
first case and a whole run's output in the second — worth keeping apart when
reading either file.

### axis / `axis_of`

The dimension a selection question fans out over — `"year"` or `"ticker"` —
when it names a period or several companies rather than one cell.
`axis_of` (`src/finance_qa/modules/solve/solvers/decompose.py:136-161`) reads
the resolved years/tickers and question text, and returns `(axis, elements)`
or `None` to keep the current (non-fanned-out) path. Years win over tickers
when both are plural (`decompose.py:141`). Consumed by `selection_decompose`
(`src/finance_qa/modules/solve/pipeline/router.py:24-29`) and by
`capability_trace` (`src/finance_qa/modules/solve/solvers/capability_router.py:13`).

### below-floor rescale

A post-processing pass, `scripts/rescale_below_floor.py`, that runs on a
completed run file between `run_graph.py` and `build_submission.py`
(`scripts/rescale_below_floor.py:3-4`). It multiplies an answer by a power of
ten when it falls below a unit-specific floor (e.g. an answer in `tỷ` below
`0.1`, `scripts/rescale_below_floor.py:46-53`) — the fix for one specific
failure shape (mantissa plausible, exponent off by a power of ten), not for
the unrelated "vượt trần" (over ceiling) failures, whose gold deltas are not
power-of-ten multiples (`scripts/rescale_below_floor.py:7-9`). One-directional:
it only touches values that are already almost-certainly wrong, so a
wrong-to-wrong change cannot lose points
(`scripts/rescale_below_floor.py:23-25`). It edits `pandas_query` too, not
just `answer` (`scripts/rescale_below_floor.py:27`).

### capability trace / capability router

`capability_trace` (`src/finance_qa/modules/solve/solvers/capability_router.py:23`,
docstring at lines 34-38) is a diagnostic function that mirrors the graph's
fail-closed solver order (module docstring, line 4) and reports which solver
would attempt a question and why, without executing anything or choosing an
answer. It is attached to the
pipeline state as `"capability_router"` in
`src/finance_qa/modules/solve/pipeline/nodes/solvers.py:390`. The module is
named `capability_router.py`, but the router that actually walks solvers in
order and picks one is a separate module,
`src/finance_qa/modules/solve/pipeline/router.py` (docstring at line 3,
`SOLVER_CHAIN` at line 14) — `capability_router.py` only traces what that
router would do.

### cell read / cell locator request

A `CellRequest` (`src/finance_qa/modules/solve/solvers/cell_locator.py:117`)
is the bounded, deterministic query the `cell_locator` solver builds for an
L1-shaped question (exactly one ticker, one year, no derived/comparison
marker): metric phrases, ticker, year, doc type, period, value transform, and
target unit. `build_request` (`cell_locator.py:208-235`) is the gate that
either returns a `CellRequest` or a string reason it declined (fail-closed).
Downstream, `cell_locator` verifies row/column/unit against the actual table
before emitting a `PandasSolution` (see below) — it never hands the model the
answer directly.

### fact catalog / normalized fact table / `long_format`

The normalized long-format fact table at `data/derived/long_format.parquet`,
accessed through `StatementFactStore`
(`src/finance_qa/modules/solve/facts/store.py:1,28`) via DuckDB. Its
docstring calls it "the normalized main-statement fact table"; each row is one
VAS `ma_so` fact for one `(report_id, table_pos)` at one period. `formula_facts`
(`src/finance_qa/modules/solve/facts/execute.py:239`) and `structured_facts`
(`src/finance_qa/modules/solve/facts/structured_facts.py:1`) read from it; it
covers the main balance sheet / income statement / cash flow statements only —
notes, entity, and equity tables are outside it
(`docs/config_flags.md:279-280`, describing the "gold94" scoring gate).

### fail-closed

The design rule that a deterministic solver, when it cannot verify its own
answer with confidence, declines and falls through to the next solver rather
than guessing. Named explicitly in `src/finance_qa/modules/solve/pipeline/router.py:3-4`
("walks enabled fail-closed solvers in order"),
`src/finance_qa/modules/solve/solvers/capability_router.py:4`, and per-solver
docstrings, e.g. `src/finance_qa/modules/solve/solvers/selection_facts.py:6`
("unsupported shapes fail closed to raw-table codegen") and
`src/finance_qa/modules/solve/solvers/raw_table_linking/request.py:204`.

### gold73

The 73-question subset of the two hand-checked gold sets (`unbiased60_gold.jsonl`,
60 questions, plus `manual15_gold.jsonl`, 15 questions — 75 total) used by
`scripts/score_gold75.py`, after dropping rows whose `confidence` is below
`medium` (`scripts/score_gold75.py:5-6`; despite the "75" in the script name,
the scored denominator is 73). `docs/config_flags.md:97-99` describes this
measurement; `docs/config_flags.md:125` and `:189` use "gold73" as the name
for the scored set. It is described elsewhere in the same doc as partially
contaminated — 27 of its 75 source ids are hardcoded in `src`/`tests`
(`docs/config_flags.md:191`).

### magnitude / `as_magnitude`

`as_magnitude` (`src/finance_qa/modules/solve/codegen/execute.py:273-283`) asks
whether a question wants the unsigned amount of a cell rather than its printed
(possibly negative, parenthesized) sign — e.g. an expense row printed as
`(83.790.676.915)`. It wraps the whole `pandas_query` result in `abs()` when
true (`execute.py:528`). Distinct from the narrower `value_transform` in
`cell_locator.py:195-205`, which some solvers already apply per-term; codegen
only gained this check after a measured failure (q526).

### `main-statement`

Shorthand, used in several fact-solver docstrings, for the three primary VAS
financial statements — balance sheet, income statement, cash flow statement —
as opposed to notes/detail tables. See `src/finance_qa/modules/solve/facts/store.py:1`,
`structured_facts.py:1`, `table_profile.py:5`, `execute.py:239`.

### PandasSolution / `ScreeningSolution`

`PandasSolution` (`src/finance_qa/modules/solve/common/solution.py:36-48`) is
the shared output contract every solver asks the model to fill: which table
and cell it read (`table_variable`, `target_row`, `target_column`), the source
and target unit, and the resulting `pandas_query`. `cell_locator`,
`raw_table_linker`, `raw_selection_linker`, `formula_facts`, and
`selection_decompose` all submit one (`solution.py:5-6`).
`ScreeningSolution` (`solution.py:64-114`) extends it for screening questions:
the model never writes `pandas_query` itself — `screening.compose` builds it
deterministically from a per-company `SeriesPart` list plus a condition, so a
filter predicate has somewhere to live (`solution.py:68-71`,
`src/finance_qa/modules/solve/codegen/screening.py:13-15`).

### `pandas_query`, `relevant_tables`, `relevant_docs`, `evidence`

Fields of one submission item, assembled by `submission_item`
(`src/finance_qa/pipelines/submission.py:13-34`). `relevant_tables` is every
table id handed to the planner, not only the ones the final query reads,
because retrieval is scored separately and trimming it would throw away
recall (`submission.py:18-21`). `relevant_docs` is the set of report ids
implied by `relevant_tables` (`submission.py:23-25`). `evidence` is narrower
and must match the query exactly (`submission.py:21`); it can legitimately be
empty even on a solved question, e.g. every `formula_facts` answer ships
`evidence: []` (`src/finance_qa/modules/solve/facts/cellexpr.py:8`).
`pandas_query` is the single pandas expression that reproduces `answer`; the
competition also re-runs it to compute execution accuracy.

### PoT / CoT

The two answering strategies the organisers benchmark against each other.
Defined on pages 33-35 of
`docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf` (that PDF has a
real text layer; `pdftotext`/`pdftoppm` are not installed on this machine, but
`pypdf` inside `.venv_bge` extracts it fine).

**PoT (program-of-thought)** — the LLM emits executable Python/pandas, the code
runs in a sandbox, and the value assigned to `result` is the answer. Strengths:
exact arithmetic, no numeric drift. Weaknesses: one syntax error loses the
question outright, and it needs a strong code model. This is what our pipeline
does; `pandas_query` in every run file is the emitted program.

**CoT (chain-of-thought)** — the LLM reasons in prose and states the number
directly in its text. Strengths: flexible, cannot crash. Weaknesses: arithmetic
slips and loose output formatting.

Page 42 carries the organisers' own recommendation: PoT for frontier or large
code models, CoT for models under 10B "để tránh crash code", with page 39
putting the PoT syntax-error rate for sub-10B models at up to 99%. Our server
is a 9B model running PoT, so this is a live architectural question rather than
settled trivia — see [`docs/config_flags.md`](config_flags.md) for what has
actually been measured here.

### `report_id` / `table_pos`

The two fields that key every table in the corpus; `f"{report_id}|{table_pos}"`
is the table id used everywhere downstream (`src/finance_qa/modules/rag/candidates.py:86-87`,
`src/finance_qa/modules/solve/facts/store.py:102`). `report_id` encodes ticker,
year, and consolidated/separate scope (`src/finance_qa/modules/rag/judge.py:14,63`).
The competition's own submission format uses the same convention under a
different name: `relevant_tables` entries are `"<id_báo_cáo>|<vị trí trong báo
cáo>"` (`docs/competition/Thể lệ Stage 2.pdf`, section VI, sample item).

### screening

A question that filters a group of companies by a condition and reduces the
survivors to one number ("trong nhóm các doanh nghiệp có ROE > 15%, ai có D/E
thấp nhất"). Detected by `is_screening`
(`src/finance_qa/modules/solve/common/screening.py:27`), a heuristic on
distinct ticker count (>= 3) or a set of Vietnamese group-scoping phrases —
explicitly noted to undercount questions that name companies in full rather
than by ticker or phrase (`common/screening.py:10-13`). The screening solver
itself (`src/finance_qa/modules/solve/codegen/screening.py:3-7`) exists
because a single `pandas_query` has nowhere to put a filter predicate: plain
codegen folds every company straight into one expression and scores 4/29 on
the clean eval where the rest of a run scores 45/90.

### unbiased60

The 60-question set at `data/eval/unbiased60_gold.jsonl`, sampled without bias
(as opposed to the tuned 363-440 id band), scored by
`scripts/score_unbiased60.py` (docstring at lines 1-13). Used alone or unioned
with `manual15_gold.jsonl` (disjoint ids) to form `gold73`/gold75. A third,
opt-in set of 20 formula questions inside the 363-440 tuned band is not scored
by default for that reason (`scripts/score_unbiased60.py:22-25`).

### Vietnamese scale words: `ngàn`, `nghìn`, `triệu`, `tỷ`

Vietnamese magnitude words that most tables declare their unit with, printed
inside the grid itself rather than in a column name — 24.2% of a 500-table
sample declares unit only in cells (`src/finance_qa/modules/solve/common/units.py:1-12`).
Detection and the scale-to-VND factor live in `MONEY_SCALE`
(`common/units.py:38-45`); the LLM's own `source_unit` field is only a
fallback for tables that declare nothing (`common/units.py:16-17`), because it
is unreliable when used — measured wrong in 4 of 4 inspected failures
(`common/units.py:32-34`). `ngàn` and `nghìn` are used inconsistently across
source tables (both mean "thousand"); an early regex only matched `nghìn` and
silently misread every HAG/HNG statement, which prints `Ngàn VND`, as raw VND
— a 1000x error (`common/units.py:54-58`).
