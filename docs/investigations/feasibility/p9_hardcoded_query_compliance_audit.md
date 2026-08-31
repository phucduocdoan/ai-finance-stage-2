# P9 — Hardcoded-`pandas_query` Compliance Audit (fresh, 2026-08-31)

Organizer rule under test (`final_submission.md`):

> Kết quả của mỗi pandas query phải được tính toán trực tiếp từ dữ liệu có
> trong các bảng CSV tại thời điểm thực thi. Không được gán cứng, mã hóa
> hoặc lưu sẵn kết quả dưới bất kỳ hình thức nào.

Forbidden examples given by organizers: `result = 2.06`, `result = 1.03 * 2`,
`result = df["answer"].iloc[0]`. Violating questions score **0** for that
question only (separate rule: "sai định dạng -> câu đó không hợp lệ", not the
whole submission).

The prior audit at `docs/SUBMISSION_EXECUTION_AUDIT.md` (2026-08-16) checked
an old package (`cell_locator_1012_submission`) against old code. It is
superseded by this document; do not use its numbers.

## 1. Which package was audited

`scripts/build_submission.py` takes `--run <jsonl>` and writes
`<out>/submission.json` + `<out>/data/*.csv`. No Makefile target or README
wraps it; invocation is manual (see the script's own docstring).

Candidate run files in `artifacts/runs/` (newest complete first, by mtime):

| file | lines | mtime (UTC) | complete? |
|---|---|---|---|
| `full1012_headcode_today_w8.jsonl` | 492 | 2026-08-31 06:44 | **no — live/in-progress, excluded per instructions** |
| `full1012_oldcode_today_w8.jsonl` | 439 | 2026-08-31 06:42 | **no — live/in-progress, excluded per instructions** |
| `full1012_v18_postfix.jsonl` | 1012 | 2026-08-29 22:48 | yes |
| `full1012_v17_unitfix.jsonl` | 1012 | 2026-08-24 09:43 | yes (older) |
| `full1012_t06.jsonl` | 1012 | 2026-08-24 07:20 | yes (older) |

`full1012_v18_postfix.jsonl` is the newest complete (1012/1012) run, and its
mtime (22:48 on 2026-08-29) is **after** all five regression-fix commits
listed in the task (`b799b22`, `35a313c`, `7f4fb27`, `ba75239`, `1a01801`,
all committed 17:57:42–17:58:18 on 2026-08-29, matching current `HEAD`). A
pre-built package from it already exists: `output/submission_v18_postfix/`
(`submission.json`, `data/`, built 2026-08-29 22:50), and it was used as-is
— rebuilding produced no differences worth noting since it's already current.

This is the package audited below. (Note: there is one uncommitted working-tree
change on top of HEAD, in `raw_table_linking/request.py`'s stopword handling
for the token `cho` — a retrieval/scoring tweak, not a query-generation path,
so it does not affect this audit.)

## 2. Method

1. **Static AST scan** (`/tmp/audit_hardcoded.py`, not checked in — a one-off
   check, not proposed as permanent CI): for every item's `pandas_query`,
   parse with `ast`, walk the whole tree, and flag any item where no `Name`
   node matches `df\d+` anywhere in the expression. This catches both the
   organizer's literal examples and disguised hardcoding (e.g. a real-looking
   expression that never actually touches a dataframe).
2. Sub-classified flagged items into `BARE_LITERAL` (the whole query reduces
   to a literal/arithmetic expression with no Name/Call/Subscript/Attribute
   at all) vs `NO_DF_REF` (has some structure — e.g. `round(<literal>, 2)` —
   but still no df reference).
3. **Dynamic verification**: executed every one of the 1012 queries via
   `finance_qa.modules.tools.python_exec.run_query` against the shipped
   `data/*.csv`, comparing the result to the item's `answer`.
4. Traced flagged items back to their source record in
   `full1012_v18_postfix.jsonl` to find the root cause in the pipeline code
   (not just the packaging step).
5. Spot-checked 10 `evidence[].csv_path` files against
   `ViFinQA/financial_statements/<TICKER>/<YEAR>/.../*_extracted.txt`.

## 3. Exact counts

Total items: **1012**

| category | count | meaning |
|---|---|---|
| OK (references a dataframe) | 872 | compliant |
| `NO_DF_REF` | 107 | query has structure (e.g. `round(x, 2)`) but no df reference |
| `BARE_LITERAL` | 33 | query is nothing but a literal/arithmetic expression |
| **Flagged total, excluding the 66-item zero-answer fallback** | **116** | **non-compliant, would score 0 under the rule** |

