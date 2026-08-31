# P8 — Submission Deliverables Gap List

Deadline: 17h30, 2026-08-31 (Vietnam time). Source of requirements: `final_submission.md`
(read in full — Vietnamese, four parts: data doc, model doc, source code, README/guide).

This confirms and sharpens the initial quick pass: **no data-description doc, no
model/checkpoint doc, and no Drive/OneDrive link exist anywhere in the repo** (verified by
grep across the whole tree, excluding `sofier_*`/venvs/caches). One thing the quick pass
missed: `docs/competition/data_source.txt` already contains a complete, well-written
description of the *raw* BTC-provided dataset, including a public, already-shareable link
(`https://huggingface.co/datasets/AIGuruTinix/ViFinQA`). That materially de-risks item 1.

## Checklist

| # | Item | Status | Fastest close |
|---|---|---|---|
| 1 | Data description doc — raw dataset (source, structure, usage) | **have, needs repackaging** | `docs/competition/data_source.txt` (6.8K) already covers source, structure, format, and a public HF link. Copy/lightly adapt into `docs/DATA.md`, add one paragraph naming which files this repo actually reads (`ViFinQA/financial_statements/*_extracted.txt`, `questions/questions.jsonl`, `code_stock.csv`) and where they must be placed (repo root, per README). ~15 min. |
| 2 | Data description doc — derived artifacts (metadata/index) | **missing** | `data/metadata/tables_metadata_v2.jsonl` (628M) and `data/indexes/tables_doc_text.parquet` + `tables_dense.npy` (2.4G total) are the team's own derived data, not covered by the HF card. `docs/metadata_audit.md` already has the field list, sizes, and provenance notes — reuse it almost verbatim as a section in `docs/DATA.md`. ~10 min once file 1 above exists. |
| 3 | Data shared via Drive/OneDrive/equivalent link | **partially blocked — human action required** | Raw dataset: already public on HF, just link it (done, see #1). Derived metadata+index (~3 GB, see #2): **not hosted anywhere**. README states plainly the dense index (`tables_dense.npy`) "cannot currently be rebuilt from scratch" (its v1 metadata source no longer exists on disk) — so this is the single point of failure for "someone else can reproduce." Someone must upload `data/metadata/` + `data/indexes/` (~3 GB) to Drive/OneDrive and get a shareable link before 17h30. This is upload-and-permission work, not automatable from here — start it now, it is the longest-running item on this list. |
| 4 | Model info doc — chat/answer LLM | **have in code/docs, not written up** | Production model is `Qwen/Qwen3.5-9B`, served locally via vLLM on port 8990 (`docs/HANDOFF.md` line 283, `docs/config_flags.md` line 262, `docs/final_week_plan_2026-08-23.md` line 48 — explicit decision to keep it local, not switch to a hosted large model). **Bug to fix first:** `core/llm.py`'s coded default and the README's own documented example (`export LLM_MODEL=Qwen/Qwen3-8B-Instruct`) are a *stale alias* — `docs/retrieval_preprocessing_2026-08-21.md:713` and `scripts/gate_retrieval_full.py:36` both note this alias **404s** against the current server; the real model is `Qwen/Qwen3.5-9B`. Fix the README example line and confirm this before writing the model doc, or the doc will describe a broken config. |
| 5 | Model info doc — embedding / reranker | **have in code, not written up** | Dense retrieval: `BAAI/bge-m3` (local, `modules/rag/indexing/dense.py`), default backend. Reranker: `Qwen/Qwen3-Reranker-0.6B` via DeepInfra hosted API (`modules/rag/rerankers/deepinfra.py:18`), not a local checkpoint — needs `DEEPINFRA_API_KEY`, no weights to share. Optional alt embedding backend: `Qwen/Qwen3-Embedding-4B`, also DeepInfra-hosted, off by default. |
| 6 | Model checkpoint version + download/usage instructions | **fast to write — no custom fine-tuned weights exist** | All three models above are stock public HuggingFace repos (`Qwen/Qwen3.5-9B`, `BAAI/bge-m3`, `Qwen/Qwen3-Reranker-0.6B`) — this team did not fine-tune anything. "Checkpoint" doc can just be: model name -> HF repo link -> how it's served (local vLLM command for the chat model, `AutoModel.from_pretrained` for bge-m3, DeepInfra API for the reranker) -> required env vars. No large binary needs uploading for this item, unlike item 3. ~20 min to draft `docs/MODEL.md` from `core/llm.py` docstring, `modules/rag/indexing/dense.py` docstring, `modules/rag/retrievers/clients.py` docstring, and README's "LLM backend" section. |
| 7 | Model checkpoint shared via accessible link | **satisfied by linking public HF pages** | Since no custom checkpoint exists (see #6), the "shareable link" requirement is met by linking the three public HF model cards. No upload needed. Double-check this reading is acceptable — the rule's wording assumes teams often have a fine-tuned checkpoint; teams should note explicitly in the doc that no fine-tuning was done, to preempt reviewer confusion. |
| 8 | Source code — full repo | **exists, code_stock.csv... hosting unverified** | `git remote -v` shows `origin = https://github.com/phucduocdoan/ai-finance-stage-2.git`. Anonymous `curl` to the GitHub API for this repo returned **404** — that means either private or renamed/deleted; could not confirm public readability from here. Action: log into GitHub and confirm the remote repo's visibility is Public (or make it so), or otherwise zip `src/`, `scripts/`, `tests/`, `pyproject.toml`, `docs/` (repo minus `.git`, `.venv*`, `sofier_*`, `data/`, `ViFinQA/`, `artifacts/`, `output/` is ~18G total incl. data — code-only is small, well under Drive limits) and upload alongside the data/checkpoint links. 5 min to verify visibility; zip fallback ~10 min if needed. |
| 9 | Dependency/library/framework list | **mostly complete, one real gap found** | `pyproject.toml` lists `duckdb`, `httpx`, `langchain-core`, `langchain-openai`, `langgraph`, `numpy`, `pandas`, `pyarrow`, `pydantic`, `rapidfuzz`, `torch`, `transformers`. Cross-checked against actual imports in `src/finance_qa/**/*.py`: **`bs4` (BeautifulSoup4) is imported directly in production code** (`modules/data/preprocessing/extract_tables.py`, `modules/data/preprocessing/offline/grid.py`, `modules/data/preprocessing/offline/header_flatten.py` — all part of the `build_data_pipeline.py` rebuild chain the README tells users to run) **but is missing from `pyproject.toml`**. A fresh `pip install -e .` per the README's own Setup section will `ModuleNotFoundError` the first time someone runs the data-pipeline rebuild path. Fix: add `beautifulsoup4` to `dependencies` in `pyproject.toml`. 2 min. |
| 10 | Dependency list — minor/lower-priority note | **not blocking** | `pytest` is imported by `tests/test_score_comparators.py` but is not declared anywhere (not in `pyproject.toml`, no dev-deps file) and is not part of README's listed "Common Commands" (those all run test files directly via `python`, not `pytest`). Low priority — either add `pytest` as an optional/dev dependency or note in the README that this one test file needs `pip install pytest` separately. `rapidfuzz` is declared but only used by two non-documented diagnostic scripts (`scripts/build_gold_candidates.py`, `scripts/semantic_filter_gold.py`), not the documented reproduction path — harmless, no action needed. |
| 11 | Config files needed to deploy/run | **exists but scattered — needs a pointer, not new content** | `pyproject.toml` (deps/build), `src/finance_qa/core/paths.py` (filesystem defaults), `src/finance_qa/agents/finance/config.py` (`FinanceAgentConfig` graph defaults — reranker, judge_top_n, frozen_fallback), env vars (`LLM_ENDPOINT`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TEMPERATURE`, `LLM_SEED`, `DEEPINFRA_API_KEY`) documented across README + `core/llm.py` docstring. No dedicated config file is missing; the README/guide doc (item 12) should just enumerate these in one place rather than leaving them spread across three files. |
| 12 | README — "reproduce from scratch" completeness | **partial — real gaps, not just polish** | Root `README.md` (161 lines) is a genuinely good asset (setup, env warning about `.venv_bge`, mermaid flow diagram, common commands) but has concrete holes against the rule's own checklist ("environment, phiên bản phần mềm, cách tải dữ liệu/checkpoint, lệnh thực thi"): (a) the `LLM_MODEL` example is a stale/404 alias (see item 4) — must fix before submitting, this would actively mislead a fresh reproducer; (b) no mention of *which* embedding/reranker backends are default vs. optional, or that the reranker/alt-embedding are paid DeepInfra API calls requiring a key (someone following only the README's "LLM backend" section would not know they also need `DEEPINFRA_API_KEY` for the default `judge` config's reranker per `docs/DECISIONS.md` §3); (c) no data/checkpoint download instructions at all — currently just says "must be placed at the repo root" / "copied in from a backup," which assumes internal access; once items 2/3/6/7 exist, README should link to them; (d) no explicit OS/Python/CUDA driver version pins beyond `requires-python = ">=3.11"` and a mention of "CUDA-12.6 driver" in prose — worth a one-line "tested on" statement. None of these are large rewrites — (a) is a one-line fix, (b)-(d) are short additive paragraphs, all pointing at content produced by other items in this list. ~20-30 min once items 1/2/6/7 exist to link to. |

## Priority order for the remaining hours

1. **Start the data/index upload now** (item 3) — largest file transfer (~3 GB), longest wall-clock, and everything else is fast in comparison. This is the one item that is not primarily a writing task.
2. **Fix the `LLM_MODEL` stale-alias bug** in README (item 4/12a) — a 1-line fix, but leaving it in would make the submitted README actively wrong for a fresh reproducer, which is exactly what the rule is checking.
3. **Add `beautifulsoup4` to `pyproject.toml`** (item 9) — 2 minutes, prevents a real fresh-install failure.
4. **Verify GitHub repo visibility** (item 8) — 5 minutes, decides whether a manual zip+upload is also needed for source code.
5. **Write `docs/DATA.md`** from `docs/competition/data_source.txt` + `docs/metadata_audit.md` (items 1-2) — mostly copy/adapt, ~25 min combined.
6. **Write `docs/MODEL.md`** from `core/llm.py`, `modules/rag/indexing/dense.py`, `modules/rag/retrievers/clients.py` docstrings + README's LLM backend section (items 5-7) — ~20 min.
7. **Patch README** with links to the two new docs and the missing DeepInfra-key/version-pin notes (item 12) — ~20-30 min, do last so it can link to the finished docs.

Total estimated writing time once the upload is running in parallel: roughly 1.5-2 hours of
focused work, dominated by the data/index upload's wall-clock time rather than the writing
itself.

## Update (2026-08-31, ~1.5h before deadline)

`docs/DATA.md` and `docs/MODEL.md` now exist, written from the actual code/data (not just the
estimates above) — `core/llm.py`, `modules/rag/indexing/dense.py`, `modules/rag/indexing/deepinfra.py`,
`modules/rag/rerankers/deepinfra.py`, `modules/rag/retrievers/clients.py`, `agents/finance/config.py`,
`docs/DECISIONS.md` §8, and `docs/competition/data_source.txt`, plus a direct pandas/numpy
inspection of the three derived artifact files.

One correction to this list's earlier size estimate: the ~628M/~2.4G figures above were the
*whole* `data/metadata/` and `data/indexes/` directories, which include several experimental
variant files (`tables_metadata_v3.jsonl`, `tables_dense_v3.npy`, `tables_dense_noheader.npy`,
etc.) that are not part of the README's required-inputs list. The actual three required files
(`tables_metadata_v2.jsonl`, `tables_doc_text.parquet`, `tables_dense.npy`) total **~618 MiB
(~648 MB)** by direct measurement — a much smaller and faster upload than originally estimated.
`docs/DATA.md` documents this distinction and recommends uploading only the required three.

Item 4's stale-`LLM_MODEL`-alias concern is already resolved: current `README.md` documents
`export LLM_MODEL=Qwen/Qwen3.5-9B` for the local vLLM path, not the old 404ing alias. No README
edit was needed for that specific bug. `docs/MODEL.md` does flag one real README gap not yet
fixed: the README's "LLM backend" section never mentions that the default reranker
(`qwen3-0.6b`, DeepInfra-hosted) requires `DEEPINFRA_API_KEY` — noted in `docs/MODEL.md` itself
as a follow-up, not fixed here since it's outside this task's scope (writing the two docs only).

**Remaining manual blockers — cannot be done by an agent:**

1. Upload the three required derived-data files (~618 MiB total: `data/metadata/tables_metadata_v2.jsonl`,
   `data/indexes/tables_doc_text.parquet`, `data/indexes/tables_dense.npy`) to Google Drive or
   OneDrive, set sharing to "anyone with the link."
2. Paste that link into the `[TODO: ...]` placeholder at the top of `docs/DATA.md`.
3. Verify the link works from a logged-out/incognito browser before submitting, per
   `final_submission.md`'s own closing recommendation.

Everything else needed for items 1, 2, 5, 6, 7 in the checklist above is now written and
requires no further human action beyond the three steps here. Item 9's `beautifulsoup4` gap is
also already resolved — current `pyproject.toml` lists `beautifulsoup4==4.15.0` in
`dependencies`, so no action needed there. Items 3, 8, 12 (source-code hosting verification,
README polish) are unchanged from the original list above and still need separate attention if
time remains.
