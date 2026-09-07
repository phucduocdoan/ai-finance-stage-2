# Handoff - ViFinQA Stage 2

This is the current operating map for the repo. Source code is the source of truth when
any note here disagrees — in particular, docstrings in `agents/finance/graph.py` and
`modules/solve/*.py` carry the measured numbers behind each design choice and are more
detailed than this file.

## Active Architecture

The graph is the only answer flow, for both interactive (`run_question`) and batch
(`scripts/pipeline/run_graph.py`) use. The default path is still the grounded pandas-codegen path:

```text
understand -> retrieve -> generate_pandas -> execute_and_repair -> verify_answer
```

- **understand** (`agents/finance/understand.py`): resolves tickers rule-based from BTC's
  `code_stock.csv` (authoritative — the LLM hallucinates codes otherwise), applies a
  regex backstop that promotes `doc_type` to `separate` when the question states that scope
  outright and the LLM returned `unknown`, then asks the LLM for a Pydantic `UnderstandIntent`
  (metric/operation/years/answer shape/unit hint).
- **retrieve** (`modules/rag/service.py` -> `modules/rag/candidates.py`): hard-filters by
  ticker/year/doc_type, BM25 + dense candidates combined by RRF, primary-statement expansion,
  optional reranker, LLM judge picks the final table ids. Falls back to a frozen cache
  (`artifacts/runs/full_1012.jsonl`) if tickers/years are missing or retrieval errors.
- **generate_pandas** (`modules/solve/codegen.py`): one LLM call shown the *contents* (not
  schema) of the head of retrieval's ranking (`codegen_max_tables=3` tables), writes one pandas
  expression.
- **execute_and_repair** (`modules/solve/execute.py`): runs the query, repairs on exception (up
  to `max_repairs=2` times), then applies deterministic unit conversion
  (`modules/solve/units.py`) — repair first, scale last, because scaling cannot fail and
  shouldn't be what the repair prompt is about.
- **verify_answer** (`modules/solve/verify.py`): a second LLM look at what cell the query
  *actually* read (not what the model claims it read); rewrites once if wrong, keeps the
  rewrite only if it executes and changes the answer. Toggle: `SOLVE_VERIFY_ANSWER=0`.

There is one opt-in structured branch, off by default:

```text
understand -> retrieve -> solve_structured_facts -> verify_answer
                                      \-> solve_selection/generate_pandas on fallback
```

- **solve_structured_facts** (`modules/solve/structured_facts.py`): prototype deterministic
  solver over `data/derived/long_format.parquet`. The LLM emits a bounded Pydantic
  `StructuredPlan`; it does not write SQL, pandas, or arithmetic code. DuckDB is only the fact
  access layer, and Python owns all formulae and unit conversion. Toggle:
  `SOLVE_STRUCTURED_FACTS=1`.
- The current branch is deliberately narrow: v1 only accepts selection questions over years or
  tickers where the selector and answer metrics are in the main-statement catalog. Unsupported
  or failed plans fall back to the default path.
- Measured on the 94-question low-confidence gold gate:
  `structured_v1=44/94`, `tools=43/94`, `base1=42/94`, `base2=42/94`. The branch answered 13
  questions through structured facts, with 4 structured-only wins (`q363`, `q371`, `q387`,
  `q390`) and 2 baseline-only losses caused by normal codegen nondeterminism in the fallback
  path. Keep it off by default until the plan schema and coverage validator improve the 9
  structured misses.

Do not expand this branch by regexing question text into special cases. The intended next step
is a richer typed semantic plan (`selection`, `filters`, `answer`, `year_offset`, `expression`)
plus deterministic validation. Regex is acceptable for cheap canonicalization such as ticker
resolution, explicit report scope, and metric aliases; it should not be the solve semantics.

There is also a narrow deterministic catalog-selection branch:

```text
understand -> retrieve -> solve_selection_facts -> execute
                                      \-> generate_pandas on fallback
```

- **solve_selection_facts** (`modules/solve/selection_facts.py`): uses the existing
  main-statement metric catalog and deterministic formula executor for max/min/threshold
  selection over one clear axis. It is not an LLM planner and does not handle note/detail-table
  metrics. Toggle: `SOLVE_SELECTION_FACTS=1`.
