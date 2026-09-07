# Decisions - ViFinQA Stage 2

This file records current engineering decisions. Historical experiment logs for the
architecture these decisions replaced live in git history, not here — an old path or
conclusion in git log is not implementation guidance.

## 1. Code Organization

```text
core      -> shared config, LLM client, paths, types
modules   -> data, rag, solve, tools
pipelines -> compose module services (and the graph) into runnable jobs
agents    -> domain-facing agent state/understand/graph topology/public entrypoints
```

Decision:

- Keep module internals behind `service.py` when another module or pipeline calls them.
- Keep cross-module orchestration in `pipelines/`, not in `modules/`.
- Keep agent state/understand/graph-topology code under `agents/finance/`.
- Keep future database/storage work behind `modules.data.repositories.TableRepository`.

Rationale:

- Modules stay reusable and testable.
- Pipelines can change without forcing storage/RAG/solve internals to import each other.
- A future DB backend can replace file-backed table loading through the data service boundary.

## 2. Supported Import Paths

Supported public surfaces:

```python
finance_qa.agents
finance_qa.agents.finance
finance_qa.pipelines.submission
finance_qa.pipelines.data_pipeline
finance_qa.modules.data.service
finance_qa.modules.rag.service
finance_qa.modules.solve
finance_qa.core.paths
finance_qa.core.llm
```

Removed import paths are not compatibility targets — do not route new code through them and
do not re-add shims for them:

```text
finance_qa.modules.codegen        (deleted: planner IR, generator, repairs, formula, REPL)
finance_qa.modules.data.canonical (deleted, orphaned once codegen went)
finance_qa.modules.tools.metrics  (deleted: canonical metric catalog)
finance_qa.agents.finance.router
finance_qa.agents.finance.solvers (lookup/formula/repl LangGraph adapters)
finance_qa.evaluation.planner
finance_qa.pipelines.finance_qa   (old graph topology module; topology now lives in agents.finance.graph)
finance_qa.retrieval
finance_qa.preprocessing
finance_qa.planning
finance_qa.execution
finance_qa.pipeline
finance_qa.paths
finance_qa.llm
finance_qa.agents.finance.nodes
```

## 3. Retrieval

Active implementation: `src/finance_qa/modules/rag/candidates.py`, called by
`src/finance_qa/modules/rag/service.py`. Unaffected by the codegen/graph rewrite in
section 4 — retrieval and solving are independent stages joined only by `table_ids`.

Decision:

- Use deterministic filters for ticker/year/doc_type before semantic retrieval.
- Use BM25 and dense retrieval as candidate sources, combined by RRF.
- Keep primary-statement expansion in the pool so balance sheet, income statement,
  cash flow, and equity-change tables remain reachable even when lexical matching favors notes.
- Let the LLM judge select final evidence tables from the pool.
- Configure graph retrieval through `FinanceAgentConfig` and `modules.rag.service`.
- If ticker/year is missing, fall back to the frozen `artifacts/runs/full_1012.jsonl` cache
  when `frozen_fallback=True` — this is a retrieval-quality safety net, not a data source to
  build new logic on top of.

Rationale:

- Report-tier retrieval is structurally constrained by metadata.
- The hard part is selecting the correct table inside a known report.
- Primary statement tables are sparse enough to include directly and important enough
  that missing them is expensive.

Current graph defaults (`agents/finance/config.py`):

```python
reranker = "qwen3-0.6b"
judge_top_n = 20
judge_thinking = False   # measured: beats thinking=True at every K once qwen3 reranks first
frozen_fallback = True
```

## 4. The Graph Is One Flow, Four Nodes, No Router

The old design routed a question to one of three solvers (`lookup`/`formula`/`repl`), each
backed by its own planner/IR/repair stack in `modules/codegen/` (~3,900 lines). That
architecture, all of `modules/codegen/`, `agents/finance/solvers/`, `agents/finance/router.py`,
`evaluation/planner.py`, and `modules/tools/metrics.py` are deleted.

Decision — every question takes the same path:

```text
understand -> retrieve -> generate_pandas -> execute_and_repair -> verify_answer
```

- One LLM call in `generate_pandas` (`modules/solve/codegen.py`) reads the actual table
  *contents* (not a schema) for the head of retrieval's ranking and writes one pandas
  expression. It does not choose a solver route or plan a multi-step program.
- Deterministic code, not the model, owns unit detection/conversion (`modules/solve/units.py`),
  execution + repair on exceptions (`modules/solve/execute.py`), and a second-look check of
  whether the query read the cell the question actually asked for (`modules/solve/verify.py`).