`answer == 0.0` items: 66 total.
- 42 of these have a real dataframe-computed query that legitimately
  evaluates to 0 (e.g. id 156, 158, 168 — genuine `df2.iloc[...]` expressions
  whose scaled result rounds to `0.0`). These are compliant; they are inside
  the 872 "OK" count.
- 24 are the packaging give-up fallback: `pandas_query == "0.0"` /
  `"round(0.0, 2)"`, `evidence: []` — see §5.

**Execution consistency** (separate from the hardcoding rule): all 1012
queries, including all 116 flagged ones, execute without error and reproduce
`answer` exactly (`exec_ok=1012, exec_fail=0, exec_mismatch=0`). This
matters because it means the flagged items will *not* be caught by an
"does the query even run / match the answer" check — a literal like
`round(2077.87, 2)` trivially "runs" and "matches". Only a rule-aware check
(does it touch a dataframe) catches them, which is exactly what this audit
does and what the organizers' human/automated reviewer is expected to do.

## 4. Root causes of the 116 flagged items

Two distinct, unrelated mechanisms — traced by diffing each flagged item's
final `submission.json` query against its original entry in
`full1012_v18_postfix.jsonl`.

### 4a. Upstream solver-level hardcoding — 107 items (the large one)

`execute_plan()` in `src/finance_qa/modules/solve/facts/execute.py`
(around line 279) ends with:

```python
return {
    "answer": float(scaled),
    "pandas_query": repr(float(scaled)),   # <- bare literal, no df reference
    "table_ids": table_ids,
    "evidence": [],
    ...
}
```

This is the deterministic executor behind the `formula_facts` and
`selection_facts` solvers (`SOLVE_*`-flag-gated deterministic stack from
commit `69515d0`). It computes the answer from a separately-parsed
`StatementFactStore` (not from `df1`/`df2` pandas objects), then literally
`repr()`s the resulting float as the "query" and ships `evidence: []`. There
is no query-synthesis step in this code path — it was built to answer, not
to produce a df-executable trace.

Breakdown by solver tag (from the run file, 107 items total):
`formula_facts` = 54, `selection_facts` = 50, `codegen` = 3.

Notably, `src/finance_qa/modules/solve/codegen/execute.py` (~line 570)
*already* guards against exactly this failure mode with an explicit comment
— *"Never submit a bare float literal — that forfeits the execution
objective outright"* — and falls back to the last non-empty query string
instead of a literal. The facts-solver stack has no equivalent guard. This
reads as an oversight (a known anti-pattern fixed once in codegen, not
retrofitted into the newer facts stack) rather than a deliberate tradeoff.

### 4b. Packaging-level literalization of a genuinely-computed query — 9 items

