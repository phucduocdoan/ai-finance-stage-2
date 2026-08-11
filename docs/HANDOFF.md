# Handoff - ViFinQA Stage 2

This is the current operating map for the repo. Source code and artifacts are the
source of truth when any older note disagrees.

## Active Architecture

The active graph answer flow is exposed by `finance_qa.agents.finance.run_question`.
`src/finance_qa/agents/finance/graph.py` is an agent-facing facade; the actual
LangGraph topology lives in `src/finance_qa/pipelines/finance_qa.py`.

```text
understand
  -> modules.rag.service
  -> modules.data.service
  -> route
      lookup + single_cell        -> lookup_solver -> repl fallback on planner error
      formula/compare/multi_step  -> formula_solver -> repl fallback on formula_skip
      other                       -> repl_solver
```

`understand` resolves ticker codes from the authoritative stock-code metadata,
then asks the LLM for a Pydantic `UnderstandIntent` covering operation, metric,
years, document scope, answer shape, and unit hint. It does not parse free-form
LLM JSON with regex.

The module boundary is:

| Path | Responsibility |
|---|---|
| `src/finance_qa/core/` | LLM connection, paths, shared config/types |
| `src/finance_qa/modules/data/` | table store, metadata, preprocessing, canonical finance data, data service |
| `src/finance_qa/modules/rag/` | candidate retrieval, indexes, retrievers, rerankers, judge, RAG service |
| `src/finance_qa/modules/codegen/` | codegen service API, planner IR, generator, repairs, validators, formula planner, REPL services |
| `src/finance_qa/modules/tools/` | numeric, DataFrame helpers, Python execution, metrics |
| `src/finance_qa/pipelines/` | workflow composition for graph QA and batch submission |
| `src/finance_qa/agents/` | reusable agent base plus finance state/config/router/solvers/facades |
| `src/finance_qa/evaluation/` | retrieval and planner evaluation helpers |

Default filesystem paths are owned by `src/finance_qa/core/paths.py`. Application code
should not hardcode checkout-local paths.

## Public Entrypoints

Use these imports from application code and scripts:

```python
from finance_qa.agents.finance import FinanceAgent, FinanceAgentConfig, run_question
from finance_qa.pipelines.finance_qa import build_graph, make_initial_state
from finance_qa.pipelines.submission import main as run_submission_pipeline
from finance_qa.modules.data.service import load_tables
from finance_qa.modules.rag.service import retrieve_table_ids
from finance_qa.modules.codegen.service import (
    generate_solution,
    generate_lookup_solution,
    generate_formula_solution,
    generate_repl_solution,
)
```

Removed top-level namespaces are not supported import paths: `finance_qa.retrieval`,
`finance_qa.preprocessing`, `finance_qa.planning`, `finance_qa.execution`,
`finance_qa.pipeline`, `finance_qa.paths`, `finance_qa.llm`, and
`finance_qa.agents.finance.nodes`.

## Facade And Boundary Files

The import-only scan currently leaves only package/API facades. Other files own a class,
service, or implementation logic.

| File | Current role | Recommendation |
|---|---|---|
| `src/finance_qa/agents/__init__.py` | Owns lazy package API for `BaseAgent`, `FinanceAgent`, `FinanceAgentConfig` | Keep as package API. |
| `src/finance_qa/agents/finance/__init__.py` | Owns lazy finance agent public API | Keep as domain API. |
| `src/finance_qa/agents/finance/graph.py` | Re-exports graph functions from `pipelines.finance_qa` | Keep while scripts/tests import it directly. |
| `src/finance_qa/core/config.py` | Owns `LLMConfig` and env loading. | Keep as config object boundary. |
| `src/finance_qa/modules/codegen/compiler.py` | Owns `PlanCompiler` service wrapper over plan validation/compilation. | Keep as codegen compiler boundary. |
| `src/finance_qa/modules/data/metadata/__init__.py` | Owns `JsonlMetadataStore`. | Keep until metadata moves to a DB-backed repository. |
| `src/finance_qa/modules/data/table_store.py` | Owns file-backed `CsvTableStore`, sync load helpers, and async facade. | Keep as data module boundary. |
| `src/finance_qa/modules/rag/rerankers/deepinfra.py` | Owns DeepInfra reranker implementation. Shared HTTP plumbing lives in `modules/rag/deepinfra_client.py`. | Keep as reranker backend boundary. |
| `src/finance_qa/modules/rag/deepinfra_client.py` | Owns sync HTTP client plus async facade for future gather-based calls. | Keep as shared external-service boundary. |

## Data Snapshot

The current snapshot contains:

- 1,973 OCR report files.
- 146,246 extracted tables.
- 1,012 enriched questions.
- Curated answer labels in `data/eval/extended_gold.jsonl` and `data/eval/planner_answers.json`.

Treat `data/metadata/tables_metadata_v2.jsonl`, `data/indexes/tables_doc_text.parquet`,
and `data/indexes/tables_dense.npy` as protected corpus artifacts. Rebuilds should write
to staging paths first and should not overwrite the dense index unless the rebuild is
deliberate and reproducible.

`scripts/extract_tables.py` rewrites `data/tables/`, `tables_index.jsonl`,
`extract_stats.md`, and `extract_errors.log`. Do not run it as a smoke test.

Corpus-build logic now lives in module services. The `scripts/` files are thin
CLI wrappers that preserve the old commands.