- Targeted wins are stable for catalog-backed selection (`q363`, `q553`). The first gold73 run
  measured `54/73`, but a repeat measured `52/73` because fallback codegen moved; do not cite
  the total score as robust. The branch itself was `2/2` in both runs, so it remains the
  candidate baseline flag with `SOLVE_STRUCTURED_FACTS=0`.

There is a second opt-in branch for raw-table cell linking, also off by default:

```text
understand -> retrieve -> solve_raw_table_linker -> execute
                                      \-> generate_pandas on fallback
```

- **solve_raw_table_linker** (`modules/solve/raw_table_linker.py`): covers fixed-scope direct,
  diff, sum, average, and ratio questions when the answer cells live in raw CSV tables rather
  than `long_format`. It builds real cell candidates from scoped tables, optionally asks an LLM
  to map question wording to candidate ids, then Python validates slot order, scope, ambiguity,
  unit compatibility, and builds the pandas expression. Toggles:
  `SOLVE_RAW_TABLE_LINKER=1`, `SOLVE_RAW_TABLE_LINKER_PLANNER=1`.
- The planner's self-confidence is not a control-flow gate. It is telemetry only. Gates are
  mechanical: row-phrase coverage before/after search expansion, bounded matches per slot,
  candidate ids that exist, expected candidate count/order, candidate score, scope, and unit kind.
- The linker uses compact linking context, not whole reports: section/note title, flattened
  headers, page OCR hint, first-column labels, table-profile row labels, row/column/unit/value
  for candidates. Candidate context is capped before prompt rendering, and table snippets are
  limited per slot. If a prompt misses evidence, improve snippet selection or metadata extraction
  before raising global character limits.
- First broad gold73 measurement was negative (`raw_linker_on=43/73`, same-session
  `raw_linker_off=44/73`) because deterministic/direct linking caused regressions. After
  fail-closed guardrails for low-evidence direct cells, zero cells, single-slot sums, and
  direct-ratio requests, the opt-in branch measured `49/73` on the same gold73 set
  (`artifacts/runs/gold73_raw_linker_guardrails_on.jsonl`) versus `44/73` control. Keep the
  branch opt-in until a repeat broad run or full 1,012-question run checks live nondeterminism
  and non-gold regressions.
- **solve_raw_selection_linker** (`modules/solve/raw_selection_linker.py`): experimental
  opt-in branch for temporal/cross-company raw-table max/min selection. It asks the LLM only to
  choose bounded candidate ids; Python validates slot coverage, units, total-row policy, ties,
  and the final ranking. Toggle: `SOLVE_RAW_SELECTION_LINKER=1`. (Superseded 2026-08-22: the
  default is now `True`, matching what both submitted runs used — `config.py:186`.) The advice
  that follows was written when the default was off:
  current deterministic targeted wins are `q868` and `q974`; older planner-owned wins on `q878`
  and `q946` are not stable. The branch now models component-row group sums per slot and in-year
  flow/payable top-candidate selection. It only accepts these paths when Python can choose one
  deterministic candidate/group for every slot. If component groups are required but ambiguous, it
  fails closed instead of letting the one-shot planner substitute a broad total or nearby table
  family.

For future work, treat raw CSVs as the source of truth for detail tables. Do not scale by forcing
all notes and bank/entity layouts into `long_format`. Add fact layers or domain adapters only for
measured, stable table families; otherwise prefer bounded raw-table linking with deterministic
validation and codegen fallback.

The module boundary:

| Path | Responsibility |
|---|---|
| `src/finance_qa/core/` | LLM connection, async HTTP/event-loop helpers, paths, shared config/types |
| `src/finance_qa/modules/data/` | table store, metadata, preprocessing (OCR extraction, enrichment, classification) |
| `src/finance_qa/modules/rag/` | candidate retrieval, indexes, retrievers, rerankers, judge, RAG service |
| `src/finance_qa/modules/solve/` | grounded pandas codegen, execution/repair, unit detection, verify |
| `src/finance_qa/modules/tools/` | DataFrame helpers, numeric normalization, Python execution |
| `src/finance_qa/pipelines/` | submission item shape (`submission.py`), data-rebuild orchestration (`data_pipeline.py`) |
| `src/finance_qa/agents/` | agent base class, finance state/config/understand/graph topology, public entrypoints |
| `src/finance_qa/evaluation/` | reusable retrieval evaluation helpers |

## Public Entrypoints

