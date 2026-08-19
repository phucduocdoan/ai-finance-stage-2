# Next Agent Handoff - Raw Table Linking

Date: 2026-08-17

This is a short continuation note for the next agent. Source code remains the
source of truth. Also read `CONTEXT.md`, `docs/HANDOFF.md`, and
`docs/DECISIONS.md` before making changes.

## Current Goal

Improve answer accuracy for Type 2-5 finance questions without adding
question-specific rules.

The current direction is:

```text
understand -> retrieve -> specialized validated solver when fit -> codegen fallback
```

For detail-table arithmetic, the preferred specialized solver is
`raw_table_linker`, not a full rewrite of all tables into `long_format`.

## Important User Preferences

- Keep it simple first.
- General solution first; do not fix by question id or one-off semantic branches.
- Do not hardcode answer expressions or metric routing inside broad logic files.
- Use Pydantic/structured schemas for model output.
- LLM can understand semantic wording, but Python must validate and execute.
- Do not use LLM self-confidence as a control-flow gate.
- Do not claim score improvements until measured.
- Prefix shell commands with `rtk`.

## Current State

Relevant files:

- `src/finance_qa/modules/solve/table_linking/schema.py`
- `src/finance_qa/modules/solve/table_linking/columns.py`
- `src/finance_qa/modules/solve/table_linking/__init__.py`
- `src/finance_qa/modules/solve/raw_table_linker.py`
- `tests/test_raw_table_linker.py`
- `tests/test_table_linking_schema.py`
- `tests/test_table_linking_columns.py`
- `src/finance_qa/agents/finance/config.py`
- `src/finance_qa/agents/finance/graph.py`
- `CONTEXT.md`
- `docs/HANDOFF.md`
- `docs/DECISIONS.md`

`raw_table_linker.py` is currently an opt-in branch:

```bash
SOLVE_RAW_TABLE_LINKER=1
SOLVE_RAW_TABLE_LINKER_PLANNER=1
```

Typical probe config used so far:

```bash
SOLVE_CELL_LOCATOR=1
SOLVE_FORMULA_FACTS=1
SOLVE_RAW_TABLE_LINKER=1
SOLVE_RAW_TABLE_LINKER_PLANNER=1
SOLVE_TABLE_PROFILES=0
```

Thinking flags should remain off. The current vLLM backend was observed to
return empty output with `enable_thinking=True`, and `plan.confidence` is not a
reliable gate anyway.

## What Was Changed Recently

In `raw_table_linker.py`:

- Extracted shared typed linking primitives into
  `src/finance_qa/modules/solve/table_linking/schema.py`; raw linker still
  re-exports the old names to preserve API compatibility.
- Added `RawCellRef` and `RawGroupCandidate` as the next general primitive for
  deterministic expressions over real physical cells, e.g. bounded group sums.
- Added `src/finance_qa/modules/solve/table_linking/columns.py` for source-CSV
  column/header enrichment and row x semantic-column `RawGroupCandidate`
  generation.
- Added experimental flag `SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1`. It defaults
  off because the q955 group-candidate prompt still failed closed and increased
  latency; keep using it only for targeted probes until the ratio selection
  surface is smaller.
- Removed `plan.confidence` / `decision.confidence` thresholds from control
  flow. Any remaining `plan.confidence` assignment is telemetry only.
- Added compact table context cleanup:
  `section_title`, `note_title`, `header_flat`, page OCR hint,
  `first_col_labels`, profiled row labels, and company name at the end.
- Added parsing for metadata lists stored as strings, e.g. `first_col_labels`.
- Added identity-token filtering so ticker/company names do not dominate row
  scoring after scope is already fixed.
- Added table snippets for the search planner so it can copy real row/table
  wording from in-scope tables.
- Added guarded search expansion:
  expansion is used only if a row phrase adds evidence for every required slot
  and is not too broad.
- Added `normalize_planner_decision`: if the LLM marks `supported=false` but
  supplies exactly the expected real candidate ids, Python treats the ids as the
  stronger structured signal and still validates them.
- Candidate execution is still Python-owned: selected ids must exist, match slot
  order, pass score/scope/unit checks, and then Python builds the pandas
  expression.

