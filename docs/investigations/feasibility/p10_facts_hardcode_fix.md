# P10 — Feasibility check: fixing the 107-item `execute_plan()` hardcode

Follows up on `docs/feasibility/p9_hardcoded_query_compliance_audit.md` §4a/§8,
which found 107 items (`formula_facts`=54, `selection_facts`=50, `codegen`=3)
ship `pandas_query = repr(float(scaled))` — a bare literal, no df reference —
from `execute_plan()` in `src/finance_qa/modules/solve/facts/execute.py`
(~line 279), with `evidence: []`.

**Outcome: no code changed.** Investigated feasibility only, per the task's
own instruction to revert/abstain if verification is uncertain. `execute.py`
and every other file are untouched — `git status --porcelain -- src/.../facts/execute.py`
is empty.

## 1. What provenance actually survives per fact

`StatementFactStore.value()` (`src/finance_qa/modules/solve/facts/store.py`)
returns a `Fact(value, table_id, row)` where `table_id = f"{report_id}|{table_pos}"`
(same id format `load_frame`/`evidence_for` already expect — that part is
compatible) and `row` is one record from `long_format.parquet`:
`report_id, ticker, year, doc_type, statement_type, statement_subtype,
table_pos, ma_so, label, note_id, period, value`.

Critically **absent**: the row's positional index and the column's positional
index within the actual CSV. `long_format.py`'s builder
(`src/finance_qa/modules/data/preprocessing/long_format.py::process_table`)
iterates `df.iterrows()` and only keeps `ma_so`/`label`/`period` (the raw
column header text) and `value` — it discards the row/column position. So
"which cell" is recoverable only by re-matching `ma_so` (or `label`) and the
`period` header text against a dataframe at query time, not by direct
`iloc[r, c]` addressing.

## 2. Why re-matching at query time is not safely mechanical

`long_format.py` reads each table with a **plain** `pd.read_csv(csv_path,
dtype=str, keep_default_na=False)` — no repairs. The frame that actually gets
shipped as evidence (`load_frame()` in
`src/finance_qa/modules/data/table_store.py`) reads the *same* source CSV but
then runs it through four structural repair passes before `normalize_frame`:
`repair_shifted_bank_header`, `repair_shifted_multilevel_header`,
`repair_group_leaf_header`, `repair_right_shifted_columns`. These rename,
reorder, or relabel columns for tables with shifted/misaligned headers (their
own docstrings cite concrete examples: `KLB_2019_consolidated|67`,
`DTK_..._2024_consolidated|9`, and 144/1,365 tables matched by
`repair_group_leaf_header` alone).

Consequence: for any fact drawn from a table that needed one of these
repairs, the `period` string stored in `long_format.parquet` (the *raw*
header text) may no longer be a column name in the *repaired* frame that
gets shipped and executed against. There is no per-fact flag recording
whether its source table was repaired, so a synthesis step can't
conditionally special-case this — it would have to re-run the same
label/ma_so/column search logic `raw_table_linking` already implements, per
fact, against the repaired frame, and verify the result still equals
`fact.value` before trusting it enough to emit a query. That degree of
re-derivation is a real engineering task, not a one-line query-string
formatter.

## 3. Composite formulas compound the problem

Most flagged items aren't a single cell lookup. `execute_plan()`'s branches
(`_metric_value`, `_execute_selection`, `_execute_aggregate`) combine 2+
primitives — often from different tables/statement_types/doc_types/years
(e.g. `roe` = `net_profit / average(equity_begin, equity_end)`, pulling from
income_statement and balance_sheet, two periods of one ma_so) — then apply
unit scaling (`_scale`/`conversion_factor`, ratio→percent ×100), rounding,
and for `argmax`/`argmin`/`filter_aggregate` a ranking or median-threshold
selection over several ticker/year candidates before picking the final
metric. Reproducing this as *one* `dfN`-referencing pandas expression per
operation type (lookup, ratio, growth, diff, avg, median, argmax, argmin,
filter_aggregate × share/mean/median/sum/count) is effectively writing a
second code generator — structurally the same problem `codegen/execute.py`
solves by having an LLM author the expression up front, not something
`execute.py` can bolt on mechanically from the data it currently keeps.

## 4. Feasibility verdict

**Not safely fixable in the remaining time.** The blocking gap is data, not
code structure: `Fact.row` doesn't carry the row/column position needed to
build a real `iloc`/`loc` reference, the fallback (re-matching by
`ma_so`/`period` text) is unreliable against repaired frames with no
per-fact signal of repair, and even a reliable cell locator would only solve
single-primitive lookups — most flagged items need multi-step formula
synthesis on top. Attempting this against a live path ~1.5h before the
deadline, with no time budget for the verification loop the task requires
(rebuild, re-audit, regression-check all 1012, confirm answers unchanged),
is exactly the "uncertain, so don't ship" case the task called out.

No fix attempted; no files changed.

## 5. Recommendation

Leave the known, bounded 107-item risk as-is, consistent with
`p9_hardcoded_query_compliance_audit.md` §8 item 2: these items lose only
execution-accuracy credit on the organizer's own "sai định dạng → chỉ câu đó
[bị 0]" rule, not the whole submission, and their `relevant_docs`/
`relevant_tables` retrieval credit is unaffected. `output/submission_v19_boolfix/`
(from the already-applied, already-verified 9-item boolean-rounding fix)
remains the package to submit.

For a future (post-deadline) fix pass, the concrete engineering plan would be:

1. Thread `row_index`/`col_index` (or a stable row/column key materialized
   *after* the same repair pipeline `load_frame` runs) through
   `long_format.py`'s builder, so `Fact` carries a real cell address instead
   of just `ma_so`/`period` text. Requires re-running the long-format build
   against repaired frames, or building it by calling `load_frame()` per
   table instead of a bare `pd.read_csv`.
2. In `execute_plan()`, extend `_EvalContext.primitive()` to also record
   `(var, table_id, row_key, col_key)` per fact used (it already collects
   `ctx.facts`).
3. Write one synthesis function per `plan.operation` branch that renders the
   recorded fact addresses plus the same arithmetic `execute_plan()` already
   performs (scaling, filters, selection/aggregation) into a single
   `dfN`-referencing expression string, then executes that string through
   `finance_qa.modules.tools.python_exec.run_query` and asserts the result
   equals `scaled` before emitting it (mirroring codegen's fallback-on-
   mismatch pattern) — never emit a synthesized query that doesn't
   round-trip.
4. Populate `evidence` via the existing `evidence_for()` contract
   (`src/finance_qa/modules/solve/pipeline/emit.py`) from the tables actually
   referenced.

Rough estimate: 1-2 engineer-days (mostly step 1's data threading and step 3's
per-operation synthesis + round-trip verification across ~10 operation
variants), not a same-day fix.