```python
from finance_qa.agents.finance import FinanceAgent, FinanceAgentConfig, run_question
from finance_qa.agents.finance.graph import arun_question, build_graph, get_graph
from finance_qa.pipelines.submission import submission_item
from finance_qa.modules.data.service import load_tables
from finance_qa.modules.rag.service import retrieve_table_ids
from finance_qa.modules.solve import agenerate, aexecute
```

Removed import paths are listed in `docs/DECISIONS.md` section 2 — do not re-add compatibility
shims for them.

## Data Snapshot And Pipeline

Current snapshot: 1,973 OCR report files, 146,246 extracted tables, 1,012 enriched questions.

`tables_metadata_v2.jsonl`, `tables_doc_text.parquet`, and `tables_dense.npy` are protected
artifacts (see `docs/DECISIONS.md` section 8) — the bge-m3 dense index in particular cannot be
rebuilt today because the v1 metadata file it was built from no longer exists on disk.

| Stage | Service owner | CLI wrapper |
|---|---|---|
| OCR TXT/HTML -> raw CSVs | `modules.data.preprocessing.extract_tables.TableExtractor` | `scripts/data_build/extract_tables.py` |
| raw questions -> enriched metadata | `modules.data.preprocessing.questions.QuestionEnricher` | `scripts/data_build/enrich_questions.py` |
| metadata -> retrieval text parquet | `modules.data.preprocessing.document_text.DocumentTextBuilder` | `scripts/data_build/build_doc_text.py` |
| table metadata/CSV -> long format | `modules.data.preprocessing.long_format.LongFormatBuilder` | `scripts/data_build/build_long_format.py` |
| retrieval text -> local dense index | `modules.rag.indexing.dense.DenseIndexBuilder` | `scripts/data_build/build_dense_index.py` |
| retrieval text -> hosted dense index (paid) | `modules.rag.indexing.deepinfra_build.DeepInfraIndexBuilder` | `scripts/data_build/build_deepinfra_index.py` |
| `statement_type=="unknown"` rows -> reclassification patch | `modules.data.preprocessing.offline.statement_type_classifier.StatementTypeClassifier` | `scripts/data_build/classify_statement_type.py` |

`src/finance_qa/pipelines/data_pipeline.py` (+ `scripts/pipeline/build_data_pipeline.py`) chains the
required rebuild order (`enrich_questions -> build_doc_text -> build_dense_index`); the other
stages are explicit, off-by-default flags on that same CLI.

### Long Format Coverage

`data/derived/long_format.parquet` is a main-statement fact table, not a corpus-wide normalized
database. It is built by `modules.data.preprocessing.long_format.LongFormatBuilder` from
`tables_metadata_v2.jsonl` by:

```text
statement_type in {balance_sheet, income_statement, cash_flow}
AND has_ma_so_column
AND row ma_so is numeric with 2-4 digits
AND cell value parses as numeric
```

Current coverage:

```text
metadata tables:            146,246
BS/IS/CF tables:             14,278
BS/IS/CF with ma_so:          8,898
long_format table_ids:        8,218
long_format rows:           290,230
reports:                      1,465
tickers:                         75
years:                    2015-2025
```

This is the right substrate for deterministic answers over VAS main-statement metrics:
`net_revenue`, `cogs`, `gross_profit`, `interest_expense`, `profit_before_tax`, `net_profit`,
`cfo`, `current_assets`, `inventory`, `total_assets`, `liabilities`, `current_liabilities`,
`equity`, and derived formulae such as D/E, current ratio, quick ratio, gross/net margin,
ROA/ROE, interest coverage, and CFO ratios. It is not expected to cover notes, entity tables,
equity-change tables, bank/CTCK-specific note layouts, or metrics with no stable `ma_so`
mapping.

The product rule is: if a structured plan's primitive dependencies are covered, execute it
deterministically; if coverage is missing or the metric is outside the catalog, fall back to raw
table codegen. Do not make `long_format` pretend to be complete.

## Verification

These avoid LLM calls:

```bash
PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
PYTHONPATH=src .venv_bge/bin/python tests/test_query_execution.py
PYTHONPATH=src .venv_bge/bin/python tests/test_candidate_pool.py
PYTHONPATH=src .venv_bge/bin/python tests/test_solve_units.py
PYTHONPATH=src .venv_bge/bin/python tests/test_understand.py
```

