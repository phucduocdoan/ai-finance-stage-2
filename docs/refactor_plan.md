# Refactor Plan

Muc tieu: lam codebase de doc, de debug, va de tiep tuc cai tien score ma khong lam mat baseline hien co. Refactor phai di theo huong giu behavior truoc, doi kien truc sau, va moi buoc deu co test.

## Current Diagnosis

Code production khong co nhieu module chet ro rang trong `src`. Van de chinh la mot so file qua lon va gom nhieu trach nhiem:

- `src/finance_qa/modules/solve/solvers/raw_table_linker.py`: schema, request parsing, candidate build, scoring, LLM planner, validation, va render query trong cung mot file.
- `src/finance_qa/modules/solve/facts/structured_facts.py`: metric catalog, fact store, planner schema, executor, selection/aggregate logic trong cung mot file.
- `src/finance_qa/agents/finance/graph.py`: graph topology, node wrappers, codegen path, solver wrappers, verify, va emit/bookkeeping trong cung mot file.
- `src/finance_qa/agents/finance/config.py`: production flags, experiment flags, va lich su do dac dai dang nam chung.

Workspace cung bi nhieu boi boi artifact:

- `sofier_AI_FINANCE_snapshot/` va `sofier_work/` rat lon, chi nen giu neu con can doi chieu.
- `output/` co nhieu submission/probe cu, mot so artifact hybrid khong phai output thuan tu pipeline.
- `artifacts/runs/` co rat nhieu run jsonl/log cu, nen archive theo manifest thay vi de ngang trong workspace.

## Guardrails

- Khong rewrite thuat toan trong cung commit voi refactor cau truc.
- Khong xoa file/artifact lon khi chua co danh sach "keep" va ly do giu.
- Sau moi buoc phai chay test lien quan.
- Khong claim score khong doi neu chua chay lai eval tuong ung.
- Baseline submission/run can giu de rollback va doi chieu.

Minimum keep set hien tai:

- `output/submission_v17_unitfix.zip`
- `output/submission_v22_hybrid_answer_retrieval_with_data.zip`
- Run JSONL dung de reproduce baseline neu con tren may, vi du `artifacts/runs/full1012_v17_unitfix.jsonl`

## Phase 0 - Freeze Baseline

Muc tieu: co diem neo truoc khi refactor sau.

Tasks:

- Ghi lai artifact nao la baseline nhe nhat de nop va artifact nao chi la probe.
- Tao manifest cho output/artifacts can giu.
- Chay validation package cho submission giu lai: so record, id 1..1012, answer float, evidence csv ton tai.
- Chay test suite nho dang dung lam gate.

Verification:

```bash
rtk env PYTHONPATH=src .venv_bge/bin/python -m compileall src scripts tests
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_solver_router.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_solver_outcome.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_codegen_budget.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_solve_units.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_cell_locator.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_table_linker.py
rtk env PYTHONPATH=src .venv_bge/bin/python tests/test_raw_selection_linker.py
```

## Phase 1 - Split Graph Orchestration

Muc tieu: `graph.py` chi con topology va public entrypoints.

Da lam mot phan:

- `src/finance_qa/modules/solve/pipeline/router.py`
- `src/finance_qa/modules/solve/pipeline/outcome.py`
- `src/finance_qa/modules/solve/pipeline/evidence.py`
- `src/finance_qa/modules/solve/pipeline/emit.py`
- `src/finance_qa/modules/solve/pipeline/nodes/codegen.py`
- `src/finance_qa/modules/solve/pipeline/nodes/verify.py`
- `src/finance_qa/modules/solve/pipeline/nodes/solvers.py`
- `src/finance_qa/modules/solve/codegen/legacy.py`

Next tasks:

- Chuyen sang Phase 2: normalize solver contract/debug schema.
- Giu compatibility exports trong `agents.finance.graph` cho entrypoints va script cu.
- Khong xoa wrapper compatibility cho toi khi khong con script ngoai nao phu thuoc.

Expected end state:

```text
agents/finance/graph.py
  build_graph()
  make_initial_state()
  get_graph()
  arun_question()
  run_question()

modules/solve/pipeline/
  router.py
  outcome.py
  evidence.py
  emit.py
  nodes/
    codegen.py
    solvers.py
    verify.py
```

## Phase 2 - Normalize Solver Contract

Muc tieu: moi solver node tra ve mot contract debug giong nhau.

Current direction:

```text
status: done | declined | error
done: bool
reason: str
solver: str
diag: dict
errors: list[str]
```

Da bat dau:

