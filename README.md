# ViFinQA Stage 2

Pipeline for retrieving financial-statement tables, planning a validated symbolic
calculation, compiling it to pandas, and executing the result.

For the current implementation status, operational cautions, and the recommended
next work, read [`docs/HANDOFF.md`](docs/HANDOFF.md).

## Current status

- The derived corpus contains 146,246 tables from 1,973 OCR files and 1,012
  enriched questions.
- The planner's ground-truth-table regression set is 15/15 correct, with all 15
  answers produced by the symbolic planner and no direct-code fallback.
- Retrieval and planning work independently, but there is no production runner
  connecting retrieved tables to the planner and submission packaging.
- The best measured retrieval candidate policy is still partly implemented in
  diagnostic scripts. See the handoff before treating a retrieval score as the
  behavior of `evaluate_retrieval.py`.

## Repository layout

```text
src/finance_qa/       importable application code
  preprocessing/     question and table metadata construction
  retrieval/         hard filter, BM25, dense retrieval, LLM judge
  planning/          symbolic IR, validation, pandas compilation
  execution/         DataFrame normalization and safe query execution
  evaluation/        reusable evaluation metrics and runners
scripts/              command-line entrypoints and diagnostics
tests/                deterministic tests that do not call the LLM
data/                 tables, metadata, indexes, and curated eval data
artifacts/            generated reports and run outputs
output/               final submission artifacts only
docs/                 current handoff plus design and audit records
```

All filesystem defaults are defined in
`src/finance_qa/paths.py`. Library modules must not hardcode a checkout path.

## Main flow

```text
question metadata
  → hard filter
  → BM25 + dense retrieval
  → LLM table judge
  → load and normalize selected DataFrames
  → LLM symbolic planner
  → deterministic contracts and compiler
  → execute pandas query
  → answer + evidence
```

Retrieval and query generation are independently testable. Query-generation
evaluation can use ground-truth tables to separate planner errors from retrieval
errors. A single production batch entrypoint connecting both stages is not yet
implemented.

## Common commands

Use the repository's `.venv_bge` environment:

```bash
.venv_bge/bin/python scripts/enrich_questions.py
.venv_bge/bin/python scripts/build_evalset.py
.venv_bge/bin/python scripts/build_doc_text.py
.venv_bge/bin/python scripts/build_dense_index.py
.venv_bge/bin/python scripts/evaluate_retrieval.py --stage rrf
.venv_bge/bin/python scripts/viewer.py --port 8080
```

`build_dense_index.py` and retrieval stages using dense vectors require the GPU
environment. `--stage filter` and `--stage bm25` do not run the encoder.
The extraction-only commands `extract_tables.py` and
`table_numbering_audit.py` additionally require `beautifulsoup4`; that package
is not installed in `.venv_bge`.

### Corpus extraction warning

`scripts/extract_tables.py` has no command-line options, dry-run, or `--help`
mode. Running it immediately regenerates all table CSVs and overwrites
`data/metadata/tables_index.jsonl` plus the extraction reports. Do not run it as
a smoke test. The checked-in `tables_metadata_v2.jsonl` also depends on a v1
metadata file that is not present in this workspace, so extraction is not yet a
complete reproducible rebuild path. Details and recovery checks are in the
handoff.

## Tests

```bash
.venv_bge/bin/python tests/test_planning_ir.py
.venv_bge/bin/python tests/test_generation.py
.venv_bge/bin/python tests/test_query_execution.py
.venv_bge/bin/python tests/test_planner_evaluation.py
```

The tests cover numeric normalization, structural header repair, plan validation,
formula compilation, unit contracts, canonical financial concepts, period
alignment, state-preserving plan repair, cross-frame comparative-period recovery,
company subtraction order, and rejection of incomplete multi-period shortcuts.

Query-planner quality is measured separately from retrieval by supplying the
curated ground-truth tables:

```bash
# Inspect the 15 labeled cases without calling the model
.venv_bge/bin/python scripts/evaluate_planner.py --list

# Run all cases; results are streamed to artifacts/runs as JSONL
.venv_bge/bin/python scripts/evaluate_planner.py

# Run or resume a smaller diagnostic slice
.venv_bge/bin/python scripts/evaluate_planner.py --ids 1,752,363 \
  --output artifacts/runs/planner_smoke.jsonl --resume
```

Numeric labels and tolerances live only in
`data/eval/planner_answers.json`; production planning code does not read them.
Each run also writes a neighboring `.summary.json` with overall, per-level,
planner, and fallback metrics.

The current verified ground-truth-table run is stored in
`artifacts/runs/planner_gt15_after_fixes.jsonl`: 15/15 answers are correct and
all 15 use the symbolic planner (no direct-code fallback). The run took 93.2
seconds in total on the configured local endpoint. This small curated set is a
regression benchmark, not an estimate of accuracy over all 1,012 questions.

## Current limitations

- `scripts/evaluate_retrieval.py` does not yet share the final candidate-pool
  construction used by `scripts/dump_pools.py`: entity/year query stripping,
  unconditional primary-statement expansion, and `judge_text` must be moved into
  reusable application code before the best experiment is the default pipeline.
- A full metadata rebuild is blocked by the absent
  `data/metadata/tables_metadata.jsonl` v1 input.
- Planner repair preserves the last validated structure and can recover missing
  prior-year bindings when a unique comparative column exists; unseen L6 shapes
  may still require a decomposed multi-stage planner.
- Multi-row OCR headers are normalized only when their span structure can be
  inferred unambiguously. Other malformed OCR tables fail validation rather than
  being guessed.
- Direct-code fallback remains available while planner coverage is measured.
- Planner benchmark results depend on the configured local LLM endpoint and are
  therefore stored as run artifacts rather than checked into production code.

## Documentation map

- [`docs/HANDOFF.md`](docs/HANDOFF.md): current source of truth for continuing
  the work.
- [`docs/v0_retrieval_pipeline.md`](docs/v0_retrieval_pipeline.md): retrieval
  experiment record and root-cause analysis; some winning variants are not yet
  wired into the main evaluator.
- [`docs/metadata_audit.md`](docs/metadata_audit.md): metadata quality audit and
  deferred schema ideas.
- [`brainstorming/v0_pipeline_design.md`](brainstorming/v0_pipeline_design.md):
  early design notes, retained as history rather than current behavior.
