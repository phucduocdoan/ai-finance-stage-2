# Raw Table Linker Guardrails - Gold73 Measurement

Date: 2026-08-17.

This follows `artifacts/audits/raw_linker_gold73_buckets.md`, where the first
broad raw-linker run scored 43/73 versus a same-session control at 44/73. The
regression cluster was deterministic/direct raw linking.

## Code Change

General fail-closed guardrails were added in
`src/finance_qa/modules/solve/raw_table_linker.py`:

- store candidate unit provenance as `source_unit_from`;
- keep single-slot `sum`/`avg` out of phase-1 raw-table arithmetic;
- keep single-cell direct requests with ratio target out of raw linking;
- require stronger evidence for direct candidate selection;
- reject selected raw candidates whose numeric value is `0.0`;
- expose unit provenance in candidate prompts/diagnostics.

No question-id rules or semantic if/elif branches were added.

## Verification

Offline:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
```

Both passed.

Targeted live probe:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids 55,120,262,263,283,732,353,744,753,754,818,856 \
  --out artifacts/runs/raw_linker_guardrails_probe_12.jsonl --workers 1
```

The six previous linker-caused regressions fail closed and return to correct
fallback answers:

| qid | solver after guardrail | guardrail reason |
|---:|---|---|
| 55 | codegen | direct candidate evidence below threshold |
| 120 | codegen | direct candidate evidence below threshold |
| 262 | codegen | single-slot sum is a lookup, not raw-table arithmetic |
| 263 | codegen | direct candidate evidence below threshold |
| 283 | codegen | selected candidate value is zero |
| 732 | codegen | single-cell direct request cannot answer a ratio |

The representative raw-linker wins remained intact:

```text
353 -> 7306.508578
744 -> -2880000.0
753 -> 571308.0
754 -> 116644397.0
818 -> 145.134
856 -> 2992.4
```

## Full Gold73

Command:

```bash
rtk env PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py \
  --ids "$(cat artifacts/audits/gold73_ids.txt)" \
  --out artifacts/runs/gold73_raw_linker_guardrails_on.jsonl --workers 4
```

Score:

| Run | Score |
|---|---:|
| `gold73_raw_linker_guardrails_on.jsonl` | **49/73** |
| `gold73_raw_linker_off.jsonl` | 44/73 |
| `gold73_after_stt_shift_fix_live.jsonl` | 44/73 |

Solver distribution in the guardrail run:

| solver | count |
|---|---:|
| codegen | 46 |
| raw_table_linker | 14 |
| cell_locator | 7 |
| formula_facts | 6 |

Raw-linker decision sources:

| decision_source | count |
|---|---:|
| deterministic | 7 |
| candidate_planner | 5 |
| search_expanded_candidate_planner | 2 |

Delta versus same-session control:

- Guard-only wins: `353, 744, 753, 754, 818, 856`.
- Control-only loss: `327`.

`327` is not a raw-linker fire; it is fallback/codegen nondeterminism in this
live run. The measured raw-linker contribution is therefore the six guard-only
wins while the previous six linker-caused regressions are now blocked.

## Next

Keep the branch opt-in until at least one more broad run or full 1012 run checks
for live nondeterminism and non-gold regressions. The next useful audit is not a
new semantic rule; it is to inspect raw-linker fires that are still wrong or
latent-risk cases, especially `920`, `955`, and the q792 near-miss.

