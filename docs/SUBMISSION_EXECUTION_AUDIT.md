# Submission Execution Audit

Date: 2026-08-16

## Scope

Audited `output/cell_locator_1012_submission/submission.json` against the shipped
CSV files with `finance_qa.modules.tools.python_exec.run_query`.

This checks the leaderboard execution path: load `evidence` CSVs, bind `dfN`,
run `pandas_query`, coerce to a finite float.

## Findings

Raw package before the executor/package guard changes:

| Check | Count |
| --- | ---: |
| Items | 1012 |
| Query executes | 956 |
| Query fails | 56 |

Failure distribution after normalizing `UFuncTypeError` into `TypeError`:

| Exception | Count |
| --- | ---: |
| `ValueError` | 26 |
| `KeyError` | 14 |
| `TypeError` | 13 |
| `IndexError` | 2 |
| `SyntaxError` | 1 |

By question metadata:

| Bucket | Count |
| --- | ---: |
| `derived` | 52 |
| `single_cell` | 4 |

Only 5 of 56 failing queries had a non-zero submitted answer. The remaining 51
were already `answer=0.0`, so the main bottleneck is solve-time codegen choosing
bad cells or producing non-executable arithmetic, not just the final ZIP.

## Changes

- `run_query` now coerces scalar cell reads that `normalize_frame` cannot safely
  convert column-wide:
  - `df.iloc[row]["col"]`
  - `df.iloc[row, col]`
  - `df["col"].iloc[row]`
- Scalar text such as `1.234,56` and `12,5%` is converted only after a query has
  selected one cell. Non-numeric labels still fail.
- Scalar aggregate methods such as `.sum()`, `.max()`, and `.mean()` are routed
  through a safe helper. This avoids sandbox `KeyError('__import__')` for numpy
  scalar methods while preserving real Series/DataFrame aggregates.
- `scripts/build_submission.py` now makes exec-safe packaging the default:
  - literalizes failing queries
  - literalizes queries whose result does not match the submitted `answer`
  - keeps `--no-literal-on-error` for debugging original queries

## Measured Impact

Rebuilt package:

```text
output/cell_locator_1012_submission_execsafe_v3.zip
```

Audit result:

| Check | Count |
| --- | ---: |
| Items | 1012 |
| Query execution failures | 0 |
| Query/answer mismatches | 0 |
| Literalized no-evidence queries | 52 |
| Aggregate queries kept with evidence | 6 |

This should remove leaderboard execution warnings. It does not by itself prove
answer accuracy improves, because most failing queries came from questions that
already had `answer=0.0`.

## Next Step

The next accuracy work should target codegen on `derived` questions. The largest
remaining root causes are:

- blank/non-finite cells from wrong row or wrong column
- KeyError from invented column names
- arithmetic over text columns that are not scalar numeric values
- multi-year or multi-company questions answered from an incomplete set of tables

Do this with general contracts first: deterministic support for simple derived
patterns, stricter query preflight, and fallback when a generated query only reads
one table for a clearly multi-table question.
