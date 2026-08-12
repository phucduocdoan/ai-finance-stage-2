# Handoff - ViFinQA Stage 2

This is the current operating map for the repo. Source code is the source of truth when
any note here disagrees — in particular, docstrings in `agents/finance/graph.py` and
`modules/solve/*.py` carry the measured numbers behind each design choice and are more
detailed than this file.

## Active Architecture

The graph is the only answer flow, for both interactive (`run_question`) and batch
(`scripts/run_graph.py`) use. There is no router and no per-question solver choice — every
question takes the same five nodes:

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
| OCR TXT/HTML -> raw CSVs | `modules.data.preprocessing.extract_tables.TableExtractor` | `scripts/extract_tables.py` |
| raw questions -> enriched metadata | `modules.data.preprocessing.questions.QuestionEnricher` | `scripts/enrich_questions.py` |
| metadata -> retrieval text parquet | `modules.data.preprocessing.document_text.DocumentTextBuilder` | `scripts/build_doc_text.py` |
| table metadata/CSV -> long format | `modules.data.preprocessing.long_format.LongFormatBuilder` | `scripts/build_long_format.py` |
| retrieval text -> local dense index | `modules.rag.indexing.dense.DenseIndexBuilder` | `scripts/build_dense_index.py` |
| retrieval text -> hosted dense index (paid) | `modules.rag.indexing.deepinfra_build.DeepInfraIndexBuilder` | `scripts/build_deepinfra_index.py` |
| `statement_type=="unknown"` rows -> reclassification patch | `modules.data.preprocessing.statement_type_classifier.StatementTypeClassifier` | `scripts/classify_statement_type.py` |

`src/finance_qa/pipelines/data_pipeline.py` (+ `scripts/build_data_pipeline.py`) chains the
required rebuild order (`enrich_questions -> build_doc_text -> build_dense_index`); the other
stages are explicit, off-by-default flags on that same CLI.

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
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --ids 371 --out artifacts/runs/smoke_q371.jsonl
```

## Current Benchmark State

The honest gold set is `data/eval/unbiased60_gold.jsonl` + `data/eval/manual15_gold.jsonl` (73
questions with confidence >= medium, disjoint from the 363-440 band the old architecture was
tuned against). Score any run or packaged submission against it with:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py --run solve=<run.jsonl> --right solve
```

The most recent recorded run of the current solve_qa graph
(`artifacts/runs/solve_gold75_verifyfull.jsonl`, from before this session's deletion/migration)
scores **37/73 (50.7%)** at 1% relative tolerance, against 29-30/73 (~40%) for the legacy
submission artifacts it replaced. This number predates the deletion/migration work landed in
this session — the migration only moved *where* the same graph code lives (`pipelines.finance_qa`
-> `agents.finance.graph` directly) and trimmed unused legacy files; it did not touch
`understand`/`retrieve`/`modules/solve/*`. A live smoke run (`--ids 371`) confirms the graph
still runs end-to-end post-migration, but **the 73-question set has not been re-scored against
the current on-disk code** — do that before treating 50.7% as the current number.

## Next Work

1. **Re-run the unbiased-73 gold set against current code** and confirm the 50.7% figure still
   holds post-migration before using it as a baseline for further changes.
2. **Run the statement-type classifier at full scale.** `scripts/classify_statement_type.py` has
   only been run on two ~10-row samples (`artifacts/audits/sample_title_only.jsonl`,
   `sample_with_llm.jsonl`) to check output shape. The real ~2,600-row "unknown" backlog has
   never been classified, and no patch has been reviewed or merged into
   `tables_metadata_v2.jsonl`.
3. **Error taxonomy on `generate_pandas` misses.** The biggest lever is still "the model reads
   the wrong cell" (verify_answer's own rationale: ~34/73 gold questions in the last full
   measurement). Categorize the current misses (wrong table vs wrong row vs wrong column vs
   wrong unit) before changing anything in `modules/solve/`.
4. **DeepInfra safety-guard gap in the orchestrator** (flagged by review, non-blocking): when
   `build_data_pipeline.py --with-deepinfra-index` runs with no `--limit`, it can start billing
   immediately with no confirmation prompt, because the orchestrator constructs
   `DeepInfraIndexBuildConfig(yes=True)` directly instead of surfacing the module's own guard.
5. **`docs/tables_metric_probes.md`** tracks a still-open, separate investigation: the
   leaderboard's `relevant_tables` scoring format. Read that file before spending another
   submission probing it — it records 11 already-spent attempts and what each ruled out.

## Standing Items

- Add typed operations for `get_metric`/`find_row`/`convert_unit` inside `modules/solve/` only
  if a measured failure shows the model needs them — the free-form-query design in section 4 of
  `docs/DECISIONS.md` was chosen over a typed-tool orchestrator (the abandoned direction is not
  documented here; see git history for `docs/REPL_REDESIGN.md` if picking this up again) because
  it measured better, not because typed tools are wrong in principle.
- `data/derived/long_format.parquet` has OCR/parse gaps (e.g. POW 2019 separate lost mã số 151
  because the label OCR'd as "Chỉ phí"). Not exercised by the current graph path, but relevant if
  anything starts reading it again.
- #790 fails to resolve BIDV (ticker resolution) — not reverified since the rewrite.