| Stage | Service owner | CLI wrapper | Output |
|---|---|---|---|
| OCR TXT/HTML tables -> raw CSVs | `modules.data.preprocessing.extract_tables.TableExtractor` | `scripts/extract_tables.py` | `data/tables/<report_id>/table_<pos>.csv`, `data/metadata/tables_index.jsonl` |
| v1 table metadata -> enriched metadata | `modules.data.preprocessing.metadata_enrichment.MetadataEnricher` | `scripts/enrich_metadata_v2.py` | `data/metadata/tables_metadata_v2.jsonl`, `artifacts/reports/enrich_v2_stats.md` |
| raw questions -> enriched question metadata | `modules.data.preprocessing.questions.QuestionEnricher` | `scripts/enrich_questions.py` | `data/metadata/questions_enriched.jsonl`, `artifacts/reports/questions_stats.html` |
| metadata -> retrieval text parquet | `modules.data.preprocessing.document_text.DocumentTextBuilder` | `scripts/build_doc_text.py` | `data/indexes/tables_doc_text.parquet` |
| table metadata/CSV -> long format | `modules.data.preprocessing.long_format.LongFormatBuilder` | `scripts/build_long_format.py` | `data/derived/long_format.parquet` |
| retrieval text -> local dense index | `modules.rag.indexing.dense.DenseIndexBuilder` | `scripts/build_dense_index.py` | `data/indexes/tables_dense.npy` |
| retrieval text -> hosted dense index | `modules.rag.indexing.deepinfra_build.DeepInfraIndexBuilder` | `scripts/build_deepinfra_index.py` | `data/indexes/tables_qwen3_4b.npy` |

These services expose `run()` and async `arun()` facades so later pipelines can
orchestrate independent rebuild stages with `asyncio.gather` without importing
from `scripts/`.

## Retrieval

The active retrieval implementation is `src/finance_qa/modules/rag/candidates.py`,
called by `src/finance_qa/modules/rag/service.py`.

```text
shortlist by ticker/year/doc_type and content
  -> BM25 top-k + dense top-k
  -> RRF ordering
  -> primary-statement expansion
  -> optional reranker
  -> LLM judge
  -> selected table ids
```

Graph defaults are defined by `FinanceAgentConfig`:

- `reranker="qwen3-0.6b"`
- `judge_top_n=20`
- `frozen_fallback=True`
- `formula_thinking=True`
- `formula_max_tokens=8192`

The 8192 formula budget is important for thinking-mode calls; 2048 truncates some
multi-step reasoning before the final answer.

## Solver State

The graph has three solver paths. Files under `agents/finance/solvers/` are
LangGraph adapters only; implementation lives behind `modules.codegen.service`.

- `lookup_solver`: calls `generate_lookup_solution`; the model emits a Pydantic
  `OperationPlan`, then repairs/validators/compiler execute it deterministically.
  The graph falls back to REPL on planner error.
- `formula_solver`: calls `generate_formula_solution`, backed by `modules.codegen.formula`.
  It runs deterministic Python over typed plans in this order:
  capability-gated `FactPlan` for aggregate/scenario/growth/DOH/fixed-asset-turnover
  questions, `CanonicalPlan` for stable canonical selection/filtering, then
  `FactPlan` as fallback when canonical planning abstains, then one-shot formula
  reasoning before graph-level REPL fallback.
- `repl_solver`: calls `generate_repl_solution`, backed by `modules.codegen.repl.solve_repl`.

The canonical formula path uses deterministic execution after the model emits a Pydantic
`CanonicalPlan`. Regex in solver paths is limited to low-level parsing such as extracting
report years from table ids; semantic intent and model-produced plans are structured.

Known benchmark notes:

- A green 10-question probe passed for Q363, Q371, Q372, Q378, Q381, Q387, Q390, Q396, Q407, Q426.
- Current live GRAPH20 score is 14/20 with `scripts/eval_graph20.py`.
- Correct GRAPH20 ids: Q363, Q371, Q372, Q378, Q381, Q387, Q390, Q396, Q407, Q414, Q422, Q423, Q424, Q426.
- Remaining misses: Q392, Q409, Q415, Q429, Q439, Q440. Q415 and Q439 are gold-audit
  candidates; Q392 currently lacks complete canonical facts for the requested ticker group,
  and Q429 shows cross-company magnitude/unit normalization issues in canonical facts.

## REPL Direction

The current REPL is useful as a fallback but still asks the model to write pandas code.
The target design is a typed tool orchestrator:

```text
Pydantic OperationPlan
  -> deterministic Python tools
  -> structured repair errors
  -> Python REPL only as an escape hatch
```

See `docs/REPL_REDESIGN.md` for the concrete plan.

## FactPlan V2

`src/finance_qa/modules/codegen/facts.py` materializes canonical data into stable
ticker/year fact rows. `src/finance_qa/modules/codegen/fact_plan.py` asks the LLM
for a Pydantic `FactPlan`, then executes filters, selected-row answers, aggregates,
year offsets, scenario ICR, and inventory-days cash release deterministically.

Fact-only metrics such as operating margin, revenue growth, operating leverage,
inventory days, fixed-asset turnover, previous-year operating profit, and average
fixed assets remain hidden from the older `CanonicalPlan` prompt via
`planner_visible=False`. This keeps the canonical planner stable while FactPlan
handles the richer operations behind a capability gate.

Use this audit when changing formula planning:

```bash
PYTHONPATH=src FORMULA_TRACE=0 .venv_bge/bin/python scripts/audit_graph20_failures.py
```

It writes `artifacts/audits/graph20_failures.jsonl` and `.md`.

## Verification

Use `.venv_bge/bin/python`; these tests avoid LLM calls:

