# Solver Hardcode And Linking Audit

Date: 2026-08-17

Scope: hardcode audit after `gold73_raw_linker_guardrails_on.jsonl`, followed
by a small raw-linker validation patch.

## Current Flow

When opt-in flags are enabled, the graph routes by executable capability:

```text
understand -> retrieve -> trace_capabilities
  -> cell_locator
  -> formula_facts
  -> raw_table_linker
  -> structured_facts
  -> selection_decompose
  -> codegen fallback
```

The route is not split by benchmark Type 1-6. Each solver owns a narrow shape
and must fail closed when evidence is weak.

## Hardcode Audit

No question-id (`qid` / `question_id`) routing was found in the solve modules.
Question IDs appear in comments, tests, audits, and scripts only.

Acceptable general mechanisms currently present:

- bounded metric catalogs and formula executors in `structured_facts.py` /
  `formula_facts.py`
- shape regexes for operation gates: selection, diff, avg, sum, ratio
- fail-closed checks for unsupported note/segment/borrowings cases
- score thresholds based on row/column/table evidence, not LLM self-confidence

Risks found:

- `raw_table_linker.normalize_planner_decision` promotes
  `supported=false` to `supported=true` when the planner supplies the expected
  number of candidate ids. This can rescue valid ids, but it can also hide a
  real semantic contradiction.
- `raw_table_linker.validate_decision` checks candidate existence/count/order,
  score, zero values, and unit-kind consistency. It does not yet reject all
  operation/target-unit contradictions. Example observed miss: target percent
  with `operation=avg` over money candidates.
- Phrase lists in `formula_facts.py` and `profile_validate.py` are acceptable
  as conservative exclusion/diagnostic guards, but should not grow into
  question-specific answer routing.

## Latest Measured State

`report_capability_failures.py` on
`artifacts/runs/gold73_raw_linker_guardrails_on.jsonl`:

```text
overall: 49/73

by solver:
  codegen            24/46
  raw_table_linker   12/14
  cell_locator        7/7
  formula_facts       6/6

by first capability attempt:
  cell_locator       29/32
  codegen             8/25
  raw_table_linker    9/12
  formula_facts       3/4
```

`report_gold_types.py` on the same run:

```text
L1: 4/4
L2: 2/2
L3: 1/2
L4: 2/2
L5: 2/2
L6: 0/2
P1: 14/17
P4: 5/9
P5: 7/18
P6: 12/15
```

Compared with `gold73_raw_linker_off.jsonl`:

- overall improved from 44/73 to 49/73
- raw linker moved 14 answers out of codegen and got 12/14 right
- zero answers dropped from 7 to 3
- execution errors dropped from 10 flagged to 7 flagged
- remaining misses are still dominated by codegen and by "gold table present
  but wrong cell/logic/value"

## Validation Follow-Up

Implemented after the audit in `raw_table_linker.py`:

- Added operation/target/source-unit compatibility validation.
  - A `ratio`/`percent` target cannot be answered by `direct`/`sum`/`avg` over
    money cells.
  - A money target cannot be answered by ratio/percent cells.
- Kept `normalize_planner_decision`, but added an independent coherence check
  for its promoted `supported=false` outputs:
  - multi-slot promoted ids must have the same row label, or
  - when the request asks for a total, every promoted candidate must be a total
    row.

This is not a question-id rule. It is a validation rule over operation, unit
kind, and row-evidence coherence.

Added tests in `tests/test_raw_table_linker.py`:

- direct percent cell can answer a percent target
- avg over money cells cannot answer a percent target
- money target cannot be answered by a percent cell
- normalized unsupported ids pass when row evidence is coherent
- normalized unsupported ids fail when row evidence is incoherent

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
```

Both passed.

Targeted probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 \
  SOLVE_TABLE_PROFILES=0 .venv_bge/bin/python scripts/run_graph.py \
  --ids 920,955,792 \
  --out artifacts/runs/raw_linker_validation_probe_920_955_792.jsonl \
  --workers 1
```

Observed:

| qid | solver after validation | answer | raw-linker reason |
|---:|---|---:|---|
| 920 | codegen | 0.0 | unsupported planner ids need coherent row evidence |
| 955 | codegen | 0.5494801622412201 | unsupported planner ids need coherent row evidence |
| 792 | codegen | 234471.0 | candidate order/scope mismatch |

So q920/q955 no longer produce raw-linker false positives, but they are still
wrong after codegen fallback. q792 falls back to the exact gold answer.

Full gold73 after validation:

```text
validation: 49/73
guardrails: 49/73
off:        44/73
```

Solver distribution after validation:

```text
codegen           24/48
raw_table_linker  11/11
cell_locator       8/8
formula_facts      6/6
```

Delta versus `gold73_raw_linker_guardrails_on.jsonl`:

- `q327`: validation-only win, fallback nondeterminism
- `q635`: guardrails-only win, fallback nondeterminism
- `q920` and `q955`: no longer raw-linker answers; both remain wrong via
  codegen fallback
- `q792`: no longer raw-linker near-miss; fallback gives exact value

## Interpretation

The base direction is sound:

- Keep LLM/codegen focused on logic.
- Let Python/table-linking own data access, candidate provenance, unit handling,
  and execution.
- Keep specialized solvers opt-in until broad repeat/full-run evidence is stable.

The linker is not yet a universal schema layer. It is currently a bounded
candidate linker for fixed-scope direct/diff/sum/avg arithmetic over raw CSV
cells. It scales by adding validated capabilities, not by adding question
specific branches.

## Recommended Next Step

Do not build a full schema graph yet.

First tighten raw-linker validation with general constraints:

1. If target unit is `ratio` or `percent`, reject `direct`, `sum`, and `avg`
   over money candidates unless the operation explicitly computes a ratio.
2. Keep `normalize_planner_decision` only if independent validators can catch
   semantic contradictions. Otherwise demote unsupported planner output and
   accept losing any rescued wins until a safer validator exists.
3. Audit remaining raw-linker misses/near-misses (`920`, `955`, `792`) by the
   same buckets: operation shape, candidate visibility, chosen row/column,
   target/source unit, and planner contradiction.
4. Then run a repeat gold73 or full 1012 on/off comparison before enabling by
   default.

Only after this should we design a persistent linking index/table schema:

- table scope: ticker, year, doc type, report family
- table context: titles, note titles, headers, page hints
- row candidates: label, normalized aliases, row type, total/component/detail
- column candidates: period/year/unit/value role
- cell facts: value, source unit, unit provenance, row/column provenance

That index should feed the same capability solvers and codegen fallback; it
should not replace raw CSVs as the submission authority.

## Ratio Component Linker Follow-up

Implemented a first bounded `ratio_from_components` capability inside
`raw_table_linker.py`.

What changed:

- `build_request` now recognizes component-ratio intent such as `tỷ trọng`,
  `tỷ số`, `trong tổng`, and `gấp ... lần`.
- Ratio uses a separate structured schema:
  `RawRatioDecision -> RawRatioSlotDecision`.
- Each slot has explicit `numerator_candidate_ids` and
  `denominator_candidate_ids`.
- Each side can contain one or more real cell candidates, so the executor can
  build expressions like `(vay ngắn hạn + vay dài hạn) / tổng tài sản`.
- Python builds the pandas expression and applies `* 100` only when target unit
  is `percent`.
- Ratio candidate building keeps otherwise-skipped period rows such as
  `Số dư cuối năm`, and synthesizes blank numeric total rows as `Cộng` for OCR
  tables that omit the label.
- Validation rejects a side that mixes a total row with its own components. This
  prevents double-counting like `Tiền mặt + Tiền gửi + Cộng`.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
```

Both passed.

Probe command:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,732,693,955 \
  --out artifacts/runs/raw_ratio_probe_663_732_693_955.jsonl --workers 1
```

Post-guard probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,693,955 \
  --out artifacts/runs/raw_ratio_probe_663_693_955_after_total_guard.jsonl --workers 1
