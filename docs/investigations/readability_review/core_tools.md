# Readability review: core, tools, pipelines, evaluation

Scope: `core/{config,http,llm,paths,types}.py`,
`modules/tools/{dataframe,numeric,python_exec}.py`,
`pipelines/{data_pipeline,submission}.py`, `evaluation/retrieval.py`.

1. **`core/config.py:1-33` (whole file) is dead and duplicates fragile
   config that lives for real in `core/llm.py`.** `LLMConfig`,
   `DEFAULT_LLM_CONFIG`, `LLM_ENDPOINT`, `LLM_MODEL`, `LLM_API_KEY` are not
   imported anywhere in `src/`, `scripts/`, or `tests/` — the actual runtime
   config is the separate module-level `ENDPOINT`/`MODEL`/`API_KEY` in
   `core/llm.py:33-41`, and the two copies of the same default literals
   (`"http://127.0.0.1:8990/v1/chat/completions"`, `"Qwen/Qwen3.5-9B"`) can
   silently drift apart, which is precisely the class of bug `llm.py`'s own
   comment (the 2026-08-23 model-id incident) warns about. Delete
   `config.py` (or make `llm.py` actually build on it) so there is one
   source of truth for this value.

2. **`modules/tools/python_exec.py:199-223` (`exec_in_namespace` and its
   inline `safe_builtins`) is dead code.** Nothing in `src/`, `scripts/`, or
   `tests/` calls `exec_in_namespace`; the module docstring's "Python
   execution... helpers" framing plus `llm.py`'s reference to "the REPL
   solver" leads a reader to expect a live execution path here that doesn't
   exist. Either wire it to whatever REPL tool it was written for, or remove
   it — as-is it's a maintenance trap.

3. **`modules/tools/python_exec.py` mixes two unrelated concerns behind one
   module boundary**: the live query-execution sandbox (`SAFE_GLOBALS`, AST
   coercion, `run_query`, lines 14-197) and the offline submission linter
   (`validate`, lines 225-300). `run_query`/`SAFE_GLOBALS` are imported by
   the live solve path (`modules/solve/codegen/execute.py`), while `validate`
   is only imported by `scripts/build_submission.py` and the
   `scripts/gate_*.py` one-off tools — it has nothing to do with "tools the
   agent calls." A new engineer scanning `modules/tools/` for the agent's
   runtime toolset will trip over a submission-file linter that belongs
   closer to `pipelines/submission.py` or a dedicated `evaluation/` module.
   Suggest splitting `validate()` (and `query_names`, which it alone drives)
   out of this file.

4. **`modules/tools/dataframe.py`: the same three-line "rebuild columns and
   return" tail is repeated near-verbatim across all four `repair_*`
   functions** (lines 59-61, 75-77, 171-173, 229-231, 273-275:
   `out = df.copy(); out.columns = [...]; return out`, with one variant using
   `.iloc[:, :-1]`/`body.reset_index(drop=True)`). Not urgent — the
   surrounding detection logic legitimately differs and the comments there
   are valuable — but a small `_with_columns(df, names, drop_first_row=False)`
   helper would remove five near-duplicate lines and make the four repair
   functions read as "detect condition -> call helper."

5. **`core/http.py:38-49` — the function `pool()` returns a per-event-loop
   object cache, not a connection pool, which collides with the module's own
   vocabulary** (`LIMITS = httpx.Limits(...)` a few lines above is the actual
   connection pool). The docstring on `pool()` itself says "cache," so the
   code is correct, but the exported name invites a reader to conflate "the
   httpx connection pool" with "the dict `pool()` returns." A name like
   `_loop_cache()`/`loop_registry()` would remove that ambiguity for anyone
   skimming `core/http.py` for the first time.

6. **`evaluation/retrieval.py:258-346` (`main`) does five distinct jobs in
   one function**: build the retriever, run the stage loop, assemble
   per-question rows, build the summary, and handle file I/O/printing. It's
   a script entry point so some of that is expected, but the per-question
   row-building loop (lines 279-317) is the part most likely to change when
   a new metric is added, and it's currently interleaved with
   argparse-derived `args.*` reads and print statements. Pulling the loop
   into a `build_rows(evalset, retriever, stage, thinking) -> list[dict]`
   function would make "what does scoring actually consume" answerable
   without reading the whole CLI wrapper.

7. **`evaluation/retrieval.py:54` — `DENSE_PATH = DENSE_INDEX_PATH` is a
   second name for the same constant**, re-exported and consumed by two
   `scripts/diag_*.py` files. It's not dead, just an unexplained alias; a
   one-line comment on why the retrieval module renames the path constant it
   imports (or just having the diag scripts import `DENSE_INDEX_PATH`
   directly from `core.paths`) would remove the "why are there two names"
   question for a new reader.

## Overall impression

This is a well-organized, carefully-commented codebase — the "why" comments
in `dataframe.py`, `core/http.py`, and `modules/solve/codegen/execute.py` are
genuinely load-bearing and should stay untouched. The functions read are
mostly right-sized and single-purpose; the issues found are narrow (one dead
module, one dead function, one misplaced function) rather than systemic.

**If only one change could be made:** delete `core/config.py` (item 1) — it's
unused, it duplicates the exact fragile literals (`LLM_ENDPOINT`/`LLM_MODEL`)
that already caused a real production incident documented in `core/llm.py`,
and a new engineer has no way to know from reading the code alone which of
the two config sources is authoritative.