```bash
PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
PYTHONPATH=src .venv_bge/bin/python tests/test_query_execution.py
PYTHONPATH=src .venv_bge/bin/python tests/test_planning_ir.py
PYTHONPATH=src .venv_bge/bin/python tests/test_generation.py
PYTHONPATH=src .venv_bge/bin/python tests/test_candidate_pool.py
PYTHONPATH=src .venv_bge/bin/python tests/test_pipeline_run.py
PYTHONPATH=src .venv_bge/bin/python tests/test_formula_deterministic.py
PYTHONPATH=src .venv_bge/bin/python tests/test_understand.py
PYTHONPATH=src .venv_bge/bin/python tests/test_codegen_structured_planner.py
PYTHONPATH=src .venv_bge/bin/python tests/test_fact_table.py
PYTHONPATH=src .venv_bge/bin/python tests/test_fact_plan.py
```

Graph smoke:

```bash
PYTHONPATH=src FORMULA_TRACE=0 .venv_bge/bin/python scripts/run_graph.py --ids 371 --out artifacts/runs/smoke_q371.jsonl
```

## Agent Handoff Notes

The latest work added a typed `FactPlan` layer for richer formula questions without
hardcoding question ids. Start from these files:

- `src/finance_qa/modules/codegen/fact_plan.py`: Pydantic `FactPlan`, prompt, and
  deterministic executor for filters, selected-row answers, aggregates, year offsets,
  scenario ICR, and inventory-days cash release.
- `src/finance_qa/modules/codegen/formula.py`: routing order between FactPlan,
  CanonicalPlan, one-shot formula, and graph-level REPL fallback.
- `src/finance_qa/modules/codegen/facts.py`: normalized ticker/year fact table over
  canonical data.
- `src/finance_qa/modules/tools/metrics.py`: canonical metric catalog, hidden
  FactPlan-only metrics, derived metric formulas, and unit conversion.
- `tests/test_fact_plan.py`: deterministic coverage for the new execution semantics.

Current measured state:

- Live `scripts/eval_graph20.py` score: 14/20.
- Newly fixed by FactPlan path: Q414, Q423, Q424.
- Preserved canonical wins after capability gate: Q372, Q378, Q407.
- Remaining misses: Q392, Q409, Q415, Q429, Q439, Q440.

Important constraints for the next agent:

- Do not add question-id rules or answer-specific constants. The user explicitly wants
  general graph/planner behavior, not hardcoded competition patches.
- Keep semantic/model outputs Pydantic structured output. Regex is acceptable only for
  low-level deterministic parsing such as report years from table ids.
- Keep FactPlan-only metrics hidden from `CanonicalPlan` with `planner_visible=False`.
  Exposing them to the older canonical prompt previously regressed Q396.
- Keep `unit_hint` from `understand` authoritative over model-supplied answer units.
  This matters for cash-release questions such as Q424.
- Prefer reproducing through the real graph path (`run_graph.py` or `eval_graph20.py`)
  before fixing; isolated solver tests are useful only after the root cause is known.

Suggested next investigation order:

1. Q392: inspect canonical coverage for QNS/OGC/MCH. The current fact table has
   incomplete rows for part of the ticker group, so planner logic alone cannot recover it.
2. Q429: audit magnitude normalization across companies before changing fixed-asset
   turnover logic; current facts show inconsistent scale between MSN and VND-scale peers.
3. Q409 and Q440: audit whether expected labels, metric definitions, or filters differ
   from the current canonical formulas.
4. Q415 and Q439: treat as gold/semantic audit candidates before tuning the solver.

## Current State (2026-08-11)

### The graph is the only answer flow

See `docs/DECISIONS.md` sections 11-12. `scripts/run_pipeline.py` is legacy for
answering; `pipelines.submission.submission_item` remains as the shared packaging
function that `run_graph.py` imports.

`scripts/run_graph.py` gained `--resume` and `--workers` so a long run survives a
kill (v7/v8/v9 previously died mid-run and left nothing to restart from). These
changes are not committed yet.

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --all \
    --out artifacts/runs/graph_1012.jsonl --resume --workers 4
```

Full-corpus graph run in `artifacts/runs/graph_1012.jsonl`. Solver mix shifts
sharply with question id -- `formula` was 2% over the first 400 ids and is ~30%
by id 560 -- so any solver-mix number is only meaningful with its id range.
`status` is always `ok` (the graph reroutes errors to REPL); read `answer == 0.0`
as the failure signal instead.

### Gold-set state

Answer-labeled gold: `data/eval/planner_answers.json` + `data/eval/extended_gold.jsonl`.
Retrieval gold: 15 questions with `gt_tables` in `data/eval/evalset.json`, in
OR-group form (`[[id, id], [id]]`, any member of a group present = hit).

`data/eval/gold100_raw.jsonl` and `scripts/build_gold_candidates.py` (a
non-RAG deterministic resolver) were built to widen retrieval gold to ~100
questions. Measured on the 15 acceptance questions, the resolver recovers 36/36
gold groups, but at:

```
accepted tables/question: min 8  median 42  mean 60.1  max 154   (901 tables for 36 groups)
max tables from a single report: 33
macro P = 4.5%   R = 100%   F2 = 19.2%
```

100% recall at 60 tables/question is not distinguishable from accepting
everything, so the acceptance test as written cannot fail. `--max-candidates`
caps only the `scored` bucket, per (ticker, year) cell; main-statement tables are
additive and uncapped, which is where the volume comes from.

Do not use the resolver's own value extraction as a pruning filter. Keeping only
tables with at least one non-empty row/period match cuts volume to 21.3 and
raises F2 to 43.5%, but drops recall to 74.3% -- it loses the gold table on
qid40, qid754, qid818 and 6 of 7 groups on qid363. It also loses qid818 entirely
in the current code, for the same reason (see below).

Consequence: gold-100 is not usable as a measuring stick in this form. The
defensible set today is the ~53 questions of `gold100_raw` with `<= 10 tables and
0 empty cells`, plus the existing 15 (no overlap) -- about 68 questions.

**Per-report capping was tried and does not fix this.** The resolver now caps
`scored` and `main_statement` tables in two independent tracks, rejecting and
flagging over-cap reports rather than truncating. Independently reproduced sweep
over the 15, macro-averaged:

```
cap   accepted  /q     main%  gt_groups  recall(grp)   R      P     F2
  3     496    33.1    87%       891       23/36     73.3%  5.7%  21.8%
  5     590    39.3    73%      1047       28/36     87.3%  6.1%  23.8%
 10     635    42.3    68%      1158       31/36     93.3%  6.1%  24.1%
 20/999 635    42.3    68%      1158       31/36     93.3%  6.1%  24.1%
