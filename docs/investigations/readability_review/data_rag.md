# Readability review: data layer + RAG

Scope: `modules/data/{table_store,service,repositories}.py`,
`modules/data/preprocessing/*.py`, `modules/rag/{candidates,deepinfra_client,
judge,service}.py`, `modules/rag/indexing/*.py`, `modules/rag/rerankers/*.py`,
`modules/rag/retrievers/*.py`.

Per review scope, the long "why" comments (measured tradeoffs, question-id
specific bug histories) are not flagged — that convention is deliberate,
valuable, and consistently well-maintained here. Findings below are about
structure, naming, and duplication.

1. **`modules/data/repositories.py:10` (`TableRepository` Protocol) is dead /
   duplicated abstraction** — Nothing in the codebase imports or type-hints
   against `TableRepository`; `table_store.py:21`'s `CsvTableStore`
   implements the same three methods (`load_frame`, `source_csv`,
   `submission_csv_name`) but never references the protocol, and
   `service.py:8` calls the module-level `load_frame` function directly,
   bypassing both. A new engineer will reasonably assume `repositories.py` is
   the interface `table_store.py` implements and be confused when nothing
   wires them together. Either delete the protocol or have `CsvTableStore`
   declare it explicitly (and reference it from a call site).

2. **`modules/data/preprocessing/` mixes pipeline-wired modules with orphaned
   standalone scripts, with no structural signal distinguishing them** —
   `data_pipeline.py` (the orchestrator) only ever imports
   `document_text.py`, `extract_tables.py`, `long_format.py`, `questions.py`.
   `metadata_enrichment.py`, `metadata_v3.py`, and
   `statement_type_classifier.py` each have their own `main()`/CLI script
   under `scripts/` but are not reachable from the pipeline; `grid.py` and
   `header_flatten.py` exist solely as private library code for
   `metadata_v3.py`. This is documented individually in each file's
   docstring (good), but there's no directory-level signal telling a new
   engineer "these 5 files are one-off/offline, not part of the live
   pipeline." Consider a subfolder split (e.g. `preprocessing/offline/`) or a
   one-paragraph index comment.

3. **`metadata_v3.py` — the "v3" name is a false-cognate with this repo's
   real versioned-artifact convention.** The module docstring
   (`metadata_v3.py:1-13`) is explicit that this is "a staging artifact for
   the experiment... does not touch tables_metadata_v2.jsonl," i.e. an
   unmerged, non-authoritative rebuild — not a successor to the
   `metadata_enrichment.py` that produces the live `tables_metadata_v2.jsonl`.
   Because the codebase's actual data artifacts genuinely are versioned
   (`_v1`, `_v2`), a reader who doesn't stop to read the docstring will
   assume `v3` supersedes `v2` in production. Recommend renaming the module
   (e.g. `header_unit_experiment.py`) to decouple it from that naming
   convention, even though the file's own content is fine and clearly
   explained.

4. **`modules/rag/candidates.py:194-299`** — `CandidateRetriever.__init__` is
   a ~105-line constructor doing five distinct things inline: backend-name
   validation, name-index construction, one shared parquet read with
   conditional column selection, BM25 construction, and dense-index
   loading/shape-checking. Each block is individually well-commented, but for
   onboarding it reads as one large procedure rather than a sequence of named
   steps. Suggest extracting 2-3 private helpers (e.g.
   `_load_texts_and_index(...)`, `_load_dense_backend(...)`) with the same
   bodies, purely to make the constructor's top-level shape scannable.

5. **Duplicated "primary statement" concept, defined twice with different
   names** — `candidates.py:69-71` defines `PRIMARY_STATEMENT_TYPES` and
   `add_primary_statements()` (`candidates.py:120-137`); `rag/service.py:15`
   independently defines `_PRIMARY` (identical four-value frozenset) and
   `_evidence()` (`service.py:82-90`), which re-implements the same "append
   primary-statement tables not already selected" logic for a different
   stage (final evidence list vs. pool assembly). If the definition of
   "primary statement" ever changes, it must be remembered in two files with
   two names. Recommend consolidating into one shared constant/helper that
   both call sites use.

6. **`modules/rag/indexing/bm25.py:94` and
   `modules/rag/retrievers/filters.py:58`** — both use `Path` as a parameter
   type annotation (`path: Path = PARQUET_PATH` / `path: Path = METADATA_PATH`)
   without importing `pathlib.Path`. This only "works" because
   `from __future__ import annotations` postpones evaluation; a reader, a
   docstring-extraction tool, or `typing.get_type_hints()` would hit a
   `NameError`. Small but worth a one-line import fix in both files.

7. **Recurring stats/report-generation duplication across four preprocessing
   builders** — `extract_tables.py:172` (`write_stats_md`, ~60 lines),
   `metadata_enrichment.py:368` (`write_stats`, ~50 lines),
   `long_format.py:159` (`write_stats`, ~25 lines), and
   `questions.py:298-380` (`render_stats`/`render_counter_table`/`render_bar`,
   ~80 lines) each hand-roll their own markdown/HTML report generation
   embedded directly in the "build the artifact" class. No shared helper
   exists for the common pattern (percentile/percentage formatting,
   counter-to-table rendering). Not exact code duplication but a repeated
   structural pattern that bloats four otherwise-focused classes; a small
   shared `reports.py` utility (counter-to-markdown-table, percentile helper)
   would shrink each builder to its actual transform logic.

8. **Two sibling files both literally named `deepinfra.py`** —
   `modules/rag/indexing/deepinfra.py` (embedding backend) and
   `modules/rag/rerankers/deepinfra.py` (reranker backend). The
   backend/registry design justifies the split (confirmed by
   `retrievers/clients.py:76-101`'s lazy-import registry), so this is not a
   correctness issue, but it is a real "which `deepinfra.py` am I in"
   friction point for a new engineer navigating by filename/tab title. A
   one-line docstring cross-reference in each ("see also
   `rerankers/deepinfra.py` for the reranker backend") would remove the
   ambiguity cheaply.

9. **`modules/data/preprocessing/statement_type_classifier.py`** — not
   imported anywhere except its own script entry point (confirmed via grep),
   and it duplicates the `StatementType` literal / label vocabulary that
   also appears (differently, as `STATEMENT_LABELS`) in
   `document_text.py:56-62`. Not wrong, but worth flagging alongside item 2/3
   as another "offline experiment living in the main package tree" case, and
   a second place a reader must go to find the full list of statement-type
   labels.

## Overall impression

The code itself is unusually well-reasoned for a competition codebase — the
tradeoff comments are genuinely load-bearing (they cite exact measured
deltas and question ids), naming inside functions is clear, and most modules
have a single, well-stated responsibility. The maintainability risk here
isn't logic complexity, it's package-level legibility: `preprocessing/`
silently contains both the modules that actually run in production
(`document_text.py`, `extract_tables.py`, `long_format.py`, `questions.py`,
wired through `data_pipeline.py`) and several standalone/experimental
scripts (`metadata_enrichment.py`, `metadata_v3.py`,
`statement_type_classifier.py`, plus their private helpers `grid.py`/
`header_flatten.py`) with no structural marker distinguishing the two
groups — and `metadata_v3.py`'s name actively suggests the wrong thing to a
reader pattern-matching on this repo's real `_v1`/`_v2` data-versioning
convention.

**If only one change could be made:** give the offline/experimental
preprocessing scripts a distinct home (subfolder or clearly marked section)
and rename `metadata_v3.py` away from the versioned-artifact naming pattern
(items 2/3) — this is the single change most likely to save a new engineer
from mis-reading "which code actually runs" during onboarding.
