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

## Setup

**Environment.** Use a dedicated virtualenv (`.venv_bge` in the commands below), not the base
conda env: the base env's `torch` build (cu130) cannot see the GPU against this machine's
CUDA-12.6 driver, and `torch`/`transformers` are what run the local bge-m3 dense embedder.

```bash
python3 -m venv .venv_bge
.venv_bge/bin/pip install -e .
# GPU acceleration matching the pinned torch version (optional -- falls back to CPU
# automatically if no CUDA device is visible, see modules/rag/indexing/dense.py):
.venv_bge/bin/pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
```

**Required inputs not in git** (see `.gitignore` — unrebuildable / too large for a repo):

- `ViFinQA/` — the raw dataset: `financial_statements/*_extracted.txt` (OCR text),
  `questions/questions.jsonl`, `code_stock.csv`. Must be placed at the repo root.
- `data/metadata/tables_metadata_v2.jsonl`, `data/indexes/tables_doc_text.parquet`,
  `data/indexes/tables_dense.npy` — protected derived artifacts (`docs/DECISIONS.md` section 8).
  The bge-m3 dense index cannot currently be rebuilt from scratch (its v1 metadata source no
  longer exists on disk), so these three must be copied in from a backup rather than regenerated.
- `data/eval/*.jsonl` (gold questions) — these ARE tracked in git (`!data/eval/` in
  `.gitignore`), nothing to provide.

**LLM backend.** Every node except `retrieve`'s BM25/dense scoring calls out to a chat model
over the OpenAI-compatible endpoint in `core/llm.py`. Point it at either:

```bash
# a local vLLM server serving Qwen3-8B-Instruct (defaults if unset):
export LLM_ENDPOINT=http://127.0.0.1:8990/v1/chat/completions
export LLM_MODEL=Qwen/Qwen3-8B-Instruct

# or a hosted backend (no local server needed):
export LLM_ENDPOINT=https://api.deepinfra.com/v1/openai/chat/completions
export LLM_MODEL=Qwen/Qwen3-14B
export LLM_API_KEY=$DEEPINFRA_API_KEY
```

## Reproducing A Run

With the inputs above in place:

```bash
# 1. (only if data/indexes/* are missing) rebuild derived data from the raw dataset:
PYTHONPATH=src .venv_bge/bin/python scripts/build_data_pipeline.py

# 2. run the graph over questions, writing one JSONL record per question:
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --all --out artifacts/runs/full_run.jsonl

# 3. score against the honest gold set (73 questions, see docs/HANDOFF.md):
PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py --run solve=artifacts/runs/full_run.jsonl --right solve

# 4. package a leaderboard submission:
PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py --run artifacts/runs/full_run.jsonl --out output/submission
```

`run_graph.py --ids <comma-separated ids>` runs a subset instead of `--all` (see Common Commands
below for a one-question smoke test).

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