```

Observed:

| qid | solver | answer | interpretation |
|---:|---|---:|---|
| 663 | raw_table_linker | 36.76031567513054 | numerator as `vay ngắn hạn + vay dài hạn`; denominator total assets |
| 693 | raw_table_linker | 31.385622109258755 | numerator intangible fixed assets; denominator total fixed assets |
| 732 | codegen after raw fail-close | 902.4344411630631 | raw planner double-counted denominator; validation rejected it |
| 955 | codegen after raw fail-close | 0.5494801622412201 | raw candidates do not expose a coherent per-bank short-term-loan numerator, especially ACB wide maturity layout |

Current capability:

- Good fit: single-slot ratio where numerator/denominator are direct cells, and
  simple component sums over rows.
- Partial fit: multi-slot average of ratios only when each slot has coherent
  numerator/denominator families.
- Not solved yet: maturity-bucket ratios where one side is a subset across
  multiple columns under multi-row headers, e.g. ACB in q955.

Next recommended step:

Build a small column/section-aware candidate representation before attempting
q955-like maturity-bucket questions. Do not hardcode bank names or qids. The
needed general feature is: preserve hierarchical column labels and nearby row
section context so the planner can link "ngắn hạn / dưới 1 năm" to the correct
bucket cells instead of seeing only `Unnamed: 4`, `Unnamed: 5`, etc.

## Linking Schema Boundary

Added a small `table_linking` package as the architectural boundary between
raw-table preprocessing and solver execution:

- `src/finance_qa/modules/solve/table_linking/schema.py`
- `src/finance_qa/modules/solve/table_linking/__init__.py`

The moved/shared primitives are:

- `RawScopeSlot`
- `RawLinkRequest`
- `RawCellRef`
- `RawCellCandidate`
- `RawGroupCandidate`

`raw_table_linker.py` still re-exports the current names, so graph/tests do not
need to change. This is intentionally an API-preserving extraction, not a new
solver behavior.

Why this matters:

- Cell candidates and future group candidates now live outside
  `raw_table_linker.py`.
- `RawGroupCandidate` can represent a deterministic expression over real cells,
  currently a bounded `sum`, e.g. a maturity-bucket numerator made from multiple
  physical columns.
- The next q955-like work should generate group candidates from enriched column
  profiles, then let the existing ratio executor consume them.

Verification after extraction:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_schema.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
```

All passed.

Live regression probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,693,732 \
  --out artifacts/runs/table_linking_schema_refactor_probe_663_693_732.jsonl \
  --workers 1
```

Observed:

| qid | solver | answer |
|---:|---|---:|
| 663 | raw_table_linker | 36.76031567513054 |
| 693 | raw_table_linker | 31.385622109258755 |
| 732 | codegen after raw fail-close | 902.4344411630631 |

Next concrete implementation step:

Add column-profile enrichment and group-candidate generation under
`table_linking`, then wire ratio planning to choose from cell/group candidates
instead of only flat cells. Keep validators in Python and keep codegen fallback.

## Column Profile and Group Candidate Follow-up

Implemented the first column/header enrichment primitive:

- `src/finance_qa/modules/solve/table_linking/columns.py`
- `tests/test_table_linking_columns.py`

What it does:

- Reads the source CSV alongside the normalized `load_frame()` output.
- Detects a second header row that pandas read as data.
- Handles the common one-column leaf-header shift where the first normalized
  column is a row-label column but the first raw row contains data-column leaf
  headers.
- Builds `LinkedColumnProfile` with `raw_header_stack`, `header_text`,
  `semantic_roles`, unit, and unit provenance.
- Infers general semantic roles such as `lt_1y`, `1_to_5y`, `gt_5y`, `total`,
  `current`, `prior`, and `overdue`.
- Builds `RawGroupCandidate` objects from row x semantic-column groups.

ACB/q955 validation:

For `ACB_financial_statements_2019_separate|97`, the primitive recovers:

- `Unnamed: 4` -> `Từ trên 1 tháng đến 3 tháng`, role `lt_1y`
- `Unnamed: 8` -> `Tổng cộng`, role `total`
- `Quá hạn` remains `overdue`, not `lt_1y`

It builds:

- `Cho vay khách hàng (i) :: lt_1y`
  from `Trong hạn`, `Đơn vị: Triệu VND`, `Unnamed: 4`, `Unnamed: 5`
  with value `144152172.0`
- `Cho vay khách hàng (i) :: total`
  from `Unnamed: 8` with value `265981486.0`

This proves the preprocess layer can expose the missing ACB numerator/denominator
without a company/qid rule.

Ratio group candidates were wired behind an experimental flag:

```bash
SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1
```

The flag defaults to false. Reason: when group candidates were fed to the q955
ratio planner, raw still failed closed (`ratio slot mismatch: [] != [...]`) and
latency increased to about 68-71 seconds for q955. Keeping the feature
off-by-default preserves the measured cell-only ratio behavior while keeping the
new preprocess primitive available for the next prompt/selection iteration.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_columns.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
```

Default-off live probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,693,732,955 \
  --out artifacts/runs/ratio_groups_default_off_probe_663_693_732_955.jsonl \
  --workers 1