- Them helper `append_unique()` va `answered()` trong `pipeline/outcome.py`.
- `declined()` / `errored()` van la duong chuan cho fail-safe va exception.
- `structured_facts`, `selection_facts`, `formula_facts` da dung `answered()`
  cho success path, nen `solver`, `errors`, `diag[solver].status`, `done`,
  `frames`, `names`, `evidence_tables`, `codegen_prompt`, `solution` duoc
  dong goi o mot cho.
- `emit_result()` co keyword `solver=...`, giup raw linker va cell locator
  khong can emit bang `codegen` roi override lai `solver` thu cong.
- Them `emit_solver_result()` trong `pipeline/emit.py` cho cac solver co mau:
  prepare/locate -> `aexecute()` -> emit. `raw_table_linker`,
  `raw_selection_linker`, va `cell_locator` da dung helper nay cho success path.
- Test da cover helper contract, fact-solver success contract, router status,
  emit solver name, va success packaging cua raw/cell solver bang fake node
  khong goi LLM.
- Them `tests/test_solver_contract.py` de audit invariant chung:
  `decline/error/success` deu co `diag[solver].status`, `done`, va `reason`
  dang string. Test nay cover helper, formula success, cell decline, raw-table
  error, va selection success bang fake node khong goi LLM.

Tasks:

- Mo rong tiep `SolverOutcome` neu can them field `answer`, `pandas_query`,
  `table_ids`, `evidence`, `frames`, `names`.
- Chuyen tiep success path cua `selection` sang helper chung neu lam duoc ma
  khong doi shape output.
- Dam bao router chi doc contract, khong doc shape rieng cua tung solver.
- Ghi `status` vao trace de khi doc JSONL biet solver fail-safe hay crash.

Khong nen lam o phase nay:

- Khong doi logic candidate scoring.
- Khong doi prompt.
- Khong bat/tat flag mac dinh.

## Phase 3 - Split Raw Table Linker

Muc tieu: cat file lon nhat thanh cac module theo trach nhiem.

Da bat dau:

- Tao `src/finance_qa/modules/solve/solvers/raw_table_linking/`.
- Chuyen decision/planner schemas va `RawTableLinkError` sang
  `raw_table_linking/schema.py`.
- Chuyen request inference, operation gating, scope filtering helpers, va raw
  tokenization sang `raw_table_linking/request.py`.
- Chuyen text/scoring helpers sang `raw_table_linking/scoring.py`.
- Chuyen cell/group candidate builders sang `raw_table_linking/candidates.py`.
- Chuyen prompt rendering helpers sang `raw_table_linking/render.py`.
- Chuyen structured LLM planner calls sang `raw_table_linking/planner.py`.
- Giu `raw_table_linker.py` import/re-export cac ten cu de test/script hien tai
  van dung `from finance_qa.modules.solve.solvers import raw_table_linker as raw`.
- Giu compatibility wrapper trong `raw_table_linker.py` cho cac test/script cu
  dang monkeypatch `raw.meta_for`, `raw.table_metadata`, `raw.load_frame`,
  hoac `raw.get_chat_model`.
- Da verify compile, `tests/test_raw_table_linker.py`,
  `tests/test_raw_selection_linker.py`, `tests/test_capability_router.py`, va
  cac test `table_linking`.
- Chuyen ratio option building (deterministic ratio option decision,
  ratio side/label helpers) sang `raw_table_linking/ratio_options.py`.
- Chuyen deterministic/semantic decision (normalize planner decision,
  search-expansion coverage check) sang `raw_table_linking/decision.py`.
- Chuyen validation (`validate_decision`, `validate_ratio_decision`,
  `ratio_decision_from_options`) sang `raw_table_linking/validate.py`.
- Chuyen `build_solution` / `build_ratio_solution` sang
  `raw_table_linking/solution.py`, voi dependency injection cho
  `frame_loader`, `scale_expression_func`, `validate_decision_func`,
  `validate_ratio_decision_func`, `candidate_table_ids_func`,
  `candidate_query_func`, `candidate_first_cell_func` de wrapper trong
  `raw_table_linker.py` van truyen `load_frame` module-level, giu
  monkeypatch `raw.load_frame` trong test hoat dong dung.
- `raw_table_linker.py` giam tu 1933 xuong 747 dong. Phan con lai chu yeu la
  `aprepare_raw_table_linker` (prepare orchestration) va cac thin wrapper
  export cho cac module con lai.
- Da verify compile, full Phase 0 gate list, va cac test
  `table_linking`/`raw_table_linker`/`raw_selection_linker`/
  `capability_router`/`solver_contract` sau moi buoc tach (ratio_options,
  decision, validate, solution).
