# Raw Table Linker - Gold73 Broad Measurement

Date: 2026-08-17. This is the measurement `docs/NEXT_AGENT_HANDOFF.md` asked for before
expanding the raw linker. Numbers only; the decision notes live at the end.

## Setup

Ids: the 73 honest gold questions (`unbiased60_gold` + `manual15_gold`, confidence >= medium,
`gold_answer` present) -> `artifacts/audits/gold73_ids.txt`.

`run_graph.py --measure` was **not** used: it reads `data/eval/planner_answers.json`, which is 15
questions inside the tuned 363-440 band, so `score_unbiased60.py` would score almost nothing.

```bash
# treatment
PYTHONPATH=src SOLVE_CELL_LOCATOR=1 SOLVE_FORMULA_FACTS=1 \
  SOLVE_RAW_TABLE_LINKER=1 SOLVE_RAW_TABLE_LINKER_PLANNER=1 SOLVE_TABLE_PROFILES=0 \
  .venv_bge/bin/python scripts/run_graph.py --ids "$(cat artifacts/audits/gold73_ids.txt)" \
  --out artifacts/runs/gold73_raw_linker_on.jsonl --workers 4

# control: same command without the two linker flags -> gold73_raw_linker_off.jsonl
```

## Score (tol 1% relative)

| Run | Score |
|---|---|
| `gold73_raw_linker_on.jsonl` | **43/73** |
| `gold73_raw_linker_off.jsonl` (same-session control) | **44/73** |
| `gold73_after_stt_shift_fix_live.jsonl` (2026-08-16 baseline) | 44/73 |

The control reproduces yesterday's baseline exactly, so the harness is sound and the linker is
net **-1**. It is not a win yet. Keep the branch opt-in.

## Per-question delta vs control

- linker-only wins (6): `353, 744, 753, 754, 818, 856`
- control-only wins (7): `55, 120, 262, 263, 283, 732` (all linker-caused) + `635`
  (`635` is codegen nondeterminism; the linker never fired on it)
- both correct: 37, both wrong: 23

## Where the linker fired

24 of 73 questions, 14 correct / 10 wrong, by decision source:

| `decision_source` | fires | correct | regressions |
|---|---:|---:|---:|
| `deterministic` | 14 | 8 | 5 (`120, 262, 263, 283, 732`) |
| `candidate_planner` | 7 | 4 | 1 (`55`) |
| `search_expanded_candidate_planner` | 3 | 3 | 0 |

The regression cluster is the deterministic top-1 branch, not the planner.

Fail-closed reasons on the other 49: `outside raw-table fixed-scope operations` 22,
`raw-table ratio not enabled in phase 1` 6, planner "no candidate describes X" 3,
`operation mismatch` 2, `IndexError: list index out of range` 1.

## Failure buckets for the 6 linker-caused regressions

| qid | bucket | root cause |
|---|---|---|
| 120 | unit/scale mismatch | the linker picked `\|75`, a 7-row KPI summary table that declares its unit nowhere (`page_text` is 0 chars, no banner, no unit in any column name), so `detect_unit` returns `unknown` and units then defaults to VND (`source_unit_from="mặc định vnd (bảng không khai đơn vị)"`) and divides by 1e6 → 1.041601 vs gold 1041601. Codegen read the same number from `\|8`, the income statement, whose page text says `Đơn vị tính: triệu VND`. Two separable defects: candidate scoring is blind to unit provenance, and `source_unit=unknown` is scaled as VND instead of failing closed. Note `page_text(table_id)` *is* already passed into `detect_unit` at `raw_table_linker.py:627`. |
| 283 | planner/deterministic chose wrong column | same table and row as gold, column `Số phải thucuối năm` instead of `Số phải nộpcuối năm`. Value is `0.0` and was still submitted, although `answer == 0.0` is a documented certain-failure detector. |
| 262 | wrong row candidate | picked the note's aggregate row `Cộng` (score 1.0) instead of the named component row. |
| 263 | wrong row candidate | lexical overlap won over semantics: `Lỗ và ghi nhận chênh lệch đánh giá ... tài sản tài chính` instead of `Các tài sản tài chính FVTPL (mã 112)`, and column `Năm nay` instead of `Số cuối năm`. |
| 55 | wrong row candidate | total-vs-component: `D. VỐN CHỦ SỞ HỮU (400 = 410 + 420)` for a question about `Vốn cổ phần`. Only planner-side regression. |
| 732 | unsupported request shape accepted | question is a ratio of two metrics (`gấp ... bao nhiêu lần`); the request was built as single-slot `operation=direct` with `target_unit=ratio` and returned one raw cell. The phase-1 ratio gate declined 6 other questions but not this one. |

`792` is counted correct at 1% tolerance but read a slightly wrong cell (234305 vs 234471) —
treat it as a latent miss, not a win.

## Side measurement: what the codegen grid prompt actually costs

Reconstructed with `build_prompt` over `diag.evidence_tables` of the control run (73 questions,
227 tables shown):

| Constant | Where | Measured effect on gold |
|---|---|---|
| `codegen_max_tables = 3` (5 multi-year) | `config.py:114,124` | retrieved pool is median 14, max 53 → the model sees ~21% of what retrieval found. **15 of 59 labelled questions lose a gold table to this slice; 9 of them answer wrong** (488, 521, 525, 530, 542, 553, 685, 856, 920). 6 stay correct (18, 45, 337, 586, 732, 770). |
| `_MAX_GRID_ROWS=60`, head 40 / tail 15 | `context.py:39-40` | never fires: 0 of 227 tables shown exceed 60 rows. Dead constant on this set. |
| `max_colwidth=70` | `context.py:83-85` | 116 of 16,937 shown cells are cut (0.7%), and they are long Vietnamese `chỉ tiêu` labels — exactly where the distinguishing words sit. |

Prompt size is p50 7,853 chars (~2.6k tokens), p90 14k, max 24k, against `max_model_len=262144`.
The 3-table cut is therefore **not** a context-window constraint (~1% of the window used); it is
the accuracy tradeoff recorded in `docs/DECISIONS.md` section 4 (3 -> 10 scored 33 -> 29).

There is no cell *search* on the codegen path: retrieval ranks, Python slices the top 3, the model
reads grids. The mechanism that would be search — `FindRows`/`ShowTable` in `codegen.py:189-227` —
is gated off by `SOLVE_TOOL_TURNS=0`, and its only measurement (44/94 vs 43/94 vs 42/94) is on the
94-question low-confidence set, not this one.

## Candidate next changes (general, no question-id rules)

Ranked by evidence, all Python-side validation:

1. `source_unit == "unknown"` must not be silently scaled. Either propagate the page/table unit
   into the linker solution the way codegen's detector does, or fail closed. Silent 1e6 class of
   error; `unknown` also appears on `55`, `262`, `732`.
2. Refuse a chosen cell whose value is `0.0`/blank instead of submitting it.
3. Refuse `target_unit == "ratio"` (ratio-of-two-metrics wording) when the request is single-slot
   `direct`, so it joins the existing phase-1 ratio gate.
4. Raise the deterministic branch's bar and defer to the planner when a competing candidate in a
   different row/column family is within a small score margin. Measured support: planner sources
   are 7/10, deterministic is 8/14 and owns 5 of 6 regressions. Do not encode Vietnamese
   aggregate-row keyword lists.