```

Observed:

| qid | solver | answer |
|---:|---|---:|
| 663 | raw_table_linker | 36.76031567513054 |
| 693 | raw_table_linker | 31.385622109258755 |
| 732 | codegen after raw fail-close | 902.4344411630631 |
| 955 | codegen after raw fail-close | 0.5494801622412201 |

Next step:

Do not add more candidate volume to the ratio prompt. Instead, build a smaller
ratio-specific selection surface:

- separate numerator options from denominator options
- group/cell options per slot
- include only candidates whose semantic role matches the question need
- make the planner fill a compact schema over `slot_key -> numerator_id /
  denominator_id`

That should use the group primitive above but avoid the broad mixed candidate
prompt that caused q955 to return an empty slot list.

## Ratio Option Surface Follow-up

Implemented the compact ratio option surface on top of the typed linker:

- `RawRatioOption`, `RawRatioOptionDecision`, and slot decisions live in
  `raw_table_linker.py`.
- `build_ratio_options()` partitions mixed cell/group candidates by
  `slot_key x side`, where side is `numerator` or `denominator`.
- Options include `source_kind`, table ids, semantic role, value, unit, score,
  and short context so a planner can choose IDs instead of reading a flat mixed
  candidate list.
- `ratio_decision_from_options()` converts selected option IDs back into the
  existing `RawRatioDecision`, so validation/execution stay unchanged.
- A deterministic option selector now handles clear surfaces before the LLM:
  top numerator must match the requested semantic role, top denominator must be
  `total`, roles must be consistent across slots, and units must have one kind.
  If that is not true, the code falls back to the option LLM planner.

The candidate scorer also changed for ratio questions: when the question asks
for a numerator role such as `lt_1y`, direct row-label cells with that role no
longer receive the `wants_total` non-total penalty. This is a general fix for
the flat-ranking failure where many `Cộng` denominator rows pushed true
numerators like `Ngắn hạn` out of the retained pool.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_schema.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_table_linking_columns.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
```

New q955 option-surface regression coverage:

- ACB direct row `Ngắn hạn :: 31.12.2019Triệu VND` is preferred over the wide
  group fallback.
- The wide fallback `Cho vay khách hàng (i) :: lt_1y` remains available.
- MBB/BID/STB numerator options are the direct `Nợ ngắn hạn` rows.
- STB denominator prefers the `CHO VAY KHÁCH HÀNG` total table.
- The deterministic selector converts the surface to an executable 4-slot
  average-ratio query.

Live probes:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 \
  SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 955 \
  --out artifacts/runs/raw_ratio_option_direct_row_probe_q955.jsonl \
  --workers 1
```

| qid | solver | decision_source | answer |
|---:|---|---|---:|
| 955 | raw_table_linker | ratio_option_deterministic | 54.662648234219816 |

Default-off probe after the scorer/option work:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,693,732,955 \
  --out artifacts/runs/ratio_default_off_after_option_surface_probe_663_693_732_955.jsonl \
  --workers 1
```

| qid | solver | answer |
|---:|---|---:|
| 663 | raw_table_linker | 36.76031567513054 |
| 693 | raw_table_linker | 31.385622109258755 |
| 732 | codegen after raw fail-close | 902.4344411630631 |
| 955 | raw_table_linker | 54.662648234219816 |

This is not a full-score claim. The measured change is targeted: q955 now
answers via raw linking, q663/q693 stayed stable, and q732 did not become a raw
false positive in the 4-id probe. The next gate should be a gold73/gold94 run
with capability-failure bucketing before enabling any new default beyond the
current opt-in flags.

## Gold73 After Default Option Surface

After the first gold73 gate, q955 still fell back to codegen in the full run
because the flat ratio LLM planner returned `slots=[]`. The option surface was
therefore wired into the default ratio path only for repeated maturity-ratio
questions:

- `ratio_aggregate == "avg"`
- the question asks a concrete maturity numerator role such as `lt_1y`
- deterministic option selection must pass; otherwise the old flat ratio
  candidate planner remains the fallback

This keeps multi-component ratios such as q663 on the existing flat planner.

Targeted default-off probe after that wiring:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 663,693,732,955 \
  --out artifacts/runs/ratio_default_option_surface_probe_663_693_732_955.jsonl \
  --workers 1
```

| qid | solver | decision_source | answer |
|---:|---|---|---:|
| 663 | raw_table_linker | ratio_candidate_planner | 36.76031567513054 |
| 693 | raw_table_linker | ratio_candidate_planner | 31.385622109258755 |
| 732 | codegen after raw fail-close | n/a | 902.4344411630631 |
| 955 | raw_table_linker | ratio_option_deterministic | 54.662648234219816 |

Gold73 gate:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids "$(cat artifacts/audits/gold73_ids.txt)" \
  --out artifacts/runs/gold73_after_ratio_option_default.jsonl \
  --workers 4

rtk env PYTHONPATH=src .venv_bge/bin/python scripts/report_capability_failures.py \
  artifacts/runs/gold73_after_ratio_option_default.jsonl \
  --json-out artifacts/audits/capability_failures_gold73_after_ratio_option_default.jsonl
```