```

Capping is applied once per question over the union of all cells (`report_id`
already carries ticker+year), so `max accepted from one report` is 21 against a
theoretical bound of `max_per_report + max_main_per_report`. Extracted values are
filtered by `_is_empty_value()` before being recorded, so 0/1208 row/period
matches are empty -- an earlier 18.1%-empty measurement was on pre-fix code.
`rapidfuzz` is now installed in `.venv_bge`.

The knob saturates at 10 (10/20/999 are byte-identical) and buys ~5 F2 points
over the uncapped baseline. Do not spend more time tuning it; leave it at 10.

The blocker was composition, not volume. At cap=3, 496 accepted tables = 276
unmatched main statements (56%) + 157 matched main + 63 scored (13%): 87% of the
artifact was blanket primary-statement inclusion and only 13% came from scoring.
That was also circular -- the retrieval pipeline itself performs
primary-statement expansion, so scoring against such a gold set compares the
pipeline's heuristic to a second copy of the same heuristic.

Two recall "hits" under that scheme were not signal: qid40's gold table
(`VIB_financial_statements_2020_consolidated|10`) was accepted as
`main_statement` with **zero** row/period matches, and qid363 scored 7/7 the same
way.

**Fixed:** main statements with no row/period match now go to a separate
`unverified_tables` field instead of becoming singleton `gt_tables` groups, and
`max_per_report` is locked at 10. Measured over the 15:

```
                      accepted   /q    hit     R      P      F2   flagged
before, cap=3            496    33.1  23/36  73.3%   5.7%  21.8%    28
after,  cap=3            220    14.7  16/36  61.0%  18.6%  41.9%    28
after,  cap=10 (default) 359    23.9  24/36  81.0%  16.9%  46.0%     0
```

Recall drops are the fake hits disappearing (qid40 1/1 -> 0/1, qid363 7/7 ->
1/7). Precision roughly triples. 276 tables/15 questions (18.4/q) move to
`unverified_tables`.

### The remaining defect: one phrase list serving two consumers

`gt_tables` group inflation is **not** fixed by the above: 891 groups before,
**882 after** (656 of them singletons, max 142 groups on one question) against a
real gold of 36 groups for these 15. Every distinct `(matched_phrase, value)`
pair spawns a fact_group.

Root cause: `extract_phrases()` -> `expand_subphrases()` emits every contiguous
2+-word sub-phrase, and the same expanded list is passed to **both**
`score_table()` and `extract_row_period_matches()`. Those consumers want
opposite things -- scoring wants broad recall (a loose phrase only shifts
ranking), fact extraction wants the question's target metric (a loose phrase
becomes an asserted fact and a gold group). Consequently "value-backed" is a
weak credential: a table qualifies because some row label contains a two-word
fragment of the question.

```
qid605 "... người mua trả tiền trước ngắn hạn ... NLG": real gold 1 group, emitted 77.
       52 of the matches are on the bare fragment "ngắn hạn" (hits every short-term row).
qid363 "... hệ số khả năng thanh toán lãi vay ...":     real gold 7 groups, emitted 83.
       87 of 100 matches are on the fragment "lãi vay".
```

Probe (monkey-patching only the list passed to `extract_row_period_matches`,
scoring untouched) -- evidence for the diagnosis, not the fix:

```
all subphrases (current)   acc 359 (23.9/q)  24/36  R 81.0%  P 16.9%  F2 46.0%  groups 882  max/q 142  no-gold 0
extraction phrases >=3 w   acc 135 ( 9.0/q)  20/36  R 66.7%  P 24.2%  F2 49.4%  groups 145  max/q  27  no-gold 3
extraction phrases >=4 w   acc 123 ( 8.2/q)  20/36  R 66.7%  P 25.7%  F2 50.5%  groups 126  max/q  25  no-gold 3
```

Fix direction: keep the full expansion for `score_table()`; pass only maximal
pre-expansion phrases (drop any phrase that is a substring of another) to
`extract_row_period_matches()`. Questions left with no value-backed group should
be reported and excluded from the gold set, not given a weak one.

**Fixed:** `maximal_phrases()` now filters the pre-expansion phrase list down to
non-substring phrases before it reaches `extract_row_period_matches()`;
`score_table()` still gets the full `expand_subphrases()` list. Measured over
the 15:

```
                          groups  max/q  no-gold  accepted  /q    hit    R      P      F2