Docs were updated:

- `CONTEXT.md`: added `Raw Table Linking` and `Linking context`.
- `docs/HANDOFF.md`: added the opt-in raw-linker branch and next work.
- `docs/DECISIONS.md`: added decision 10, "Raw CSVs Stay The Authority For
  Detail Tables".

## Verified So Far

Unit/syntax checks:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
```

Both passed after the raw linker changes.

After the linking-schema extraction, these also passed:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_schema.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_columns.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
```

Live schema-refactor probe:

```text
q663 -> raw_table_linker -> 36.76031567513054
q693 -> raw_table_linker -> 31.385622109258755
q732 -> codegen after raw fail-close -> 902.4344411630631
```

Column enrichment probe on `ACB_financial_statements_2019_separate|97` now
recovers the maturity leaf headers behind `Unnamed` columns and builds:

```text
Cho vay khách hàng (i) :: lt_1y  = 144152172.0
Cho vay khách hàng (i) :: total  = 265981486.0
```

Default-off ratio-group live probe:

```text
q663 -> raw_table_linker -> 36.76031567513054
q693 -> raw_table_linker -> 31.385622109258755
q732 -> codegen after raw fail-close -> 902.4344411630631
q955 -> codegen after raw fail-close -> 0.5494801622412201
```

Live probes with raw linker planner enabled:

```text
q753 -> 571308.0
q744 -> -2880000.0
q754 -> 116644397.0
q818 -> 145.134
```

Claude's first broad gold73 measurement found the branch was not ready:
`raw_linker_on=43/73`, `raw_linker_off=44/73`. The regression cluster was
deterministic/direct raw linking.

After adding fail-closed guardrails, the branch measured:

```text
gold73_raw_linker_guardrails_on.jsonl -> 49/73
gold73_raw_linker_off.jsonl           -> 44/73
gold73_after_stt_shift_fix_live.jsonl -> 44/73
```

The detailed audit is `artifacts/audits/raw_linker_guardrails_gold73.md`.

## Current Architectural Decision

Do not build a full universal long-format layer now.

Use raw CSVs as the source of truth for detail tables. Build an incremental
table/row linking layer over existing metadata and CSVs:

- table id
- ticker
- year
- doc type
- title / note title / section title
- flattened headers
- unit
- label column
- row labels and row positions
- compact page hints
- table-profile labels

The first code boundary for that layer is now `table_linking/schema.py`. Do not
grow q955-like handling inside `raw_table_linker.py` with issuer/qid branches.
The next implementation should add enriched column profiles and group-candidate
builders under `table_linking`, then make ratio planning choose from those typed
candidates.

The compact ratio-specific surface now exists. It separates numerator options
from denominator options per slot, carries semantic role/source kind/table
context, and converts selected option IDs back to the existing ratio validator
and executor. It also has a deterministic selector for clear option surfaces
before falling back to the LLM option planner.

The q955 failure was narrowed to flat candidate ranking: direct numerator rows
like `Ngắn hạn` were pushed out by many `Cộng` rows because `wants_total`
penalized every non-total row. The scorer now exempts direct row/column text
whose component role matches the requested ratio numerator role, e.g. `lt_1y`
for `ngắn hạn`.

Targeted live probes after this change:

```text
q955 with SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1
  -> raw_table_linker / ratio_option_deterministic
  -> 54.662648234219816

default-off probe, SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS unset
q663 -> raw_table_linker -> 36.76031567513054
q693 -> raw_table_linker -> 31.385622109258755
q732 -> codegen after raw fail-close -> 902.4344411630631
q955 -> raw_table_linker -> 54.662648234219816
```

This is only a targeted probe, not a full-score result. The next gate should be
a gold73/gold94 run with the existing capability-failure report to check whether
the ratio ranking change creates any raw-linker false positives.

Gold73 was rerun after wiring deterministic option selection into the default
path for repeated maturity-ratio questions:

```text
artifacts/runs/gold73_after_ratio_option_default.jsonl -> 49/73
audit: artifacts/audits/capability_failures_gold73_after_ratio_option_default.jsonl
```

Important readout:

- `q955` is now fixed in the full run:
  `raw_table_linker / ratio_option_deterministic -> 54.662648234219816`
- q663/q693 stayed on `ratio_candidate_planner`.
- q732 still fails closed from raw and falls back to codegen.
- The total score did not robustly improve in this run because q759 and q868
  flipped wrong through codegen nondeterminism; they were not raw-linker outputs.

Treat this as a targeted q955 stability fix, not as a proven gold-score gain.
Run gold94 only after deciding whether to keep this default wiring or to measure
an on/off paired repeat.

Do not split by company as the first design axis. Company/ticker/year/doc_type
are scope filters. Company-specific adapters will likely become brittle issuer
rules.

Split by domain/table family only after measurement shows a stable family worth
normalizing, for example:

- VAS main statements
- bank note tables
- securities-company note tables
- movement/reconciliation tables

## Context Budget

The linker intentionally truncates context:

- page OCR hint in table context: about 520 chars
- candidate `table_context` rendered to planner: about 420 chars
- search snippet page hint: about 260 chars, sometimes 180 if duplicate
- table snippets per slot: limited
- labels per table: limited

These are budget controls, not semantic rules. If evidence is missing, improve
snippet selection/ranking or add a typed metadata field. Do not simply raise
global prompt length.

## Immediate Next Step

The candidate baseline config is:

```bash
SOLVE_CELL_LOCATOR=1
SOLVE_FORMULA_FACTS=1
SOLVE_RAW_TABLE_LINKER=1
SOLVE_RAW_TABLE_LINKER_PLANNER=1
SOLVE_SELECTION_FACTS=1
SOLVE_STRUCTURED_FACTS=0
SOLVE_TABLE_PROFILES=0
```

`SOLVE_SELECTION_FACTS=1` is still the candidate baseline flag because the
branch itself is stable, but the total gold73 score is not stable enough to cite
as a solved gain. Keep `SOLVE_RAW_SELECTION_LINKER=0` unless you are running a
targeted probe.

The next implementation should not be another question-specific branch. Work in
this order:

- Audit the remaining Type 2-5 misses from
  `artifacts/runs/gold73_after_selection_facts_repeat.jsonl`.
- Separate raw selection misses into single-cell selection, answer-different at
  selected slot, component/group-per-slot selection, and threshold/filter
  selection.
- Build the smallest missing typed candidate surface. The likely next surface is
  group-per-slot raw selection, reusing `RawGroupCandidate`, because q868/q974
  show that one physical cell per slot is too narrow for some note tables.
- Keep the LLM as a semantic linker over real candidate ids/search phrases.
  Python must validate coverage, table family evidence, unit compatibility,
  total-row policy, ties, arithmetic, and scaling.

Suggested command:

```bash
rtk env PYTHONPATH=src \
  SOLVE_CELL_LOCATOR=1 \
  SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 \
  SOLVE_RAW_TABLE_LINKER_PLANNER=1 \
  SOLVE_SELECTION_FACTS=1 \
  SOLVE_STRUCTURED_FACTS=0 \
  SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids "$(cat artifacts/audits/gold73_ids.txt)" \
  --out artifacts/runs/gold73_current_candidate_repeat.jsonl \
  --workers 4
```

Then score:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py \
  --run raw=artifacts/runs/gold73_current_candidate_repeat.jsonl \
  --right raw
