# P12 — scripts/ and docs/ reorg for submission clarity (2026-08-31)

Goal: BTC will read this repo as the product's full source code. The top level of
`scripts/` and `docs/` should show production pipeline code and current-state
architecture docs, not one-off investigation/debugging scripts and dated research
notes. Nothing was deleted — everything moved with `git mv` (history preserved) into
`scripts/dev/` or `docs/investigations/`.

## Final classification

**`scripts/` kept at top level (13 tracked + `_bootstrap.py`):**
`_bootstrap.py`, `build_data_pipeline.py`, `build_deepinfra_index.py`,
`build_dense_index.py`, `build_doc_text.py`, `build_long_format.py`,
`build_submission.py`, `classify_statement_type.py`, `enrich_questions.py`,
`evaluate_retrieval.py`, `extract_tables.py`, `run_graph.py`, `score_unbiased60.py`.

**`scripts/dev/` (65 files):** every `gate_*.py`, `probe_*.py`, `audit_*.py`,
`report_*.py`, `score_*.py`(except `score_unbiased60.py`), plus `compare_runs.py`,
`merge_runs.py`, `patch_sign_submission.py`, `percent_scale_replay.py`,
`rescale_below_floor.py`, `retry_pool.py`, `sweep_queue.sh`, `verify_long_format.py`,
`viewer.py`, `vote_arms.py`, `enrich_metadata_v2.py`, `classify_header_quality.py`,
`fill_from_arms.py`, `build_deepinfra_index.py`'s siblings (`build_dense_variant.py`,
`build_evalset.py`, `build_gold100_manifest.py`, `build_gold_candidates.py`,
`build_metadata_v3.py`), `eval_structured_planner.py`, plus a new
`scripts/dev/_bootstrap.py` (mirrors `scripts/_bootstrap.py`, one directory deeper,
so moved scripts that do `import _bootstrap` still resolve `src/`).
`scripts/dev/probe_selection_plans.py` was added directly (was untracked, never
committed).

Gitignored/untracked one-off scripts (`score_gold75.py`, `diag_*.py`,
`prototype_*.py`, `solve.py`, etc.) were deliberately left in place, untouched:
`git mv` doesn't apply to untracked files, moving them would silently un-ignore them
at the new path (`.gitignore` uses exact-path entries), and they never reach GitHub
regardless of where they sit.

**`docs/` kept at top level (9 files):** `DATA.md`, `DECISIONS.md`, `MODEL.md`,
`HANDOFF.md`, `artifact_manifest.md`, `config_flags.md`, `metadata_audit.md`,
`refactor_plan.md`, `tables_metric_probes.md`, plus `README.md` (repo root) and
`docs/competition/` (whole dir, BTC-provided, untouched).

**`docs/investigations/` (24 files + `feasibility/` and `readability_review/`
subdirs):** every dated `docs/*_2026-*.md` note, `CELL_LOCATOR_STATUS.md`,
`FORMULA_FACTS_STATUS.md`, `NEXT_AGENT_HANDOFF.md`, `SUBMISSION_EXECUTION_AUDIT.md`,
`v0_retrieval_pipeline.md`. Untracked files added directly (never committed before):
`docs/investigations/feasibility/`, `gold73_23fail_rca_2026-08-29.md`,
`regression_bisect_2026-08-30.md`, `readability_review/`.

## Reclassifications from the initial proposal

- **`build_metadata_v3.py` → MOVE** (was proposed KEEP). `offline/__init__.py`'s
  docstring says offline scripts are "run by hand," not wired into
  `data_pipeline.py`; `docs/DATA.md` explicitly calls `tables_metadata_v3.jsonl` an
  unneeded experimental variant.
- **`enrich_questions.py` → KEEP** (was proposed MOVE). It's the CLI wrapper for the
  `enrich_questions` stage in `data_pipeline.py`'s `DEFAULT_STAGES` — required for
  the live agent.
- **`build_deepinfra_index.py`, `evaluate_retrieval.py` → KEEP** (neither list
  mentioned them). Both are live-referenced from kept `src/` files
  (`candidates.py`, `evaluation/retrieval.py`) as the real CLI entry points for an
  optional pipeline stage and the retrieval eval harness.
- **`docs/HANDOFF.md` → KEEP** (was proposed MOVE). README.md, `DECISIONS.md`, and
  `refactor_plan.md` all point to it as "the current operating map."
- **`docs/metadata_audit.md` → KEEP** (was proposed MOVE). `docs/DATA.md` cites it
  live ("đầy đủ danh sách trong `docs/metadata_audit.md`") and it's non-dated,
  current-state content.
- **`docs/tables_metric_probes.md` → KEEP** (was proposed MOVE). `HANDOFF.md` item 8
  calls it "a still-open, separate investigation... read that file before spending
  another submission probing it" — an active operational pointer, not a closed
  citation, and the filename itself carries no date suffix.
- **`scripts/classify_statement_type.py` → KEEP** (was proposed MOVE, matched the
  `classify_*.py` pattern). `HANDOFF.md`'s pipeline-stage table lists it alongside
  the other genuine CLI wrappers (`extract_tables.py`, `build_doc_text.py`, etc.)
  with a named service owner, and item 5 frames running it at full scale as an open,
  unfinished task, not a finished experiment.
