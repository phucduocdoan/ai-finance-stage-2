# End-to-End Pipeline

This document describes the current batch runner and packaging workflow.

## Runner

Entrypoint:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/run_pipeline.py --output artifacts/runs/pipeline.jsonl
```

Implementation:

```text
scripts/run_pipeline.py
  -> finance_qa.pipelines.submission.main
```

Runtime flow:

```text
questions_enriched.jsonl
  -> CandidateRetriever.build_pools
  -> CandidateRetriever.select
  -> modules.codegen.generator.generate
  -> submission_item
  -> modules.tools.python_exec.validate
  -> JSONL record
```

## Runner Properties

- Per-question failures are recorded and the batch continues.
- Resume is append-only; the last JSONL record for an id wins.
- `--retry-failed` re-runs ids whose last record is not `ok`.
- GPU query encoding is batched by chunk.
- LLM calls run with bounded worker concurrency.

Useful flags:

```bash
--ids 1,17,40
--limit 20
--resume
--retry-failed
--workers 4
--chunk 32
--max-tables 10
--no-judge-thinking
--thinking
--no-fallback
--no-planner
--dense-backend bge-m3
--reranker qwen3-0.6b
--judge-top-n 20
--list
```

## Graph Runner

Graph runs use a separate driver:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --ids 371 --out artifacts/runs/graph_q371.jsonl
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --measure --out artifacts/runs/graph_measure.jsonl
PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --all --out artifacts/runs/graph_1012.jsonl
```

`scripts/run_graph.py` calls `finance_qa.agents.finance.graph.run_question` and writes records
that can be packaged by `scripts/build_submission.py`.

## Packaging

Package a JSONL run:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py \
  --run artifacts/runs/pipeline.jsonl \
  --out output/submission
```

Partial packaging for tests:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py \
  --run artifacts/runs/pilot.jsonl \
  --out output/pilot_submission \
  --only-run-ids
```

The packager writes:

```text
output/submission/
  submission.json
  data/*.csv
output/submission.zip
```

It validates the leaderboard schema, keeps all expected question ids for full submissions,
ships normalized CSVs for referenced tables, and converts submitted table positions to the
organizer's 0-indexed convention.