```

Use `--measure` only if you explicitly want the repository's measure set; it is
not the honest gold73 set. Do not tune on a single question.

## Failure Buckets To Produce

For every wrong or failed Type 2-5 case, classify one primary cause:

- unsupported request shape
- missing scoped table
- missing row candidate
- search expansion did not add slot coverage
- search expansion added broad/noisy candidates
- planner chose wrong candidate among visible candidates
- Python validation rejected the planner output
- unit/scale mismatch
- fallback codegen wrote wrong pandas
- execution exception

Use these buckets to decide the next change. Good next changes are likely:

- persistent row/table linking index
- better snippet ranking
- stricter search-expansion evidence checks
- domain adapter for a measured stable table family

Avoid:

- question-id fixes
- adding Vietnamese semantic if/elif branches in solver logic
- using `plan.confidence` thresholds
- raising context limits globally
- making `long_format` pretend to cover notes/bank/entity tables

## Selection Facts Follow-up

Added `src/finance_qa/modules/solve/selection_facts.py` as a deterministic,
no-LLM selection solver over the existing `structured_facts` catalog executor.

What it does:

- runs only behind `SOLVE_SELECTION_FACTS=1`;
- sits after `raw_table_linker` and before `structured_facts` / codegen;
- supports one clear axis only: one ticker with multiple years, or multiple
  tickers with one year;
- links selector/filter/answer metrics by catalog aliases and local text
  position around max/min/threshold markers;
- handles answer-first wording such as `Y ... trong năm có X lớn nhất`;
- fails closed for multi-axis change questions, conditional aggregates, and
  non-catalog note/detail metrics.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_selection_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_structured_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_formula_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_capability_router.py
```

Targeted E2E probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 \
  SOLVE_SELECTION_FACTS=1 SOLVE_STRUCTURED_FACTS=0 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 363,553,521,555,526 \
  --out artifacts/runs/selection_facts_probe_fix_q521.jsonl \
  --workers 2
```

Observed:

- `q363`: `selection_facts -> 3.319357071984094`, correct.
- `q553`: `selection_facts -> 8.138020523057806`, correct.
- `q521`: `selection_facts` now fails closed with missing interest-expense
  fact instead of returning the cash selector value; codegen fallback remains
  wrong.
- `q526`: non-catalog EPS/other-expense selection stays with codegen.
- `q555`: deterministic plan links `net_margin > 10%` and `net_revenue`, but
  fact coverage fails for consolidated CEO 2022, so it falls back.

This is a targeted mechanism result, not a full-score claim.

Gold73 repeat after enabling `SOLVE_SELECTION_FACTS=1` and keeping
`SOLVE_STRUCTURED_FACTS=0`:

```text
artifacts/runs/gold73_after_selection_facts.jsonl -> 54/73
audit: artifacts/audits/capability_failures_gold73_after_selection_facts.jsonl
```

Compared with `gold73_after_ratio_option_default.jsonl`:

- wins: `q363`, `q521`, `q553`, `q759`, `q868`
- losses: none
- attributable `selection_facts` wins: `q363`, `q553`
- `q521`, `q759`, `q868` were codegen outputs and should be treated as
  nondeterministic fallback movement, not proof of the new solver.

Solver distribution in the repeat:

```text
cell_locator       7/7
formula_facts      6/6
raw_table_linker  14/16
selection_facts    2/2
codegen           25/42
```

Decision after this gate:

- Keep `SOLVE_SELECTION_FACTS=1` as the candidate next baseline flag.
- Do not enable `SOLVE_STRUCTURED_FACTS=1` planner as baseline.
- A repeat broad run measured lower because fallback codegen moved:

```text
artifacts/runs/gold73_after_selection_facts_repeat.jsonl -> 52/73
audit: artifacts/audits/capability_failures_gold73_after_selection_facts_repeat.jsonl
```

Repeat readout:

- `selection_facts` stayed `2/2`.
- Stable attributable wins versus the previous 49/73 baseline are `q363` and
  `q553`.
- `q521` and `q868` flipped through codegen, not through `selection_facts`;
  treat them as fallback nondeterminism.
- Do not claim the total-score improvement is robust until a paired repeat or
  gold94 gate confirms it.

## Raw Selection Linker Follow-up

Added `src/finance_qa/modules/solve/raw_selection_linker.py` as an experimental
raw-table selection solver.

What it does:

- runs only behind `SOLVE_RAW_SELECTION_LINKER=1`;
- sits after `selection_facts` and before `structured_facts` / codegen;
- handles one varying axis only: one ticker across multiple years, or multiple
  tickers in one year;
- builds bounded raw cell candidates with `raw_table_linker`;
- asks the LLM only for candidate ids in a `RawSelectionDecision`;
- lets Python validate slot order, candidate existence, score, unit kind,
  total-row policy, tie ambiguity, ranking, pandas expression, and scaling.

What it intentionally does not do yet:

- selected ticker string answers;
- threshold/filter selection;
- multi-axis selection;
- arbitrary group/component reasoning. It only supports the current bounded
  component-row sum candidate path and in-year flow/payable top-candidate path,
  and only when Python can choose one clear candidate/group per slot;
- broad total-row or nearby-table substitution when the semantic search plan
  says the target is component rows.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_selection_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_selection_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_capability_router.py
```