Graph smoke (one live LLM call chain):

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/run_graph.py --ids 371 --out artifacts/runs/smoke_q371.jsonl
```

## Current Benchmark State

The honest gold set is `data/eval/unbiased60_gold.jsonl` + `data/eval/manual15_gold.jsonl` (73
questions with confidence >= medium, disjoint from the 363-440 band the old architecture was
tuned against). Score any run or packaged submission against it with:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/eval/score_unbiased60.py --run solve=<run.jsonl> --right solve
```

Current number: **38/73 (52.1%)** at 1% relative tolerance, from
`artifacts/runs/full1012_qwen35.jsonl` — a full 1,012-question run of the on-disk graph, scored
post-migration and on the current vLLM backend. Legacy submission artifacts score 29-30/73
(~40%) on the same set. This reproduces the 37/73 recorded before the migration, so the
deletion/migration and the server's model swap (see "The Model Behind The Numbers" below) both
left the score intact.

The local score scripts use 1% relative tolerance for numeric money/ratio answers, but exact
matching for gold rows whose answer unit is `năm`. This avoids false positives such as a 2025
prediction being counted correct against gold 2024.

Where the 35 misses go (measured on that run; 60 of the 73 gold rows carry an
`evidence_table_id`, which is what makes this attributable):

| Bucket | Count | Node at fault |
|---|---:|---|
| all gold tables shown to codegen, wrong cell read | 12 | `generate_pandas` |
| gold tables in the pool, some cut by `codegen_max_tables=3` | 7 | evidence budget |
| pool holds some gold tables, misses the others | 6 | `retrieve` |
| no gold table reached the pool at all | 5 | `retrieve` |
| wrong, gold row carries no table label | 6 | unattributable |

Table-level recall into `table_ids` is **83/97 (85.6%)**, so retrieval is not the binding
constraint. Cell reading is the largest bucket; the flat `codegen_max_tables=3` cut is second.

**Read `evidence_table_id` as a list, not a string.** 22 of the 60 labelled rows name 2-5 tables
separated by `;`, three carry parenthetical annotations (`|6 (BS) & |33 (note)`), and one uses a
bare `|33` that inherits the preceding report id. Comparing the raw field against `table_ids` as
one atomic token silently fails on every one of those rows, and an earlier version of this table
did exactly that: it blamed `retrieve` for 18 misses and cell reading for 10, roughly the reverse
of the truth. Split on `[;&]`, strip parentheticals, match per token — that parses all 97 gold
tables with nothing left over.

A per-stage trace of the tables that never reached `table_ids` (hard filter -> BM25 -> dense ->
RRF+primary expansion -> reranker -> judge window -> judge) puts the residue on the judge
declining candidates it was shown at rank 1-2, not on recall: 2 tables die in the hard filter
(one is the known BIDV alias gap), 2 are never retrieved by either channel, and 7 are ranked
inside the judge's top-20 window and not picked. Two of those judge misses were not reproducible
run-to-run at `judge_thinking=False`, so treat the judge bucket as a range.

### The Model Behind The Numbers

The vLLM server on 8990 serves `Qwen/Qwen3.5-9B` and *also* answers to the old alias
`Qwen/Qwen3-8B-Instruct`, which is `core/llm.py`'s default `MODEL`. The swap is therefore
silent — nothing errors, the requests just reach a different model. Every `*_thinking` flag in
`agents/finance/config.py` is `False` because this model returns an empty reply with
`enable_thinking=True` at every token budget tried; leave them off unless you have re-measured
against the server you are actually pointed at.

### Failure Detectors That Need No Gold Labels

Three signals let you count errors across all 1,012 questions without hand labelling:

| Signal | Coverage | Reliability |
|---|---|---|
| `item.answer == 0.0` or `None` | 98/1012 (9.7%) | 0 correct on gold — a certain failure |
| `diag.units.failed` | subset of the above | adds nothing on its own |
| `diag.verify.correct == false` | 560/938 (60%) | agrees with ground truth 62/71 (87%) on gold |

By question shape (from `questions_enriched.jsonl` `multi_year`/`multi_company`), the certain-
failure rate is 7.7% for single-cell, 9.6% temporal, 8.0% cross-company, and **24.7% for
multi-year × multi-company** — the bucket `codegen_max_tables=3` structurally cannot serve.

### Post-Processing Levers That Are Closed

Measured 2026-09-01 against the private leaderboard. Every one of these rearranges the 1,012
answers already on disk rather than producing new ones, and none of them moves the score. Read
this before spending another submission on post-processing.