- No fallback chain between solvers, because there is only one solver. A failure is
  attributable to a specific node.

Rationale (measured, see `agents/finance/graph.py` and `modules/solve/*.py` docstrings for the
numbers behind each of these):

- The old per-solver schema-only prompt never showed the model cell values, so most of the
  deleted code was scaffolding around a model that couldn't see the table it was reasoning about.
- Letting one query span multiple cells/dataframes (instead of a singular `target_row`/
  `target_column`) took the "needs several cells" bucket from 0/13 to 5/13 on the gold set.
- `codegen_max_tables=3` is deliberate, not a budget shortcut: raising it to 10 puts more of the
  gold set's needed tables in front of the model, but the model's accuracy on those questions
  drops enough that the net score falls (33 -> 29 on the 73-question gold set at the time of
  measurement) — telling the right table from nine near-duplicates is the binding constraint,
  not coverage.
- `verify_answer` exists because repair only fires on exceptions, so a query that runs cleanly
  and reads the wrong cell would otherwise pass unchallenged. It is gated to run once, only when
  it changes the answer, with no re-verification of its own rewrite — a verifier that can veto
  its own replacement loops forever on the questions where the verifier itself is wrong.
  Its value is as a *detector*, and that is measured: on the gold set its `correct` verdict
  agrees with ground truth on 62 of 71 questions (87%), which makes it the broadest gold-free
  error signal the run records. What it does not do is locate the fault — an earlier version of
  this file cited its 33-of-71 "wrong" count as if it were a measurement of *where* the failure
  was. Attributed properly against `evidence_table_id`, cell reading is indeed the top bucket
  (12 of 35 labelled misses) — but that is a separate measurement, and the count is 12, not 34
  (`docs/HANDOFF.md`, "Current Benchmark State").

## 5. Solving Uses LLMs For Intent, Code For Facts

Decision, unchanged in spirit from before the rewrite:

- Use deterministic code for anything with a clear authority: ticker mapping (BTC's
  `code_stock.csv`), unit detection/conversion, execution, verification-of-what-ran.
- Use the LLM for the two things without a deterministic source: which cells answer the
  question (`generate_pandas`), and whether a wrong-looking answer is actually wrong
  (`verify_answer`).
- Prefer Pydantic structured output over regex parsing for anything the model produces.
  Regex is acceptable only for low-level deterministic parsing (e.g. report years from table
  ids, the Vietnamese report-scope backstop below).
- Do not add question-id rules or answer-specific constants. General graph behavior only.

## 6. Report Scope Backstop In `understand`

Decision (`agents/finance/understand.py`):

- `understand` promotes `doc_type` from `unknown` to `separate` when the question names the
  separate/parent-only scope outright (`công ty|ngân hàng|tổng công ty mẹ`,
  `BCTC|báo cáo tài chính|báo cáo riêng`, `riêng lẻ`) and does *not* also say `hợp nhất`.
- One-directional: it only fills `unknown`, never overrides a scope the LLM committed to.
- A question naming both scopes is left `unknown` on purpose — `doc_type` is one field for the
  whole question, so a per-year scope split cannot be expressed here.

Rationale: scope is not cosmetic. Across the ~97k (ticker, year, mã số, period) cells that carry
both scopes, consolidated and separate differ by >1% in 82% of cases. The LLM returned `unknown`
for six questions that state the scope in so many words; the backstop is a rule reading an
explicit surface marker, not semantic inference, so it doesn't conflict with the no-hardcoding
principle above.

## 7. Submission Pipeline

Active implementation: `src/finance_qa/pipelines/submission.py`, now trimmed to
`submission_item()` — the shared packaging function.

Decision:

- The graph (`agents.finance.graph.arun_question`, driven over many questions by
  `scripts/pipeline/run_graph.py`) is the only flow that answers questions.
- `submission_item()` stays as a standalone function because packaging (turning a solved
  question into the leaderboard item shape) was never duplicated code — only the two old
  drivers' *answering* logic was.
- `scripts/pipeline/build_submission.py` packages a `run_graph.py` JSONL into `output/submission.zip`.

## 8. Data Pipeline And Protected Artifacts

Decision:

- Corpus-build logic lives in module services (`modules/data/preprocessing/`,
  `modules/rag/indexing/`); `scripts/*.py` are thin CLI wrappers.
- `src/finance_qa/pipelines/data_pipeline.py` (+ `scripts/pipeline/build_data_pipeline.py`) chains
  the required rebuild order — `enrich_questions -> build_doc_text -> build_dense_index` — with
  `extract_tables`, `build_long_format`, and the paid `build_deepinfra_index` as explicit,
  off-by-default stages.