Result: `49/73`.

Compared with the immediately previous `gold73_after_ratio_option_surface.jsonl`
run:

- win: `q955` (`codegen` wrong -> `raw_table_linker` correct)
- losses: `q759`, `q868`, both `codegen` answers; not raw-linker answers

So the q955 fix is real, but there is no robust total-score improvement claim
from this single gold73 run. The raw linker remains `14/16` correct on the gold
items it answered; misses are still `q355` and `q685`.

## Deterministic Selection Facts Follow-up

After auditing the Type 2-5-like misses in
`gold73_after_ratio_option_default.jsonl`, the main remaining pattern was not
raw OCR noise. The dominant wrong set was selection logic falling to codegen:

- temporal/cross-company questions such as `năm/công ty có X cao nhất, trả lời Y`;
- conditional questions such as `các năm có ratio > threshold, chọn Y thấp nhất`;
- many note/detail metrics still outside the main-statement fact catalog.

An opt-in deterministic branch was added:

- `src/finance_qa/modules/solve/selection_facts.py`
- config flag: `SOLVE_SELECTION_FACTS=1`
- graph position: after `raw_table_linker`, before `structured_facts` and
  codegen

This branch deliberately does **not** use the older `structured_facts` LLM
planner. A probe with `SOLVE_STRUCTURED_FACTS=1` showed that the planner could
produce false positives by choosing wrong metrics:

- `q526`: chose total assets for an EPS/other-expense question;
- `q542`: chose a gross-margin argmax instead of the requested multi-year
  change/filter computation;
- `q759`: chose current assets for a receivables note diff;
- `q878`: chose pretax margin for an investment-property note question.

The new branch is narrower and general:

- one clear axis only: one ticker/many years or many tickers/one year;
- selector/filter/answer metrics must be anchored by catalog aliases in the
  question text;
- filter thresholds such as ratio `> 10%` are converted into ratio scale;
- answer-first wording is handled (`Y ... trong năm có X lớn nhất`);
- non-catalog note/detail metrics and multi-axis change questions fail closed.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_selection_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_structured_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_formula_facts.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_capability_router.py
```

Targeted E2E result:

```text
artifacts/runs/selection_facts_probe_fix_q521.jsonl
q363 -> selection_facts -> 3.319357071984094, correct
q553 -> selection_facts -> 8.138020523057806, correct
q521 -> selection_facts fail-closed on missing interest-expense fact, codegen wrong
q526 -> no catalog metric anchored, codegen
q555 -> linked plan, but consolidated CEO 2022 fact missing, codegen wrong
```

Interpretation:

- This is a targeted mechanism win, not a total-score claim.
- It confirms a useful baseline direction for Type 4/5 selection questions:
  build a small clean fact matrix and let Python select/filter/rank.
- Remaining misses split into two next buckets:
  fact catalog missing note/detail metrics, and raw-linker support for fixed-scope
  detail arithmetic such as borrowings/receivables/investment-associate sums.

Gold73 repeat with:

```bash
SOLVE_CELL_LOCATOR=1
SOLVE_FORMULA_FACTS=1
SOLVE_RAW_TABLE_LINKER=1
SOLVE_RAW_TABLE_LINKER_PLANNER=1
SOLVE_SELECTION_FACTS=1
SOLVE_STRUCTURED_FACTS=0
SOLVE_TABLE_PROFILES=0
```

Result:

```text
artifacts/runs/gold73_after_selection_facts.jsonl -> 54/73
```

Capability report:

```text
cell_locator       7/7
formula_facts      6/6
raw_table_linker  14/16
selection_facts    2/2
codegen           25/42
```

Delta versus `gold73_after_ratio_option_default.jsonl`:

- wins: `q363`, `q521`, `q553`, `q759`, `q868`
- losses: none
- direct `selection_facts` wins: `q363`, `q553`
- codegen-only wins likely from fallback nondeterminism: `q521`, `q759`, `q868`

Readout:

`selection_facts` is now a plausible candidate baseline flag because it produced
two deterministic selection wins and no measured false positives in this repeat.
The total-score jump to `54/73` should still be described as one run, not a
settled score, because three of the five wins came from codegen fallback churn.