before (shared list)         882    142       0       359  23.9  24/36  81.0%  16.9%  46.0%
after (maximal_phrases)      121     32       2       108   7.2  20/36  66.7%  30.2%  53.7%
```
(R/P/F2 are macro, per-question-averaged, matching gold_acceptance_test.py's
own numbers -- not the same arithmetic as the raw 20/36 group count.)

qid40 and qid674 now report zero gt_tables groups instead of one: both were
previously a bare 2-word fragment ("VIB" main-statement row, "lợi nhuận ròng"
sub-phrase) fuzzy-matching an unrelated row and asserting a fact from it --
the same "luck, not signal" failure mode as before, just a different trigger.
Reporting no gold for these two is the intended, honest outcome, not a
regression to chase back.

Header parsing is the next defect after that, not before it: two-row/spanning
headers (`FTS_financial_statements_2018/table_22.csv`, qid818's whole 0/5) and
numeric note-code columns where `looks_codey`'s `frac_numeric < 0.3` never fires
(`VIB_financial_statements_2020_consolidated|10`, qid40).

**Fixed (partially):** the two-row/spanning-header bug is not a single-file
defect. A corpus scan (row 1 of the raw CSV consisting entirely of cells drawn
from a closed vocabulary of note-table header words -- "Số đầu kỳ", "Số cuối
năm", "Tham chiếu", etc.) found **1061 of ~data/tables/*/*.csv** with this
shape, not just `table_22.csv`. `load_table_csv`'s `header=0` read silently
folds that second physical header row into the first data row.

Two sub-patterns:
- simple (VIC/BAF/SSI-style): row 0 is a non-informative title/unit row with no
  real per-column headers; row 1 is the real header and slots in starting one
  column after `label_col`.
- FTS-style "umbrella": row 0 already carries real headers for a prefix of
  columns plus a period-anchor token ("Số cuối năm") sitting where row 1's
  finer sub-headers belong, plus one more trailing token that is actually the
  header for the table's *last* column, not the column pandas put it in.

`merge_second_header_row()` (`scripts/build_gold_candidates.py`, called from
`extract_row_period_matches()` right after `label_col` is computed) detects
the pattern and places row 1's tokens structurally, reusing `BEGIN_RE`/`END_RE`
to classify row 0's own tokens: 0 period-anchor tokens in row 0 -> start after
`label_col`; 1 -> start at its column; >=2 -> second-to-last is the umbrella
start, last is relocated after row 1's block. Verified in isolation against
`table_22.csv`: reconstructs the exact correct 9-column header.

Two alternatives were tried and rejected before this one:
- naive same-position merge -- wrong for the umbrella pattern specifically:
  it would place "Số cuối kỳ" on the column that structurally holds "đầu kỳ"
  data, a confidently wrong number rather than no match.
- scored shift search (score a shift by whether a period-anchor token lands on
  a high-`frac_numeric` column) -- for `table_22.csv`, shift=1 and shift=3 tie
  at the same score because adjacent columns are all monetary; a "smallest
  shift wins" tie-break picks shift=1, which is wrong (hand-verified by
  reconciliation: đầu kỳ 199,170,000 + trích lập 21,890,000 − hoàn nhập
  30,910,000 = cuối kỳ 190,150,000, which only lines up under shift=3).

Residual, explicitly out of scope: a 3-row nested header
(`MWG_financial_statements_2015_separate/table_18.csv`) is not handled -- rare
enough, and the unmerged leftover row is inert text rather than a source of
wrong values, so it is no worse than before the fix.

**Does not (yet) close qid818.** The fix is structurally correct and does not
regress the 15-qid acceptance test, but the aggregate numbers are unchanged
(still 20/36, F2=53.7%, qid818 still 0/5). Root cause: qid818's row-label
match fails for a *different*, unrelated reason --
`fuzz.token_set_ratio("tổng số dư dự phòng phải thu khó đòi", "dự phòng nợ
phải thu khác khó đòi")` = 86.2, under `ROW_MATCH_THRESHOLD = 90`. This is a
phrase-wording/threshold gap in `find_row_matches()`, not a header-parsing
problem, and is not part of bug #4 or bug #3 -- flagged here, not fixed.

**Fixed (partially), bug #3:** `looks_codey`'s `frac_numeric < 0.3` never fired
because `col_content_stats()` counted a bare note-reference code ("33", "24",
roman numerals) as "numeric" -- it matches `NUMERIC_RE` just as well as a real
monetary figure does. Fix: exclude `SHORTCODE_RE` hits from `frac_numeric`'s
count (`n_num`), so a note-code column now correctly measures as
`frac_numeric≈0`, `frac_shortcode≈1`. Verified directly on
`VIB_financial_statements_2020_consolidated|10`'s "Thuyết minh" column: before
the fix, `frac_numeric=1.0` (blocked); after, `frac_numeric=0.0`,
`looks_codey=True`.

Does not fully close qid40, and for a related but distinct reason from
qid818's: the shift is additionally gated on `not header_has_period(next
column's raw header)`, and that check fires on *any* year-like token in the
next header, not just the asked one. VIB's own two reports disagree here for
no semantic reason -- `VIB_financial_statements_2020_consolidated|10`'s next
header is "2019 Triệu VND" (space before "Triệu" -> `\b(19|20)\d{2}\b` finds a
word boundary after "2019" -> blocks the shift, matches=[] end to end) while
`VIB_financial_statements_2020_separate|9`'s is "2019Triệu VND" (no space ->
no boundary after the digits -> shift proceeds, correctly extracts "Lợi nhuận
sau thuế" / 2020 / 4.637.745). Both tables have the identical misplaced-header
shape; only OCR whitespace decides which one the current code fixes. This is
a distinct, deeper defect in `assign_period_headers`'s single-hop design (it
assumes only one column's header is ever misplaced at a time; here the whole
header row is offset by one column, so the "next column already has its own
valid period" check is fooled by a header that is *itself* also misplaced).
Not fixed here -- flagged, not part of bug #3 as scoped, and a hasty patch
risks the same wrong-value-shift failure mode rejected for bug #4's naive
merge (a chain-shift heuristic could confidently place a period label on a
codey column that happens to hold a look-alike value on some other row).

Acceptance test after this fix: unchanged in aggregate (still 20/36, F2=53.7%,
109 vs 108 accepted tables -- the one new accepted table is
`VIB_financial_statements_2020_separate|9`, a real, correctly-extracted
row/period match, just not the report qid40's gold group asks for).

**Coverage re-run over gold100_raw (item (d), post a+b+c):** re-ran
`build_candidates_for_question()` (current code, all three fixes applied) over
the 100 qids in `data/eval/gold100_raw.jsonl` (disjoint from the 15
acceptance-test qids) at the locked defaults (`DEFAULT_THRESHOLD=95`,
`max_per_report=10`; 90 is the separate `ROW_MATCH_THRESHOLD`):

```
81 of 100 questions have >=1 value-backed gt_tables group (81.0%)
mean groups/question:   18.3 (all 100) / 22.6 (the 81 covered)
median groups/question:  6.0 (all 100) /  9   (the 81 covered)
mean tables/group:       1.21 (1827 groups total)
reports flagged for manual review (over-cap): 1
questions with a scope_warning: 0
```

Same inflation pattern as the 15-qid set, at greater scale: 33 of the 81
covered questions emit >10 groups (qid571 emits 138, qid549 126, qid563/570
100 each). 43 of 100 land in a <=3-group range, but 19 of those are the
zero-group questions below (no evidence, not "usable"); so only 24 of 100
are *covered* questions with a plausibly-usable <=3-group count.
Mean tables/group (1.21) confirms groups are almost always singletons, so the
inflation is in group *count*, not group *size* -- consistent with the
"every distinct (matched_phrase, value) pair spawns a fact_group" root cause
already identified above, not a new defect. 19 of 100 questions emit zero
groups (no value-backed evidence located at all under current phrase/threshold
matching) -- these are the honest "resolver found nothing" outcome, not
resolver bugs to chase; a mechanical, non-hand-labelling pass here is a
different task (structured question -> target-metric extraction, per the
precision-half discussion below), not part of (a)/(b)/(c).

This does not change the ceiling finding above: gold100_raw remains triage
input for a human pass, not an automatic scoring target, regardless of the
81/100 coverage number -- coverage measures "did the resolver find *some*
value-backed fact," not "did it find the *right* one."

### The artifact still cannot serve as a measuring stick (the 38.9% ceiling)

`maximal_phrases()` cut inflation 7× (882 -> 121 groups) but did not make the
output usable as gold. Per-question, against the 15 questions that have real
`gt_tables` in `data/eval/evalset.json`:

```
 qid realG emitG  infl  acc unver   hit
   1     1     7    7x    4     3 1/1
  17     1    17   17x   12    13 1/1
  40     1     0    0x    0    15 0/1
  44     1     2    2x    2    11 1/1
  55     1     1    1x    1    14 1/1
 100     1     1    1x    1    14 1/1
 363     7    12    2x    6    65 0/7
 524     5    32    6x   39    74 5/5
 582     2    14    7x    9    27 2/2
 605     1     4    4x    4    23 1/1
 674     1     0    0x    0    11 0/1
 752     2    19   10x   20    20 2/2
 754     2     6    3x    4     8 0/2
 818     5     1    0x    1    78 0/5
 820     5     5    1x    5    22 5/5
total emitted 121 vs real 36  -> 3.4x inflation
```

Only qid44/55/100/820 are clean. **A perfect retriever that returned exactly the
real gold would score 38.9% recall against the emitted gold set.** Any F2 number
measured against this artifact is therefore dominated by artifact error, not by
retriever error -- it cannot be used to accept or reject a retrieval change.

The two halves now separate cleanly and need different fixes:

- **Precision / inflation** is no longer a phrase-heuristic problem. Every
  distinct `(matched_phrase, value)` located in a resolved report becomes a gold
  group, regardless of whether the question asks for that fact. Deciding *which*
  located fact answers the question is semantic -- per the constraint at the top
  of this file, that belongs in a Pydantic structured-output step (question ->
  target metric + period + entity), not in more string filtering. This is a new
  step, not covered by (b)/(c)/(d).
- **Recall** does depend on the header-parse defects: qid40, 363, 674, 754, 818
  are all at 0 hits, and 818's whole 0/5 plus 40's 0/1 trace to the two known
  header bugs. (b) and (c) stay valid and stay next.

Until the precision half lands, the gold set's honest use is **triage input for a
human pass**, not an automatic scoring target. Do not wire it into
`scripts/eval_submitted_retrieval.py`.

### Bug #4 (two-row headers): verified, corpus-wide, zero measured effect

`merge_second_header_row()` promotes a genuine 2nd physical header row that
`load_table_csv`'s `header=0` read left sitting in the first data row. Scope
claim independently confirmed: **1061 of 146,246** table CSVs have a first data
row that is entirely closed-vocabulary header words.

Branch distribution across those 1061:

```
none(->label_col+1)   1059   (99.8%)
umbrella(>=2)            2   FTS_..._2017|table_24, FTS_..._2018|table_22
single(==1)              0   dead path, never fires anywhere in the corpus
```

The hand-reconciled umbrella relocation covers two tables in the entire corpus;
its "clobber" of an existing header is benign on both (`Unnamed: 8` placeholder).

**Effect: none that we can score.** On the 15-qid acceptance path the function is
called 891 times and fires **once**; the acceptance test is byte-identical
(108 accepted, 20/36, P 30.2% / R 66.7% / F2 53.7%). Record this as a
correctness fix with real corpus scope, *not* as a recall improvement.

Residual defect in the branch that carries 99.8%: **31 tables** have more row1
tokens than slots after `label_col`, so the `if j < ncols` guard silently drops
the overflow (`CTG_financial_statements_2016_separate|table_77` is 4 tokens into
1 slot). A 4-into-1 overflow means either `find_label_col` chose wrong or row1 is
not a header at all -- diagnose it, do not widen the guard.

**qid818 is not a header bug and not a threshold bug.**
`fuzz.token_set_ratio("tổng số dư dự phòng phải thu khó đòi", "dự phòng nợ phải
thu khác khó đòi")` = 86.2 vs `ROW_MATCH_THRESHOLD = 90`. But the row says "phải
thu **khác** khó đòi" (other receivables) while the question says "phải thu khó
đòi" -- plausibly different line items. Lowering the shared threshold to admit
86.2 would accept a possibly-wrong row to turn one qid green: the same "luck, not
signal" failure already removed twice. This belongs to the semantic-selection
step above. Do not lower `ROW_MATCH_THRESHOLD`.

### Bugs #3 and #4, and the gold100 coverage run: independently verified

Every reported number reproduces on the on-disk code
(`build_gold_candidates.py` md5 `20f0e30226be49acada014a81a9ecf5e`):

- bug #3: acceptance test 20/36, macro P 30.2% / R 66.7% / F2 53.7%, accepted
  108 -> **109** (the +1 is `VIB_financial_statements_2020_separate|9`, a correct
  new match but not qid40's gold report).
- the VIB whitespace finding is exact. `consolidated|10` col3 header is
  `'2019 Triệu VND'` -> `header_has_period` True -> shift blocked -> qid40 still
  gets no match. `separate|9` col3 is `'2019Triệu VND'` (no space, so no `\b`)
  -> False -> shift proceeds and extracts the right cell. Same table shape; a
  single space decides.
- bug #3's blast radius on the acceptance path is **exactly 4 tables**, all at
  column index 2, all `frac_numeric 1.00 -> 0.00` with `frac_shortcode 1.00`
  (`SHB_..._2018_consolidated|5`, `SHB_..._2018_separate|6`,
  `VIB_..._2020_consolidated|10`, `VIB_..._2020_separate|9`). Measured by
  re-deriving the pre-fix `col_content_stats` and counting `looks_codey`
  False->True flips, not by reading the reported number. Per-qid recall on the
  five zero-hit questions is byte-identical before and after (40: 0/1, 363: 0/7,
  674: 0/1, 754: 0/2, 818: 0/5), so like bug #4 this is a **correctness fix with
  zero measured recall effect**, and must be recorded as such.
- gold100_raw (100 qids): **81/100** covered, mean groups/q 18.3 (22.6 over the
  81), median 6.0 (9), **1827** groups total, mean tables/group 1.21, 33 questions
  emit >10 groups (571 emits 138, 549 126, 563/570 100 each), 19 emit zero,
  1 question flagged for manual review, 0 scope warnings, total
  `unverified_tables` 3154 (31.5/q).

**The available signal for the qid40 chain-shift is better than the current
gate.** In `consolidated|10`, col2 carries the period header `'2020 Triệu VND'`
*and* has `frac_shortcode = 1.00 / frac_numeric = 0.00`; col3 carries
`'2019 Triệu VND'` and `frac_numeric = 1.00`. A period header sitting on an
all-shortcode column is itself direct evidence that the header row is offset --
strictly more informative than "the next column has no period header of its own",
which cannot tell a valid period from a misplaced one. Any such change must be
validated the way `table_22` was (arithmetic reconciliation of the resulting
columns), not by whether one qid turns green.

**Extrapolated inflation is worse at scale, not better.** Real gold on the
acceptance 15 averages 36/15 = 2.4 groups per question; gold100_raw emits 18.3.
That is ~7.6x, against 3.4x on the 15 (which contain several easy single-fact
questions). A human triage pass over gold100 would face 1827 groups to reach an
expected ~240. Two config notes for the record: the (d) run used
`DEFAULT_THRESHOLD = 95`, not 90 as first reported (90 is `ROW_MATCH_THRESHOLD`),
and "24 of 100 usable" means 24 *covered* questions with <=3 groups (43 of 100
have <=3 groups, but 19 of those have zero).

### The full 1012 graph run (artifacts/runs/graph_1012.jsonl)

Completed: 1012/1012 records, **0 errors**, 0 `answer is None`, every question got
at least one table. Median 6 s/question, p90 74 s, max 976 s.

```
solver     n   ans=0.0   rate
formula  296        54  18.2%
lookup   429         8   1.9%
repl     287       114  39.7%
TOTAL   1012       176  17.4%
```

Scored against the only answer labels that exist (`planner_answers.json` 15 +
`extended_gold.jsonl` 20 = **34 distinct qids** -- 3.4% of the set, so this is a
signal, not a grade):

```
        7/34 = 20.6%
lookup  5/7  = 71%
formula 2/21 = 10%
repl    0/6  =  0%
```

**The formula branch is the loss centre**, and it carries 296 questions. `repl`
returns exactly `0.0` on 40% of the questions routed to it.

Other magnitude signals across all 1012: 14 answers `> 1e13`, 7 answers collapsed
to `0 < |x| < 1e-6`, 92 negative answers. `table_ids` per question: median 3,
p90 10, max 10, mean 4.5.

**Correction to Step 2's justification below:** on this graph run the
#55/#818/#820 losses are *not* scale errors. #55 is off by a factor of exactly
**2.0** (a doubling, not a decimal shift), #818 returns `0.0` (no value at all),
#820 returns `2.1e-08` against 4.06904 (ratio 5.2e-9, not a power of ten). Of all
34 labelled questions exactly **one** (#524, ratio exactly 1e9) is a clean
power-of-ten error. The "all pure scale errors" finding was measured on Flow A and
does not transfer to the graph. Step 2 is still correct as consolidation work, but
it buys ~1-3 of 34, not the bulk -- do not schedule it as the big win.

## Execution scoring: `pandas_query` must be code, not a trace

The first graded submission returned three warnings, two of which were real:
`80 question(s) scored 0 on execution because of NameError` and `74 ... SyntaxError`.
Root cause: all **296** questions routed to the `formula` solver shipped the
planners' *diagnostic trace* as `pandas_query` -- `canonical_plan(ticker=HPG,...)`,
`fact_plan(answer=gross_margin.mean,...)`, `formula_oneshot(3 tickers)` -- plus
`evidence: []`. Reproducing the grader's pass over the ZIP showed 296 failures,
all inside that branch and none outside it. (`gold=506 pred=1012` is not a defect:
only 506 of the 1012 ids carry gold. 154/506 = 30.4% matches 296/1012 = 29.3%.)

The 287 `repl` questions ship a bare float literal and pass, so a literal is an
accepted query. The fix is therefore two-tier:

- **Traceable answers emit real pandas.** `canonical_frame` fills an optional
  provenance map `(metric, year) -> (row, col)`; `TracedValue` in
  `modules/tools/metrics.py` is a float that carries its pandas expression, so
  re-running the *existing* metric formulas over it yields
  `((df2.iloc[14, 4] + df2.iloc[6, 4]) / df2.iloc[6, 4])` for free -- there is no
  second copy of the formula table. `pandas_expr_for_metric` refuses to return an
  expression unless it re-evaluates to the exact answer being submitted.
- **Everything else emits the literal.** The one-shot reasoner has no plan to
  trace, and a `fact_plan` aggregate (`.mean`/`.sum`) has no single source cell, so
  those fall back to `repr(answer)` with the contributing frames as evidence, the
  way `repl` already does. The trace is preserved in `errors`.

Positional `.iloc[row, col]` is used because `build_submission.py` writes
`to_csv(index=False)`, so positions round-trip, and duplicate column names do not.
`TracedValue.__abs__` folds the sign at build time so no query depends on builtins.

Verified on `output/submission_graph_v3.zip` (built from
`artifacts/runs/graph_1012_v3.jsonl` via `scripts/merge_runs.py`): **0/1012
execution failures**, and all 1011 numeric queries evaluate to exactly the answer
submitted next to them, i.e. execution accuracy now equals answer accuracy. Only
qid707 still needs builtins, and that query comes from the planner's generator, not
from this path.

## Next Work

Consolidation steps, in dependency order. Steps 1-2 are the ones with located
root causes; the rest are scoped but not diagnosed to the same depth.

0. **Error taxonomy for the formula branch** (new, now the highest-value item):
   2/21 correct on labelled questions and 296 questions routed there. Start from
   the labelled misses, whose ratios are scattered (0.035x to 15x) rather than
   decimal -- i.e. wrong operands or wrong rows, not wrong units.
1. **One metadata source.** `understand` output is authoritative for a graph run;
   fall back to frozen `questions_enriched.jsonl` only for fields `understand`
   does not produce. Today both are live in different places.
2. **Thread `unit_hint` into codegen.** Add the parameter to `generate()` and
   pass it from `lookup_solver`. See `docs/DECISIONS.md` section 12. Scope it
   honestly: measured on the graph run this is worth ~1-3 of 34 labelled
   questions (see the correction above), not the #55/#818/#820 story.
3. **One repair policy.** `MAX_REPAIRS = 2` plus the 10 deterministic repairs in
   `modules/codegen/repairs.py` are load-bearing (211 of 773 Flow A successes came
   from attempts 2-3), but the formula branch has no repair loop of its own.
4. **Decouple submitted tables from planner-fed tables.** `picks == table_ids` in
   1008/1012 runs, so the LLM judge's answering shortlist is also the submission,
   and recall-oriented and precision-oriented goals fight over one list.
5. **Header-shift fix in `load_frame`.** 359 tables across 158 reports (mostly
   banks) shift the period header one column off the data, producing silently
   wrong numbers rather than errors. `assign_period_headers` in
   `scripts/build_gold_candidates.py` is a working reference implementation.
6. **Gold answers.** Retrieval gold does not score answers; answer coverage is
   still only `planner_answers.json` + `extended_gold.jsonl`.

Standing items carried over:

7. Remove or merge import-only compatibility files that are not public API.
8. Add typed REPL operations for `get_metric`, `find_row`, `compute`, and `convert_unit`.
9. Add abstain/diagnostic behavior when canonical data is missing or magnitudes are implausible.
10. Keep DB/storage work behind `modules.data.repositories.TableRepository` rather than leaking storage details into RAG or agents.

Open questions for the user, unanswered:

- Whether steps 1-2 land before or after the current 1012 run finishes.

(The per-report rejection threshold is no longer a question: the sweep above
shows it saturates at 10 and moves F2 by ~5 points, so it is a measurement
result, not a judgement call.)

Two side findings, unfixed and not part of the steps above:

- #790 fails to resolve BIDV (ticker resolution).
- `data/derived/long_format.parquet` has OCR/parse gaps -- POW 2019 separate lost
  mã số 151 because the label OCR'd as "Chỉ phí".