The private round scores the same submitted file on a different split. `v28` (v17 answers plus
`fill_from_arms`, `rescale_below_floor`, `repair_fact_queries`, `repair_cell_indices`) returned
metrics identical to v17 in every digit:

```
TABLES_F2MACRO 0.0003  DOCS_F2MACRO 0.9494  ANSWER_ACCURACY 0.3893  EXECUTION_ACCURACY 0.3874
```

| lever | result | why it is closed |
|---|---|---|
| `relevant_tables` format | `TABLES_F2MACRO` 0.0003 | 12 probes spent, see `docs/tables_metric_probes.md` |
| `fill_from_arms` on v17 | 3 of 1,012 cells changed | v17 already carries the rescale, so only the `== 0.0` criterion still fires; 2 of the 3 swapped one wrong answer for another |
| majority vote across runs | 51/73 vs 50/73 on gold | 5 same-day runs changed 61 answers, 10 runs across all eras changed 257; both land inside the ±4-question noise band of a 73-question set |
| `repair_cell_indices` | 72 -> 22 constant queries, score unchanged | `EXECUTION_ACCURACY` runs the query and compares to `answer`, and a constant executes and matches. The pass buys rule compliance under manual review, not metric. |

The voting probe used `rescale_below_floor` on each donor first so the clusters compare like with
like, grouped by `rel_tol=1e-4`, required a majority of at least 2, and broke ties toward the
earlier run in the priority list. It is not committed as a script because it did not clear its
bar.

The bar for spending another submission, registered before the next attempt: a candidate must beat
the standing submission by at least 4 questions on the 73-question honest gold set. One sigma on
that set is about 4 questions, so anything smaller cannot be distinguished from run-to-run
batching noise.

What is left is `ANSWER_ACCURACY`, and it needs new runs rather than new post-processing. The
obstacle is in "What the submitted answers came from" in the README: a fresh run of the current
code lands near 0.37 against the recorded 2026-08-24 run's 0.40, so a fresh run submitted without
clearing the bar above is more likely to lose three points than gain any.

### One Lever That Is Open, And Why The Bar Cannot Judge It

`scripts/pipeline/recount_saturated.py` (step 8) is built, measured, and packaged as
`output/submission_v30_countfix.zip`, but **not submitted**. Against v27 it changes 4 answers of
1,012 -- q435 `1.0`->`3.0`, q563 `0.0`->`1.0`, q932 `0.0`->`1.0`, q983 `0.0`->`2.0` -- rewrites 7
more queries without moving their answers, and leaves the other 1,001 records byte-identical. No
field other than `answer` and `pandas_query` is touched, `build_submission` emits the same 9
literal fallbacks as v27, and re-executing all 1,012 queries against the staged CSVs gives 1,005
consistent / 0 mismatched / 7 non-executing on both versions, the same 7 ids. So it is
non-negative by measurement rather than by argument.

The bar above cannot judge it: none of the 11 changed ids appears in any of the 94 gold questions.
That is not a reason to treat the bar as met. It is a reason to note that the bar was registered
against run-to-run batching noise, and this candidate has none -- it is a deterministic edit of 11
records, not a new run. The upside is bounded at 4 questions (+0.40pp, 0.3874 -> 0.3914) and the
floor is the standing score. q563 and q983 have as many conditions as the question has entities,
so their new values are structurally complete; q435 names 7 entities against 6 conditions and q932
names 4 banks against 3, so those two may still undercount.

Reproduction: `v27_cells.jsonl` -> step 8 -> step 10. `v27_cells.jsonl` -> step 10 alone reproduces
the submitted v27 `submission.json` byte for byte, so the delta has exactly one cause.

### 57 Of 1,012 Submitted Queries Are In The Shape The Rules Score As Zero

Found while dissecting the gold failures, and present identically in v27 and v30, so it predates
both and neither patch causes it. A structural scan of the packaged `submission.json` (literal-zero
multiplication anywhere in the AST; no `ast.Subscript` anywhere in the AST) returns:

- **33 queries multiply a real cell read by literal `0` and add a year.** All 33 are "năm nào"
  questions. Example: `(df3.iloc[13]['Đơn vị tính: VND']) * 0 + 2019`. The answer is a constant;
  the cell read is decorative. No "is this query a constant?" test can see it, because it does
  reference a dataframe.