`round_final()` in `scripts/build_submission.py` unconditionally wraps every
`pandas_query` as `round(<query>, 2)` before packaging (to honor "chỉ làm
tròn kết quả cuối 2 chữ số"). For the small set of solver-produced queries
that evaluate to a Python/`numpy.bool_` (boolean comparison/count
questions, e.g. id 366: `df1.iloc[15][...] > 0 and df2.iloc[16][...] > 0 and
df3.iloc[15][...] < 0`), `round(numpy.bool_, 2)` raises
`TypeError: type numpy.bool doesn't define __round__ method` — confirmed by
executing the exact wrapped string. `make_query_exec_safe()` then treats this
as a failed query and calls `_literalize_query()`, replacing the *original,
correctly df-referencing* query with a bare `repr(answer)` (e.g. `"1.0"`).

So these 9 items (ids: 366, 399, 437, 463, 484, 538, 870, 990, 1005) were
**compliant upstream and became non-compliant purely as a packaging bug** —
a bool/round dtype mismatch, not a hardcoding intent anywhere in the
pipeline.

## 5. Is the `answer=0.0` give-up placeholder itself a compliance risk?

`build_item()`'s fallback (used when a pipeline record has no valid `item`)
emits `pandas_query = "0.0"`, `evidence = []`, `answer = 0.0`. After
`round_final()` this becomes `"round(0.0, 2)"`. Textually this **does**
match the forbidden pattern (`result = <number>`-shaped, no df reference).

Reasoning: **non-issue, no incremental risk.** These 24 items are already
worth 0 on the execution/answer axis by design (organizer's own
"thiếu câu" rule requires *some* item to exist so retrieval can still be
scored, with `answer=0.0` standing in for "we have nothing"). Getting
additionally zeroed under the no-hardcode rule changes nothing — it's the
same score (0) either way, and `relevant_docs`/`relevant_tables` are
preserved so retrieval credit is unaffected. This is not something worth
spending remaining time on.

## 6. CSV traceability spot check (light, per instructions)

Checked 10 `evidence[].csv_path` files (data shipped in
`output/submission_v18_postfix/data/`) against
`ViFinQA/financial_statements/<TICKER>/<YEAR>/.../*_extracted.txt`:
`DIG_..._2016_consolidated_table_7`, `BID_..._2023_consolidated_table_37`,
`MSR_..._2023_consolidated_table_75`, `HPG_..._2022_consolidated_table_3`,
plus 6 more by filename pattern. All content (row labels, numeric values)
matches a `<table>` block in the corresponding OCR-extracted source text
verbatim (e.g. `DIG` table_7's `692.022.624.428` cell traces exactly to the
source `<td>692.022.624.428</td>`). No synthesized/fabricated tables found
in the sample. Given the low prior risk and time budget, this check was kept
light per the task's own priority guidance and not expanded further.

## 7. Flagged non-compliant items

Full list of all 116 ids + exact `pandas_query` text is in
`/tmp/audit_hardcoded_result.json` (`flagged_non_fallback` key; regenerate
anytime with `/tmp/audit_hardcoded.py output/submission_v18_postfix`). The
9 packaging-bug ids are listed in §4b; the other 107 are the
`repr(float(scaled))` outputs from `formula_facts`/`selection_facts`/
`codegen`, e.g.:

```
id=18   'round(2077.8695966550004, 2)'   (orig: '2077.8695966550004', formula_facts)
id=45   'round(108950874.0, 2)'          (orig: '108950874.0', formula_facts)
id=727  'round(10, 2)'                   (orig: '10', codegen)
id=832  'round(2017, 2)'                 (orig: '2017', codegen)
```

## 8. Recommendation

**Not safe to submit as-is.** 116 / 1012 items (11.5%) will score 0 on the
execution/no-hardcode rule under any rule-aware reviewer or automated
checker, concentrated almost entirely (107/116) in one function.

Given the ~2-hour deadline, two independent fixes, ranked by risk/reward:

1. **Do this one — low risk, ~9 items recovered.** In
   `scripts/build_submission.py::round_final`, coerce booleans before
   wrapping in `round(...)` (e.g. `query = f"round(float({query}), 2)"`, or
   detect bool results in `make_query_exec_safe` before literalizing). This
   is a one-line, mechanically verifiable fix — rerun
   `scripts/build_submission.py --run artifacts/runs/full1012_v18_postfix.jsonl`
   and confirm those 9 ids again reference `df` in the final
   `submission.json`.
2. **Skip given the deadline — high risk, 107 items.** Fixing
   `execute_plan()` in `facts/execute.py` to emit a real df-referencing
   expression requires synthesizing pandas code from `StatementFactStore`
   provenance (table/row/col per fact) — a genuine engineering task, not a
   one-liner, and not something to rush untested this close to submission.
   Recommend accepting this as a known, bounded risk: worst case is these
   107 questions score 0 on execution accuracy specifically (their
   `relevant_docs`/`relevant_tables` retrieval credit is unaffected since
   those fields stay populated), not that the whole submission is rejected
   (per the organizer's own "sai định dạng -> chỉ câu đó" rule).

If item 1 is applied, rebuild with:
```
PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py \
    --run artifacts/runs/full1012_v18_postfix.jsonl --out output/submission_v19_boolfix
```
and re-run `/tmp/audit_hardcoded.py output/submission_v19_boolfix` to confirm
the flagged count drops from 116 to 107 before submitting.

## 9. Update — fix 1 applied and verified (2026-08-31, same session)

`scripts/build_submission.py::round_final` changed from
`f"round({query}, 2)"` to `f"round(float({query}), 2)"` — coerces
`numpy.bool_`/other non-round-able dtypes to `float` before rounding, so a
genuinely df-referencing boolean/comparison query no longer raises inside
`make_query_exec_safe` and gets literalized away.

Rebuilt: `output/submission_v19_boolfix/` from the same
`full1012_v18_postfix.jsonl` run. Re-audited with `/tmp/audit_hardcoded.py`:

- `flagged_non_fallback`: **116 → 107** (exactly the 9 predicted ids).
- Confirmed ids 366, 399, 437, 463, 484, 538, 870, 990, 1005 no longer appear
  in the flagged set.
- `format OK: đủ câu, đúng schema, mọi csv_path có file` — packaging
  validation still passes; no new warnings introduced (same pre-existing
  literal-fallback warnings for ids like #15, #16, #193, #395, #412, #464,
  #529, #540, #556, #576, unrelated to this fix, present before too).

Remaining 107 items (the `execute_plan()`/`repr(float(scaled))` root cause,
§4a) are unchanged — still an accepted, bounded, known risk per §8 item 2;
not attempted given the deadline.

**`output/submission_v19_boolfix/` is now the recommended package to
submit**, superseding `output/submission_v18_postfix/`.