- Chuyen `aprepare_raw_table_linker` sang `raw_table_linking/prepare.py`, voi
  dependency injection cho toan bo ~18 callable no goi (build_request_func,
  build_ratio_candidates_func, build_candidates_func,
  prefer_ratio_option_surface_func, build_ratio_options_func,
  deterministic_ratio_option_decision_func, ratio_decision_from_options_func,
  aplan_raw_ratio_options_func, aplan_raw_ratio_linker_func,
  build_ratio_solution_func, candidate_table_ids_func,
  deterministic_decision_func, aplan_raw_search_func,
  request_with_search_plan_func, search_expansion_adds_slot_coverage_func,
  aplan_raw_table_linker_func, normalize_planner_decision_func,
  build_solution_func). Default cua moi param tro thang toi ham submodule
  goc (vi du `_request.build_request`), vi cac ham submodule nay da tu mang
  default DI dung (meta_for/table_metadata/load_frame/get_chat_model/...)
  giong het cach facade dang truyen - da doi chieu tung ham de xac nhan.
  Wrapper trong `raw_table_linker.py` truyen ten module-level hien tai cua
  chinh no cho ca 18 param, giu monkeypatch (`raw.load_frame`,
  `raw.aplan_raw_search`, ...) hoat dong dung trong test.
- `raw_table_linker.py` giam tu 747 xuong 602 dong.
- Da verify compile va toan bo gate list: `test_raw_table_linker`,
  `test_table_linking_columns`, `test_table_linking_rows`,
  `test_table_linking_schema`, `test_raw_selection_linker`,
  `test_capability_router`, `test_solver_contract`, cong voi
  `test_solver_router`, `test_solver_outcome`, `test_codegen_budget`,
  `test_solve_units`, `test_cell_locator`, `test_table_profile`,
  `test_profile_validate`, `test_solver_nodes`, `test_solver_emit`,
  `test_structured_facts`, `test_formula_facts`, `test_selection_facts`
  (3 test cuoi can chay bang `.venv_bge/bin/python` vi duckdb chi co trong
  venv do, khong lien quan gi den thay doi cua buoc nay).

Target layout:

```text
modules/solve/solvers/raw_table_linking/
  schema.py
  request.py
  candidates.py
  scoring.py
  ratio_options.py
  planner.py
  decision.py
  validate.py
  render.py
  prepare.py
```

Order:

1. Move schema/classes first, no behavior change. Done.
2. Move request inference and operation gating. Done.
3. Move candidate build/scoring. Done.
4. Move planner calls. Done.
5. Move ratio options, decision, validation, and solution building. Done.
6. Move prepare orchestration (`aprepare_raw_table_linker`) to `prepare.py`. Done.
7. Keep `raw_table_linker.py` as compatibility facade until imports are migrated. Done.

Verification:

- `tests/test_raw_table_linker.py`
- `tests/test_table_linking_columns.py`
- `tests/test_table_linking_rows.py`
- `tests/test_table_linking_schema.py`

## Phase 4 - Split Structured Facts

Muc tieu: tach catalog/fact store/planner/executor de selection_facts va formula_facts de tai su dung hon.

Da lam:

- Tach `metrics.py` (PRIMITIVES/DERIVED_ALIASES/METRIC_KEYS/EXPRESSION_ALIASES,
  `canonical_metric`, `canonical_measure`, `metric_source_unit`, `metrics_in_text`).
- Tach `schema.py` (StructuredPlan, StructuredSelectionPlan,
  StructuredPlannerOutput, MetricFilter, cac Literal type cho planner).
- Tach `store.py` (Fact, StructuredFactError, StatementFactStore, default_store,
  bank-label fallback helpers).
- Tach `execute.py` (execute_plan, supported_v1_plan, _execute_selection,
  _execute_aggregate, va cac helper unit/filter).
- Tach `planner.py` (aplan_structured, normalize_plan, heuristic_plan,
  asolve_structured_facts).
- `structured_facts.py` giam tu 1666 xuong 65 dong, chi con la facade re-export.
  Khong can dependency-injection wrapper nhu raw_table_linker vi khong co test
  nao monkeypatch attribute cua `structured_facts` (da verify bang grep).
- Da verify compile va toan bo test lien quan: `test_structured_facts`,
  `test_formula_facts`, `test_selection_facts`, `test_table_profile`,
  `test_profile_validate`, cong voi full Phase 0 gate list va
  `test_capability_router`/`test_solver_contract`.

Target layout:

```text
modules/solve/facts/
  metrics.py
  schema.py
  store.py
  execute.py
  planner.py
  structured_facts.py  # compatibility facade
```

Order:

1. Move metric aliases and canonicalization to `metrics.py`. Done.
2. Move `Fact` and `StatementFactStore` to `store.py`. Done.
3. Move plan schemas to `schema.py`. Done.
4. Move `execute_plan` and helpers to `execute.py`. Done.
5. Move LLM planner (`aplan_structured`, `heuristic_plan`, `asolve_structured_facts`)
   to `planner.py`. Done.