- Treat `tables_metadata_v2.jsonl`, `tables_doc_text.parquet`, and `tables_dense.npy` as
  protected artifacts. Rebuilds go through staging paths, not in place.
- `scripts/data_build/extract_tables.py` rewrites corpus artifacts and is not a diagnostic command.

Rationale:

- The bge-m3 dense index (`tables_dense.npy`) cannot be rebuilt today: it was built from a v1
  metadata file (`tables_metadata.jsonl`) that no longer exists on disk. Losing the index file
  itself would be unrecoverable without redoing that v1 pass from scratch. This is why a second
  dense backend (`tables_qwen3_4b.npy`) is a new file, never a rewrite of the existing one.
- The metadata/index snapshot (146,246 tables from 1,973 reports) is large and expensive to
  rebuild; accidental overwrites invalidate benchmark comparisons.

## 9. Statement-Type Classification Is Title-Rule First, LLM Fallback Second

Decision (`modules/data/preprocessing/statement_type_classifier.py`):

- For the ~2,600 rows `tables_metadata_v2.jsonl` leaves `statement_type == "unknown"`, first try
  an exact-substring match against the statement's own printed Vietnamese title
  (`TITLE_RULES`); only fall back to an LLM call (structured Pydantic output) for rows the title
  rule can't place.
- Write a *patch* file (`artifacts/audits/statement_type_reclassified.jsonl`) keyed by
  `csv_path`, not an in-place rewrite of the protected metadata file. Merging back into
  `tables_metadata_v2.jsonl` is a deliberate, separate step after reviewing the patch.

Rationale: grounded against the real corpus before writing anything — none of the "unknown" rows
carry a `mau_tag` (so the Thông tư 200 form-code regex that classifies the other 97% has zero
yield here), and only ~6% have their own title text sitting in the OCR context. The rest need
semantic judgment a deterministic rule can't provide.

## 10. Raw CSVs Stay The Authority For Detail Tables

Decision:

- Do not try to make `long_format.parquet` the universal representation for codegen. Keep it as
  a narrow main-statement fact layer.
- For Type 2-5 style arithmetic over notes, bank layouts, entity tables, movement tables, or
  tables without stable `ma_so`, build a raw-table linking layer over the existing CSVs instead
  of a full corpus-wide long-format rewrite.
- Partition linking first by structural scope already present in metadata: ticker, year,
  `doc_type`, table id, headers, note/section title, row labels, and unit. Do not partition by
  company-specific business semantics unless measurements show a repeatable family that needs a
  dedicated adapter.
- Use domain adapters only when the table family has stable layout semantics that Python can
  validate, for example VAS main statements, bank note tables, securities-company note tables, or
  movement/reconciliation tables. The adapter boundary is table shape/domain, not ticker.
- Keep LLM output bounded with Pydantic schemas. The LLM may propose search phrases or candidate
  ids from real snippets; Python owns expansion gates, candidate validation, arithmetic, and unit
  conversion.
- For raw-table selection questions, keep the current branch bounded to real cell candidates and
  typed group candidates. Component-row groups are acceptable only when Python can build one
  deterministic group per slot from real cells. If a semantic search plan says the target should
  be built from component rows and the groups are missing or ambiguous, fail closed instead of
  letting a one-shot planner substitute a broad total row or nearby table family.
- For movement/payable wording such as `phát sinh trong năm` or `phải nộp trong năm`, treat the
  flow column as a structural signal. Boost `Phát sinh trong năm` and penalize balance columns;
  then raw selection may rank the top flow candidate per slot only when every slot has a clear
  flow cell with compatible units.

Rationale:

- Most hard Type 2-5 failures are not caused by the model being unable to do arithmetic; they are
  caused by choosing the wrong row/table among similar raw tables. A linking layer attacks that
  bottleneck directly while keeping raw CSV values as the source of truth.
- A full normalized table for every note family would become a large ETL project with brittle OCR
  assumptions. It should be introduced only for a measured, high-volume, stable family.
- Company-level adapters do not scale: they encode issuer quirks and are hard to validate across
  the corpus. Metadata scope plus row/header/note linking is more general, and domain adapters can
  still be added later where table layouts genuinely converge.

Prompt/context budget:

- Do not send whole raw reports or unbounded table text to the linker LLM. Use compact linking
  context: title/header/page hints plus a ranked sample of row labels.
- The current raw linker truncates candidate `table_context` before prompt rendering and limits
  table snippets per slot. These limits are deliberate budget controls, not semantic rules.
- If truncation hides needed evidence, fix the snippet builder by ranking/selecting better labels
  or adding a typed metadata field, not by raising context limits globally.
