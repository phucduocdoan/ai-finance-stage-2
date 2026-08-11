# Decisions - ViFinQA Stage 2

This file records current engineering decisions. Historical experiment logs have been
collapsed into the current-state docs so old paths and stale conclusions do not act as
implementation guidance.

## 1. Code Organization

The repository is organized by capability modules and pipeline composition:

```text
core      -> shared config, LLM client, paths, types
modules   -> data, rag, codegen, tools
pipelines -> compose module services into workflows
agents    -> domain-facing agent APIs and solver nodes
```

Decision:

- Keep module internals behind `service.py` when another module or pipeline calls them.
- Keep cross-module orchestration in `pipelines/`, not in `modules/`.
- Keep agent state/router/solver code under `agents/finance/`.
- Keep future database/storage work behind `modules.data.repositories.TableRepository`.

Rationale:

- Modules stay reusable and testable.
- Pipelines can change without forcing storage/RAG/codegen internals to import each other.
- A future DB backend can replace file-backed table loading through the data service boundary.

## 2. Supported Import Paths

Supported public surfaces:

```python
finance_qa.agents
finance_qa.agents.finance
finance_qa.pipelines.finance_qa
finance_qa.pipelines.submission
finance_qa.modules.data.service
finance_qa.modules.rag.service
finance_qa.modules.codegen.service
finance_qa.core.paths
finance_qa.core.llm
```

Removed import paths are not compatibility targets:

```text
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

Active implementation: `src/finance_qa/modules/rag/candidates.py`.

Decision:

- Use deterministic filters for ticker/year/doc_type before semantic retrieval.
- Use BM25 and dense retrieval as candidate sources.
- Keep primary-statement expansion in the pool so balance sheet, income statement,
  cash flow, and equity-change tables remain reachable.
- Let the LLM judge select final evidence tables from the pool.
- Configure graph retrieval through `FinanceAgentConfig` and `modules.rag.service`.

Rationale:

- Report-tier retrieval is structurally constrained by metadata.
- The hard part is selecting the correct table inside a known report.
- Primary statement tables are sparse enough to include directly and important enough
  that missing them is expensive.

Current graph defaults:

```python
reranker = "qwen3-0.6b"
judge_top_n = 20
frozen_fallback = True
```

## 4. Solving Strategy

The graph uses three solver routes:

| Route | Solver | Purpose |
|---|---|---|
| lookup + single cell | `agents.finance.solvers.lookup` -> `modules.codegen.service.generate_lookup_solution` | Simple cell extraction through planner/codegen. |
| formula/compare/multi-step | `agents.finance.solvers.formula` -> `modules.codegen.service.generate_formula_solution` | Canonical finance facts plus structured Pydantic planning. |
| fallback/other | `agents.finance.solvers.repl` -> `modules.codegen.service.generate_repl_solution` | General pandas tool loop. |

Decision:

- Use deterministic sources for facts with clear authority: ticker mapping, statement code mapping,
  canonical metric extraction, unit conversion, and arithmetic execution.
- Use LLMs for intent, operation choice, and disambiguation.
- Prefer Pydantic structured output over regex parsing for model-produced intent and plans.
- Keep free-form Python as fallback until typed REPL operations cover enough cases.

Rationale:

- Hardcoded answer paths do not generalize.
- Letting the model emit typed intent while Python executes facts gives better invariants.
- REPL is broad but expensive and unstable; it should become an orchestrator over typed tools.

## 5. Codegen And Formula Solvers

Lookup/simple-cell codegen uses a Pydantic `OperationPlan` from
`src/finance_qa/modules/codegen/ir.py`; existing deterministic repairs, validators,
and compiler still own row/column/unit/code execution after the model emits the plan.

### Formula Solver

Active implementation: `src/finance_qa/modules/codegen/formula.py` plus
`src/finance_qa/modules/tools/metrics.py`. The graph solver file is an adapter.

Decision:

- The model emits a Pydantic `CanonicalPlan`.
- Python validates metric/filter/select/answer invariants.
- Canonical rows execute deterministically.
- `formula_thinking=True` and `formula_max_tokens=8192` are graph defaults.

Rationale:

- Thinking-mode calls can exceed 2048 tokens before producing the final answer.
- Pydantic structured output avoids brittle extraction of operation variables from text.
- Canonical execution keeps arithmetic and unit conversion outside model free-form text.

Known audit items:

- Q415: question says final/current-year ratio after selecting the year with max revenue; the local
  computation disagrees with `extended_gold.jsonl`.
- Q439: question asks ROE, while the label artifact describes a D/E style answer.

## 6. REPL Direction

Decision:

- Keep `run_code` REPL as an escape hatch.
- Build typed REPL operations incrementally: `get_metric`, `find_row`, `compute`, `convert_unit`,
  then filters/ranking.
- Return structured repair errors instead of raw traceback-only loops.

Rationale:

- The current REPL sees code output/errors and can recover from some planner failures.
- It still burns context on schemas and asks the model to solve labels, formulas, units, and control
  flow at the same time.
- Typed operations preserve REPL flexibility while moving data access and arithmetic into deterministic code.

See `docs/REPL_REDESIGN.md`.

## 7. Submission Pipeline

Active implementation: `src/finance_qa/pipelines/submission.py`.

Decision:

- `scripts/run_pipeline.py` is a thin CLI wrapper over `finance_qa.pipelines.submission`.
- Runs are append-only JSONL with last-record-wins resume behavior.
- Per-question failures are recorded as data; a failed question does not stop the batch.
- `scripts/build_submission.py` packages a run JSONL into `output/submission.zip`.

Rationale:

- Leaderboard submissions require all question ids to be present.
- Retrieval tables and evidence CSVs must be packaged consistently with the item schema.
- Append-only runs make long shared-GPU/LLM jobs recoverable.

## 8. Data Snapshot

Decision:

- Treat `tables_metadata_v2.jsonl`, `tables_doc_text.parquet`, and `tables_dense.npy` as protected artifacts.
- Rebuilds go through staging paths.
- `scripts/extract_tables.py` is not a diagnostic command.

Rationale:

- The current metadata/index snapshot is large and expensive to rebuild.
- Accidental extraction/index overwrites can invalidate benchmark comparisons.

## 9. Import-Only Cleanup

Decision:

- Keep package facades that are real public API.
- Remove import-only files that only preserve stale paths once call sites are migrated.
- Keep corpus-build and reranker implementation in `src/finance_qa/modules/*`;
  `scripts/` should remain thin CLI wrappers or experiments.

Current classification is documented in `docs/HANDOFF.md`.