- **`scripts/score_clean_eval.py` → MOVE, reference patched instead of un-moved.**
  It matches the `score_*.py` pattern but is imported by `tests/test_score_comparators.py`.
  Un-moving it would cascade into un-moving ~25 dependent gate/score/probe scripts
  that import it or its siblings, defeating the declutter goal. Moved it with its
  whole dependent family and instead added a second `sys.path.insert(...,
  "scripts/dev")` to the two tests that import moved modules by bare name
  (`test_score_comparators.py`, `test_screening_compose.py` — the latter's
  `gate_screening_class` import was found broken by the full test run below and
  fixed the same way).

## Stale references fixed

All fixed by adding the `investigations/` or `dev/` path segment (no content
otherwise changed): `src/finance_qa/core/paths.py`,
`src/finance_qa/modules/data/preprocessing/document_text.py`,
`src/finance_qa/modules/data/preprocessing/offline/header_flatten.py`,
`src/finance_qa/modules/data/preprocessing/offline/metadata_header_unit_experiment.py`,
`src/finance_qa/modules/rag/candidates.py` (2 occurrences),
`src/finance_qa/modules/rag/indexing/bm25.py`,
`src/finance_qa/modules/rag/indexing/dense.py` (2 occurrences),
`src/finance_qa/modules/rag/judge.py`,
`src/finance_qa/modules/rag/retrievers/clients.py`,
`src/finance_qa/modules/rag/retrievers/filters.py`,
`src/finance_qa/modules/tools/dataframe.py`,
`src/finance_qa/modules/solve/common/screening.py`,
`src/finance_qa/modules/solve/codegen/execute.py` (2 lines, 3 script names),
`src/finance_qa/pipelines/data_pipeline.py`, `tests/test_dataframe_repair.py`,
`tests/test_score_comparators.py` (added `scripts/dev` to `sys.path`),
`tests/test_screening_compose.py` (added `scripts/dev` to `sys.path`),
`docs/artifact_manifest.md` (2 edits), `docs/config_flags.md` (5 edits).

**Left as pre-existing, out of scope:** `docs/HANDOFF.md`'s reference to
`docs/REPL_REDESIGN.md` — that file was deleted in an old refactor
(`08d5306 Replace planner/IR/REPL solver stack...`); `HANDOFF.md` explicitly points
at git history for it, so the reference was already dead before this reorg. Two
dated audit reports in `artifacts/audits/` (`solver_hardcode_and_linking_audit.md`,
`raw_linker_gold73_buckets.md`) cite old script/doc paths in their own historical
prose; `artifacts/` was out of scope for this reorg (only `scripts/` and `docs/`
were in scope) and these are dated snapshots of what was true when written, same
category as the `REPL_REDESIGN.md` case. Internal cross-references between moved
files themselves (a `scripts/dev/gate_*.py` docstring citing a sibling
`docs/investigations/*.md` by its old path, etc.) were also left as-is — rewriting
the prose of dozens of archived investigation files was excessive scope for a pure
directory move.

## Verification

- `PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests` — clean.
- `pytest tests/test_dataframe_repair.py tests/test_score_comparators.py` (the only
  two real pytest-style files in `tests/`) — 15 passed.
- All 29 script-style test files (`python tests/test_X.py`, the repo's actual
  convention — `check()` + `sys.exit`) run directly — all pass except
  `tests/test_query_execution.py`, which has 2 pre-existing failures
  ("khôi phục header hai tầng bị lệch", "số cuối kỳ nằm đúng cột semantic")
  unrelated to this reorg: the file is completely unmodified, and the failing
  checks load real report data (`FTS_financial_statements_2018|22`) through
  `load_frame`'s table-grid header reconstruction, a code path this reorg never
  touched.
- Running the full test run surfaced one real regression from the move
  (`tests/test_screening_compose.py`'s bare `from gate_screening_class import ...`),
  fixed as described above.

## Scope note: excluded from this commit

`git status` at commit time also showed `final_submission.md` (BTC's Mentor Day 3 /
submission-requirements message, pasted at the repo root, unreviewed and never
mentioned in this task's scope) and `sofier_AI_FINANCE_snapshot/` +
`sofier_work/` (6.2G combined, not gitignored). Neither was part of the scripts/docs
reorg or the pre-approved fixes, and blindly running `git add -A` would have staged
6+ GB of snapshot data and an unreviewed file into git history bound for GitHub.
Staged everything relevant with a targeted `git add` instead and left these three
untracked. Also left untracked, per `docs/artifact_manifest.md`'s own "Not covered
by this manifest" section (already documents these as deliberately uncommitted):
`artifacts/audits/gold73_23fail_detail.json`,
`artifacts/eval_clean/multiyear_failures.json`,
`artifacts/eval_clean/unit_blast.json`.

## Commit hashes

Filled in after commit — see the commit that introduces this file on
`phase5-poc-period-validate`, and `master` after the `--ff-only` merge in the same
step.