- **24 queries read no cell at all.** q221 is `10.6`; q823 is `round(float(4915.48), 2)`, for a
  counting question.

The `* 0` shape comes from this repo, not from the model: `raw_selection_linker.py:813` and
`project_year` in `codegen/execute.py:432`. `project_year`'s own docstring states the intent --
keep the year inside the query so re-execution reproduces the answer -- which is right, but the
annihilation makes the result a stored constant instead.

`scripts/pipeline/deliteralize_years.py` (step 9) closes 22 of the 33. `diag.raw_selection_linker.chosen`
still holds every candidate year's cell, so the comparison the solver performed and discarded is
rebuildable as `max([(float(<cell 2016>), 2016), ...])[1]`. Measured against v30: 22 queries
rewritten, **0 answers changed**, evidence extended on those 22 and `relevant_tables` unchanged on
all 1,012 (the candidate tables were already listed; only evidence had been narrowed to the
winner), same 9 literal fallbacks, and re-executing all 1,012 queries against the staged CSVs
gives 1,012 consistent / 0 mismatched / 0 non-executing on both v30 and v31. Packaged as
`output/submission_v31_years.zip`, **not submitted**. Exposure drops 57 -> 35.

The 11 it cannot close: 9 came through codegen, which records no branches for its own `max`, and
q890/q946 have diag coordinates that predate the header merge (`Tại ngày 31 tháng 12 năm` against a
shipped column `Tại ngày 31 tháng 12 năm | 2017 VND`), so the rebuilt query raises `KeyError` and
the gate skips it. The 24 pure constants need grounding, not a rewrite.

One lead left unexploited on purpose: q946 is the single gold question in this set and is wrong
(ours 2018, gold 2022). A genuine argmax over its three candidate cells might well land on 2022,
but the gate that makes step 9 riskless is "reproduce the recorded answer exactly", and taking
that gate off to chase one question turns a guaranteed no-loss edit into a bet.

### The Solvers Now Emit That Comparison, So The Repair Pass Has No Work Left On A Fresh Run

Step 9 had no pipeline counterpart: a fresh run still emitted 33 annihilated years and the repair
only ran afterwards. Both emit sites now build the comparison themselves, gated the same way --
execute the rebuilt query, keep the old shape unless it lands on the year the solver picked.

Replaying the 33 affected ids through `run_graph.py --ids` (`/tmp/years33b.jsonl`, verified with
`scripts/dev/check_years33.py`, untracked because `.gitignore` skips `scripts/dev/`):

- 31 of 33 emit the comparison natively. The 2 left, q832 and q929, are codegen declining to
  resolve a branch's year, and step 9 cannot rebuild them either, so running it afterwards
  reports `{'dạng nhân 0': 2, 'không dựng lại được': 2}` and changes nothing.
- 33 of 33 execute on the frames the package would ship.

What that replay **cannot** show is whether accuracy held. Gold covers 0 of these 33 ids, so
`run_graph` printed `?` for every expected value, and comparing against v31 conflates the change
with run-to-run variance: 13 answers differ, and 7 of those changed solver, every one of them
because the LLM-driven raw selection planner refused where it had not before (`ambiguous row
groups`, `rank_op mismatch`, `empty slots after retry` -- all three predate this change and all
three fire at slot resolution, before any query is emitted). v31 itself ran with `retrieve:
CUDA out of memory -> frozen fallback` on 13 of the 33. Three questions (q501, q860, q884) now
answer an amount rather than a year, which is codegen's pre-existing give-up path on a question
whose year it cannot place in the asked set, reached because routing moved.

So the claim this replay supports is the shape claim, not an accuracy claim. The accuracy
argument rests on the gate being inside the pipeline: the rewrite is only emitted when it
executes to the same year, so it cannot move an answer, and when it declines the string is
byte-identical to what the old code produced.

One hole this found and closed: `year_selection_query` renders every year's selector where the
old shape rendered only the winner, and that call sat outside the try. An unrenderable loser
would have raised out of `build_solution` and dropped the question to codegen, which is an answer
change dressed as a shape fix (`19171c5`).

## Next Work