6. Keep old public exports in `structured_facts.py`. Done.

Verification:

- `tests/test_structured_facts.py`
- `tests/test_formula_facts.py`
- `tests/test_selection_facts.py`
- `tests/test_table_profile.py`
- `tests/test_profile_validate.py`

## Phase 5 - Codegen Plan Path

Muc tieu: giam quyen tu do cua LLM codegen. LLM chon plan/cell, Python render pandas.

Keep:

- Legacy expression codegen as fallback.
- Existing executor/unit/repair path.

Add:

```text
modules/solve/codegen/
  schema.py
  plan_generate.py
  render.py
  validate.py
  repair.py
  legacy.py
```

Proposed schema:

```text
CellRef
  variable
  table_id
  row_idx
  column
  role
  source_unit

SolvePlan
  answer_kind
  operation
  operands
  target_unit
```

Rollout:

1. Lookup only.
2. Sum/diff/ratio.
3. Growth.
4. Argmax/min and selected-year/selected-value.
5. Multi-company/filter later.

Validation should catch:

- Question asks year but answer is amount.
- Question asks total but chosen row is component.
- Question asks separate/consolidated but doc type mismatches.
- Question asks beginning/end period but column period mismatches.
- Query/evidence variable mismatch.
- Query executes but value does not match submitted answer.

## Phase 6 - Config Cleanup

Muc tieu: config de doc, khong chon giua production va experiment bang comment dai.

Target:

```text
agents/finance/config.py
  FinanceAgentConfig
  production defaults

agents/finance/experiments.py
  experiment flag descriptions
  measured result notes
```

Tasks:

- Giu default/env var o config.
- Move historical measurement comments to docs.
- Group flags:
  - retrieval
  - solver production
  - codegen production
  - experiment/probe
  - verification/package

Da lam:

- Thay vi tach `experiments.py`, chuyen toan bo comment do luong dai (dense_backend,
  judge_thinking, ca 5 flag cua "measured solver stack", codegen_max_tables*,
  selection_decompose, repair_history, screening_solver, v.v.) sang
  `docs/config_flags.md`, moi field co section rieng theo dung ten field, group
  giong het 5 nhom trong dataclass.
- `FinanceAgentConfig` van la MOT dataclass duy nhat (khong tach 2 class, khong
  doi API/shape) - chi sap xep lai thu tu ~34 field vao 5 comment-section
  (`# retrieval`, `# solver production`, `# codegen production`,
  `# experiment / probe`, `# verification / package`), moi field con lai 1-2
  dong comment ngan tro toi section tuong ung trong `docs/config_flags.md`.
- Verify an toan truoc khi doi thu tu field: grep toan bo `FinanceAgentConfig(`
  trong `src/scripts/tests`, khong co call site nao dung positional args (chi
  `FinanceAgentConfig()` hoac keyword-only) - nen reorder khong doi behavior.
  Doi chieu ten field, type, default value, ten env var giua ban cu/moi bang
  script doi chieu tu dong (34/34 khop).
- Verify compile + test gate: `test_codegen_budget`, `test_solver_router`,
  `test_solver_nodes`, `test_solver_contract`, `test_profile_validate`,
  `test_solve_units`, `test_codegen_nodes`, `test_raw_table_linker`,
  `test_table_linking_columns`, `test_table_linking_rows`,
  `test_table_linking_schema`, `test_raw_selection_linker`,
  `test_capability_router`, `test_solver_outcome`, `test_cell_locator`,
  `test_table_profile`, `test_solver_emit`, cong `test_structured_facts`,
  `test_formula_facts`, `test_selection_facts` (3 test cuoi bang
  `.venv_bge/bin/python` vi duckdb chi co trong venv do).

## Phase 7 - Workspace Cleanup

Muc tieu: giam nhieu workspace nhung khong mat reproducibility.

First create manifest:

```text
docs/artifact_manifest.md
  keep submissions
  keep runs
  disposable outputs
  disposable snapshots
```

Safe cleanup candidates:

- `__pycache__/`
- `.pytest_cache/`
- old `output/submission_probe*`
- broken hybrid zips without data, especially `submission_v18` through `submission_v21`

Ask before deleting:

- `sofier_AI_FINANCE_snapshot/`
- `sofier_work/`
- `artifacts/runs/*`
- old full submission dirs whose zip may still be useful for comparison

## Definition Of Done

Refactor is acceptable when:

- Entry commands in README still work.
- Test gate passes.
- `run_graph.py --ids ...` still produces JSONL with the same schema.
- `build_submission.py` still packages top-level `submission.json` and `data/`.
- For behavior-preserving phases, selected smoke qids have identical solver/answer/query, except only diag gaining new `status` fields.