Targeted probes:

- `artifacts/runs/raw_selection_probe_temporal5.jsonl`: q878 and q946 were
  answered by `raw_selection_linker` correctly in an older planner-owned run,
  but do not treat those as stable wins.
- q974 now has a deterministic component-row group path:
  `artifacts/runs/raw_selection_probe_group_q974_final3.jsonl` answered 2024
  through `raw_selection_linker` with `decision_source=row_group_deterministic`.
  Exact-year scoring confirms the one-question probe as correct.
- q868 now has a deterministic in-year flow path:
  `artifacts/runs/raw_selection_probe_flow_top_868.jsonl` answered 8407.108
  through `raw_selection_linker` with `decision_source=flow_top_deterministic`
  and winning slot `VCB:2022`. The gold answer is 8406.86, so the local 1%
  money tolerance counts it correct. The branch chooses `Phát sinh trong năm`
  cells for `Thuế TNDN hiện hành`, not the one-shot planner's schema output.
- `artifacts/runs/raw_selection_probe_bridge_q974.jsonl` is unsafe even though
  the old local scorer marked it correct: the run answered 2025 while the gold
  answer field is 2024, and the old 1% relative tolerance accepted adjacent
  years. Treat this as a scorer-tolerance false positive in older artifacts.
- The scorer/audit scripts were updated after that probe: `gold_unit=năm` and
  `unit_asked=năm` now require exact numeric matching instead of 1% relative
  tolerance.
- q974 also revealed the important semantic bug: the search plan asked for
  component rows (`prefer_total_row=false`), but the selection planner chose
  `Tổng cộng` rows from a risk-credit table. The current code rejects total-row
  replay when `allow_total_row_selector=false`, builds bounded component-row
  `RawGroupCandidate`s, penalizes groups containing `exclude_phrases`, and fails
  closed before the selection planner when component-row groups are missing or
  ambiguous.
- q868 revealed a second semantic bug: search-plan reasons that merely say
  "các dòng" are not component-sum intent. The component detector now requires
  `requires_component_sum`, explicit sum/component wording, or diverse component
  phrases after filtering identity/year phrases. For in-year payable questions,
  raw-table column scoring boosts `Phát sinh trong năm` and penalizes balance
  columns, then raw selection can deterministically rank the top flow cell per
  slot.
- Latest 4-question target probe:
  `artifacts/runs/raw_selection_probe_targets_868_878_946_974.jsonl` scored
  2/4. q868 and q974 were correct through deterministic raw selection; q878 and
  q946 fell through to codegen. q878's current raw-selection failure is
  `slot mismatch: [] != ['KBC:2015', 'KBC:2017', 'KBC:2019']`, meaning the
  one-shot selection planner returned no structured slots. q946 currently fails
  raw selection with `selection tie is ambiguous`. Do not parse planner reason
  text to recover ids.
- Guard verification:
  `artifacts/runs/raw_selection_probe_guard_q974.jsonl` falls through to
  `codegen` with `raw_selection_linker: selector total row without total intent`
  before the error text was clarified to `selector total row not allowed for this plan`.
  The final codegen answer is still wrong; this only proves the experimental
  branch no longer owns that false positive.

Decision:

- Keep `SOLVE_RAW_SELECTION_LINKER=0` in the baseline.
- Use it only for targeted development until a broad repeat shows the component
  group and flow-top paths do not create a false-positive cluster.

## Known Tradeoff

`normalize_planner_decision` intentionally distrusts the LLM's `supported`
self-judgment when complete candidate ids are present. This is acceptable only
because Python still validates candidate existence, count, order, score, scope,
and unit. It does not prove semantic correctness. If broad eval shows false
positives, add an independent candidate evidence validator rather than restoring
LLM confidence thresholds.
