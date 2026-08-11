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

## 10. Report Scope Backstop in `understand`

Decision:

- `understand` promotes `doc_type` from `unknown` to `separate` when the question
  names the separate/parent-only scope in so many words
  (`công ty|ngân hàng|tổng công ty mẹ`, `BCTC|báo cáo tài chính|báo cáo riêng`,
  `riêng lẻ`) and does *not* also say `hợp nhất`.
- The rule is one-directional: it only fills `unknown`, never overrides a scope
  the LLM committed to.
- A question naming both scopes is left `unknown` on purpose.

Rationale:

- Scope is not cosmetic. Across the ~97k (ticker, year, mã số, period) cells that
  carry both scopes, consolidated and separate differ by >1% in 82% of cases
  (median relative difference: BS 33%, IS 41%, CF 44%). Picking the wrong one is
  a wrong answer, not a formatting variant.
- The 8B returned `unknown` for six questions that state the scope outright
  (#780, #783, #790, #795, #798, #890). The shortlist filter then applied its
  unknown-means-consolidated default and all six submitted 100% consolidated
  tables. After the backstop all six submit 100% separate tables.
- Measured over all 1012 visible questions: the pattern matches 369, of which 363
  are exactly the questions the LLM already labelled `separate` (no-ops), 0
  conflict with an explicit `consolidated`, and 0 LLM-`separate` questions are
  missed. The 6 promotions are the entire behaviour change, and none of the 15
  gold-scored questions is among them -- the filter's input for the scored set is
  provably unchanged, so this cannot move the F2 baseline either way.
- This is the same rule-before-LLM pattern already used in the same module for
  tickers, and for the same reason: an explicit surface marker has an
  authoritative reading, and the 8B is unreliable on it.

Scope and known limits:

- Reading a stated marker is not semantic inference, so this does not conflict
  with the no-hardcoding principle in `docs/HANDOFF.md`. It carries no question
  ids and no answer-specific constants.
- The pattern was fitted on the visible 1012. A private-test question phrasing
  the scope differently simply falls back to today's behaviour -- no lift, no
  regression.
- `doc_type` is one field per question, so per-year scope (#952: "báo cáo công ty
  mẹ các năm 2022, 2023 và báo cáo hợp nhất các năm 2024, 2025") is not
  expressible. That question is deliberately left `unknown`; fixing it properly
  needs a per-(ticker, year) scope, not a wider regex.
- Correct scope is necessary, not sufficient. Hand-checked against the source
  reports, the six now retrieve the right documents but only #798 lands near the
  true value (67.56 tỷ true vs 68.39 tỷ produced, against 31,098 tỷ before);
  #795 and #890 still answer wrongly for unrelated reasons (line selection and
  answer shape). The remaining error is downstream of retrieval.

## 11. One Answer Flow: the Graph

Until now the repo carried two drivers that both produced a full 1012-question
run, and they disagreed:

| | Flow A (legacy) | Flow B (active) |
|---|---|---|
| driver | `scripts/run_pipeline.py` | `scripts/run_graph.py` |
| question metadata | frozen `questions_enriched.jsonl` | live `understand` (LLM, Pydantic) |
| retrieval | frozen table ids | live `modules.rag.service` |
| codegen | `generate(use_planner=True, fallback=True)` | same generator, plus formula/REPL branches |

Decision:

- The graph is the only flow that answers questions. `run_pipeline.py` and the
  batch driver in `pipelines/submission.py` are legacy for answering.
- `pipelines.submission.submission_item` stays: it is the shared *packaging*
  function, and `run_graph.py` imports it. Packaging was never the duplicated
  part.
- Anything that must hold for a submission (scope backstop, unit handling,
  repair policy) is implemented on the graph path, not in the legacy driver.

Rationale:

- Two drivers means two behaviours for the same question and no single number to
  improve. The scope backstop from section 10 lives in `understand`, which only
  the graph calls, so the legacy driver could not have benefited from it at all.
- Head-to-head on the 15 gold-scored questions: Flow A 9/15, Flow B 8/15, union
  11/15, with non-overlapping failures. The near-tie is the point -- Flow B is
  not behind on analysis. Flow B uniquely wins #363 (formula branch: 3.319357 vs
  Flow A's 0.0) and #752 (correct sign).
- **Correction, measured on the full 1012 run.** An earlier draft of this section
  claimed Flow B's three unique losses (#55, #818, #820) were all unit/scale
  errors. On the graph path they are not: #55's ratio to gold is 2.0, #818
  returns 0.0, #820's is 5.2e-9 -- none is a power of ten. Of the 34
  gold-scored questions in `artifacts/runs/graph_1012.jsonl`, exactly one (#524,
  ratio 1e9) is a clean scale error. The unit gap in section 12 is a real
  plumbing defect and worth fixing, but it buys ~1-3 of 34, not three
  named questions. See `docs/HANDOFF.md` for the per-question table.

Known limits:

- 93% of graph runs still route through `lookup` into the same `generate()` that
  Flow A used. The graph is not a different code generator; it is the same
  generator plus live understand/retrieve plus a formula/REPL escape. Expect
  most answer-quality work to land inside `modules/codegen/`, not in the graph.
- The graph swallows solver errors and reroutes to REPL, so `status` is now
  always `ok` in run records. The usable failure signal is `answer == 0.0`.

## 12. `unit_hint` Must Reach Codegen on Every Path

Decision:

- `unit_hint` produced by `understand` is authoritative and must be passed to
  every solver, including `lookup`.

Current state (the defect, not yet fixed):

- `formula_solver` and `repl_solver` both pass `unit_hint=state.get("unit_hint")`.
  `lookup_solver` (`agents/finance/solvers/lookup.py`) does not.
- `generate()` in `modules/codegen/generator.py` has no `unit_hint` parameter at
  all -- zero occurrences of the name in the file. On the lookup path the unit is
  re-derived from raw question text inside codegen, discarding what `understand`
  already decided.
- This contradicts the constraint already stated in `docs/HANDOFF.md` ("keep
  `unit_hint` from `understand` authoritative"). The constraint holds on the
  formula path and silently does not hold on the lookup path, which is 93% of
  traffic.
