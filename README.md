# ViFinQA Stage 2

Finance QA pipeline for selecting financial-statement tables, loading normalized
CSV evidence, solving numeric questions, and packaging leaderboard submissions.

For operational cautions, benchmark notes, and current next work, read
[`docs/HANDOFF.md`](docs/HANDOFF.md).

## Current Status

- Corpus snapshot: 146,246 tables from 1,973 OCR files and 1,012 enriched questions.
- Interactive and batch flows both run the same graph: `finance_qa.agents.finance.run_question`
  for one question, `scripts/run_graph.py` to drive it over many and write a submission-ready
  JSONL, packaged by `scripts/build_submission.py`.
- Core code is organized as modules and services. The graph's nodes and topology live in
  `agents.finance.graph`; pipelines compose that graph (or module service APIs) into a runnable
  job instead of importing implementation internals directly.
- Deterministic tests cover numeric normalization, header repair, retrieval candidate policy,
  and the solve_qa codegen/execute/verify units.

## Repository Layout

```text
src/finance_qa/
  core/                 config, LLM client, filesystem paths, shared types
  modules/
    data/               table loading, metadata, preprocessing
    rag/                candidate retrieval, indexes, retrievers, rerankers, judge
    solve/              grounded pandas codegen, execution/repair, verify
    tools/              DataFrame, numeric, execution utilities
  pipelines/            submission item shape + data pipeline orchestration
  agents/               finance agent state/understand/graph topology/public entrypoints
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
agents.finance.graph                     (nodes + topology, built by build_graph)
  -> agents.finance.understand           (LLM: tickers/years/metric/operation/...)
  -> modules.rag.service                 (retrieve: judge-selected tables)
  -> modules.solve.codegen               (LLM: one pandas expression)
  -> modules.solve.execute               (run + repair)
  -> modules.solve.verify                (check the cell read, rewrite once if wrong)
```

```text
scripts/run_graph.py
  -> agents.finance.graph.arun_question over many questions
  -> pipelines.submission.submission_item   (per-question JSON shape)
  -> writes a JSONL run

scripts/build_submission.py
  -> packages a JSONL run into output/submission.zip
```

## Common Commands

Use the repository's `.venv_bge` environment and set `PYTHONPATH=src`:

```bash
PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
PYTHONPATH=src .venv_bge/bin/python tests/test_query_execution.py
PYTHONPATH=src .venv_bge/bin/python tests/test_candidate_pool.py
PYTHONPATH=src .venv_bge/bin/python tests/test_solve_units.py
PYTHONPATH=src .venv_bge/bin/python tests/test_understand.py
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --ids 371 --out artifacts/runs/smoke_q371.jsonl
```

Dense retrieval and index rebuild commands require the GPU environment.
Corpus rebuild commands under `scripts/` are CLI wrappers over `src/finance_qa/modules/*`
services. `scripts/extract_tables.py` rewrites corpus artifacts and is not a smoke test.
