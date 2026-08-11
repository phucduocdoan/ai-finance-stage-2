# ViFinQA Stage 2

Finance QA pipeline for selecting financial-statement tables, loading normalized
CSV evidence, solving numeric questions, and packaging leaderboard submissions.

For operational cautions, benchmark notes, and current next work, read
[`docs/HANDOFF.md`](docs/HANDOFF.md).

## Current Status

- Corpus snapshot: 146,246 tables from 1,973 OCR files and 1,012 enriched questions.
- Active interactive answer flow: `finance_qa.agents.finance.run_question`.
- Batch submission flow: `finance_qa.pipelines.submission`, exposed by `scripts/run_pipeline.py`
  and packaged by `scripts/build_submission.py`.
- Core code is organized as modules and services. Pipelines compose service APIs instead of
  importing implementation internals directly.
- Deterministic tests cover numeric normalization, header repair, codegen IR, generation
  repairs, retrieval candidate policy, submission packaging, and the canonical formula solver.

## Repository Layout

```text
src/finance_qa/
  core/                 config, LLM client, filesystem paths, shared types
  modules/
    data/               table loading, metadata, preprocessing, canonical data
    rag/                candidate retrieval, indexes, retrievers, rerankers, judge
    codegen/            service API, IR, generator, formula planner, REPL services
    tools/              DataFrame, numeric, execution, table, metric utilities
  pipelines/            graph and batch submission workflow composition
  agents/               finance agent state/router/solvers and public entrypoints
  evaluation/           reusable evaluation helpers
scripts/                command-line entrypoints and diagnostics
tests/                  deterministic script-style tests
data/                   tables, metadata, indexes, and curated eval data
artifacts/              generated reports and run outputs
output/                 final submission artifacts only
docs/                   current handoff, decisions, and design notes
```

Filesystem defaults live in `src/finance_qa/core/paths.py`.

## Main Flow

```text
agents.finance.graph
  -> pipelines.finance_qa
      -> modules.data.service
      -> modules.rag.service
      -> agents.finance.solvers
          -> modules.codegen.service
          -> modules.tools.*
```

The batch submission flow is separate:

```text
scripts/run_pipeline.py
  -> finance_qa.pipelines.submission
      -> modules.rag.candidates.CandidateRetriever
      -> modules.codegen.generator.generate
      -> modules.tools.python_exec.validate

scripts/build_submission.py
  -> packages a JSONL run into output/submission.zip
```

## Common Commands

Use the repository's `.venv_bge` environment and set `PYTHONPATH=src`:

```bash
PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
PYTHONPATH=src .venv_bge/bin/python tests/test_query_execution.py
PYTHONPATH=src .venv_bge/bin/python tests/test_planning_ir.py
PYTHONPATH=src .venv_bge/bin/python tests/test_generation.py
PYTHONPATH=src .venv_bge/bin/python tests/test_candidate_pool.py
PYTHONPATH=src .venv_bge/bin/python tests/test_pipeline_run.py
PYTHONPATH=src .venv_bge/bin/python tests/test_formula_deterministic.py
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --ids 371 --out artifacts/runs/smoke_q371.jsonl
```

Dense retrieval and index rebuild commands require the GPU environment.
Corpus rebuild commands under `scripts/` are CLI wrappers over `src/finance_qa/modules/*`
services. `scripts/extract_tables.py` rewrites corpus artifacts and is not a smoke test.
