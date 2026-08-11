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

## Next Work

1. Remove or merge import-only compatibility files that are not public API.
2. Run a clean full gold20 graph benchmark through `scripts/run_graph.py`.
3. Add typed REPL operations for `get_metric`, `find_row`, `compute`, and `convert_unit`.
4. Add abstain/diagnostic behavior when canonical data is missing or magnitudes are implausible.
5. Keep DB/storage work behind `modules.data.repositories.TableRepository` rather than leaking storage details into RAG or agents.