1. **Measure raw-table linking across Type 2-5 before expanding it.** Run the current opt-in
   branch on a broad gold slice with `SOLVE_CELL_LOCATOR=1`, `SOLVE_FORMULA_FACTS=1`,
   `SOLVE_RAW_TABLE_LINKER=1`, and `SOLVE_RAW_TABLE_LINKER_PLANNER=1`. Bucket every miss by:
   unsupported request shape, missing scoped table, missing row candidate, search expansion not
   adding slot coverage, wrong candidate among visible candidates, validation reject, or fallback
   codegen error. Only promote the branch after this shows net wins without a regression cluster.
2. **Build raw-linking metadata incrementally, not as a full long-format rewrite.** Start with a
   corpus-level table/row index keyed by table id, ticker, year, doc type, title/header, unit,
   first-column labels, and profiled row labels. Then add domain adapters only for measured,
   stable families such as bank notes, securities-company notes, and movement tables. Avoid
   company-specific adapters unless a failure cannot be represented by metadata plus row/header
   linking.
3. **Structured facts v2 remains useful only for clean main-statement semantics.** Keep
   `understand` coarse and add a richer solve-plan schema after retrieval for VAS fact-layer
   cases: `candidates`, `selection.metric/order/axis`, `filters`,
   `answer.metric/expression/unit`, and `answer.year_offset`. The executor must remain
   deterministic, with coverage validation before execution and codegen fallback on miss.
4. **Raise per-cell accuracy on the questions codegen already sees.** The largest bucket, 12 of
   the 35 misses, is every gold table sitting in front of the model with the wrong cell read out
   of it, and single-cell questions are 43% of the corpus. Cheapest lever, and it touches neither
   retrieval nor the evidence budget.
5. **Run the statement-type classifier at full scale.** `scripts/data_build/classify_statement_type.py` has
   only been run on two ~10-row samples (`artifacts/audits/sample_title_only.jsonl`,
   `sample_with_llm.jsonl`) to check output shape. The real ~2,600-row "unknown" backlog has
   never been classified, and no patch has been reviewed or merged into
   `tables_metadata_v2.jsonl`.
6. **Make the evidence budget per-question.** The error taxonomy this item used to ask for is
   done — see the miss table above. Two claims it overturns. First, "the model reads the wrong
   cell (~34 of 73)" was never a measurement: it was `verify_answer`'s own verdict count (33 of 71
   gold questions say `correct: false`), and that verdict says only *the answer is wrong*, not
   *which node made it wrong*. Second, cell reading really is the top bucket once the misses are
   attributed properly — 12 of 35 — so the old conclusion was right for the wrong reason.
   The actionable part is the runner-up: 7 misses have every gold table in the pool and lose some
   of them to the flat `codegen_max_tables=3` cut. The fix is a budget that scales with the
   question's shape, not more tables for everyone — raising the flat limit 3 -> 10 was measured
   and *lowered* the score (`docs/DECISIONS.md` section 4). Multi-year × multi-company questions
   are 8.4% of the corpus and carry a 24.7% certain-failure rate, three times every other shape.
7. **DeepInfra safety-guard gap in the orchestrator** (flagged by review, non-blocking): when
   `build_data_pipeline.py --with-deepinfra-index` runs with no `--limit`, it can start billing
   immediately with no confirmation prompt, because the orchestrator constructs
   `DeepInfraIndexBuildConfig(yes=True)` directly instead of surfacing the module's own guard.
8. **`docs/tables_metric_probes.md`** records a closed investigation: the leaderboard's
   `relevant_tables` scoring format. Twelve submissions were spent on it and probe H1 closed it —
   two disjoint number ranges scored the same recall, so recall tracks list length and not
   content. Do not spend another submission there.

## Standing Items

- Add typed operations for `get_metric`/`find_row`/`convert_unit` inside `modules/solve/` only
  if a measured failure shows the model needs them — the free-form-query design in section 4 of
  `docs/DECISIONS.md` was chosen over a typed-tool orchestrator (the abandoned direction is not
  documented here; see git history for `docs/REPL_REDESIGN.md` if picking this up again) because
  it measured better, not because typed tools are wrong in principle.
- `data/derived/long_format.parquet` has OCR/parse gaps (e.g. POW 2019 separate lost mã số 151
  because the label OCR'd as "Chỉ phí"). It is now exercised by the opt-in
  `SOLVE_STRUCTURED_FACTS=1` path, so every structured executor change needs a coverage/fallback
  check rather than assuming the fact table is complete.
- #790 fails to resolve BIDV (ticker resolution) — not reverified since the rewrite.
