# Formula Facts Status

## Muc tieu

Nhanh nhat de giam phu thuoc codegen cho Type 2/3 la mot nhanh opt-in over
`data/derived/long_format.parquet`: LLM chi dien schema nho, Python tinh metric
catalog va unit conversion. Khong them rule theo qid/cau hoi.

Flow khi bat flag:

```text
understand -> retrieve -> solve_single_cell -> solve_formula_facts -> codegen fallback
```

Flag:

```bash
SOLVE_FORMULA_FACTS=1
```

## Da lam

- Them `src/finance_qa/modules/solve/formula_facts.py`.
  - Schema `FormulaPlannerOutput` chi cho phep `lookup`, `ratio`, `growth`,
    `diff`, `avg`, `median`.
  - Executor dung lai catalog/fact access cua `structured_facts.execute_plan`.
  - Fail closed neu thieu ticker/year, selection marker, metric khong anchor
    trong text, target unit sai, primitive thieu coverage.
  - Pre-gate cac metric ngoai main-statement facts: segment revenue/profit/cost,
    borrowings/short-term loans, fixed assets/deferred tax/securities/provisions.

- Noi vao graph bang config rieng:
  - `SOLVE_FORMULA_FACTS`
  - `SOLVE_FORMULA_FACTS_PLANNER_THINKING`

- Mo rong alias catalog tong quat:
  - `gross_margin`: them "ty suat loi nhuan gop"
  - `net_margin`: them "ty suat loi nhuan rong"
  - Type 2 ratio moi:
    - `cogs_to_revenue = cogs / net_revenue`
    - `pretax_margin = profit_before_tax / net_revenue`
    - `net_profit_to_total_assets = net_profit / ending_total_assets`
    - `current_liabilities_to_equity = current_liabilities / equity`
    - `cfo_to_profit_before_tax = cfo / profit_before_tax`
    - `debt_to_assets`: them alias "no tren tong tai san"

- Them deterministic Type 2 planner truoc LLM planner:
  - Chi nhan one ticker + one year + exactly one anchored ratio metric.
  - Type 3 period-pair sau do duoc mo rat hep: one ticker + exactly two years
    + exactly one anchored money metric + growth/diff cue ro rang.
  - Khong deterministic hoa avg/median hoac Type 4/5 trong buoc nay.
  - Neu metric/coverage khong ro thi fallback sang planner/codegen.

- Them `tests/test_formula_facts.py`.

## Ket qua do duoc

Smoke:

```text
q586: formula_facts, dung growth cash_and_equivalents
q644: fallback codegen, segment revenue
q663: fallback codegen, borrowings ratio
q674: formula_facts, dung net_margin sau khi them alias
```

Gold73 run current sau pre-gate/alias:

```text
artifacts/runs/formula_facts_gold73_final.jsonl
score: 43/73 vs cell_locator_1012 39/73
```

Doc dung: +4 nay khong phai formula_facts-only win. Trong run do
`formula_facts` tra loi 3 cau va dung 3/3 (`q18`, `q337`, `q586`), nhung cac
head-to-head wins so voi `cell_locator_1012` la live churn o codegen/cell_locator
(`q327`, `q752`, `q754`, `q871`). Khong co formula-only win tren gold73.

Smoke sau pre-gate:

```text
static gate: 153/1012 cau co the attempt
smoke4: q586 va q674 formula_facts dung; q644/q663 fallback dung
```

Type 2 deterministic smoke:

```text
static supported: 8/1012, all ratio, all derived, one ticker + one year
supported ids: 662,674,678,686,694,710,718,719
graph smoke before bank fallback: 6/8 solved by formula_facts; q694/q719 fallback vi long_format thieu primitive separate fact
gold among smoke: q674 correct
artifact: artifacts/runs/type2_formula_smoke8_v2.jsonl
```

Important semantic fix: text "loi nhuan sau thue tren tong tai san cuoi nam" is
not ROA average-assets. It maps to `net_profit_to_total_assets`, while `roa`
keeps average total assets.

Bank/no-ma-so fallback:

```text
Long_format van giu nguyen la ma-so fact table. Khi lookup primitive miss,
StatementFactStore co fallback doc raw bank BS/IS/CF khong co cot Ma so bang
canonical row label, convert ve VND bang unit detector, va tra ve cung Fact API.

Supported primitive bank labels hien tai:
total_assets, liabilities, equity, interest_expense, profit_before_tax,
net_profit, cfo.

Graph smoke:
artifact: artifacts/runs/type2_bank_fallback_smoke.jsonl
q694: formula_facts -> 81.53201278754366
q719: formula_facts -> 22199.207772795216

Type 2 deterministic sau fallback:
static supported: 8/1012
direct execute: 8/8
graph smoke full slice: 8/8 solved by formula_facts
artifact: artifacts/runs/type2_formula_smoke8_bank_fallback.jsonl

Type 3 deterministic period-pair:
static supported moi: q584 diff equity, q586 growth cash_and_equivalents
detail blockers: q609 collateral/discount wording, q623 raw-material inventory
direct execute total deterministic slice: 10/10
graph smoke: 10/10 solved by formula_facts
artifact: artifacts/runs/type2_type3_formula_smoke10.jsonl

Gold73 opt-in sau Type 3 + bank fallback:
artifact: artifacts/runs/formula_facts_gold73_after_type3_bank.jsonl
score_gold75: 41/73, thap hon artifact cu formula_facts_gold73_final 43/73
formula_facts solver: 4/4 dung (q18, q45, q337, q586)
cell_locator solver: 7/7 dung
codegen solver: 30/62 dung
churn am so voi artifact cu: q327, q754. Ca hai khong do formula_facts tra sai:
q327 ve lai baseline cell_locator_1012 vi cell_locator confidence below threshold;
q754 la live codegen chon cong thieu/thua dong trong bang note bank.
So voi cell_locator_1012, run moi van +2 cau (q752, q871).

Type 4 deterministic multi-entity diff:
Router moi chi nhan: exactly 2 tickers + exactly 1 year + exactly 1 money
metric anchor + diff cue ro (`chenh lech`, `hieu so`, `hon`) + khong co
detail/note blocker. Huong tru theo thu tu ticker da resolve theo vi tri trong
question.

Static supported sau khi them Type 4: 18/1012
- 8 Type 2 ratio cu
- 2 Type 3 period-pair cu
- 8 Type 4 multi-entity diff moi: q734, q737, q767, q770, q776, q783, q799, q808

False-positive blockers them sau static scan:
- `lai vay phai tra` chan q601 (interest payable note, khong phai IS interest expense)
- `nguoi ban` chan q801 (vendor payable note, khong phai total liabilities)

Direct execute supported slice: 17/18, fail q783 do thieu EIB 2023 bank total
assets fact trong fact store; graph fallback ve codegen nhu thiet ke.

Graph smoke:
artifact: artifacts/runs/type4_entity_diff_smoke11.jsonl
formula_facts: q734, q737, q767, q770, q776, q799, q808
fallback codegen: q601, q754, q783, q801
score_gold75 on smoke: 1/2 (q770 dung, q754 codegen sai va duoc blocker giu ngoai fact solver)

Gold73 opt-in sau Type 4:
artifact: artifacts/runs/formula_facts_gold73_after_type4_entity_diff.jsonl
score_gold75: 40/73
formula_facts solver: 5/5 dung (q18, q45, q337, q586, q770)
cell_locator solver: 7/7 dung
codegen solver: 28/61 dung
So voi run Type 3, mat q752 do live codegen churn; Type 4 khong gay formula_facts
wrong-answer tren gold73.

Capability router trace:
Them `src/finance_qa/modules/solve/capability_router.py` va graph node
`trace_capabilities` sau retrieve. Node nay chi ghi `diag.capability_router`,
khong doi route behavior. Trace dung guard hien co:
- cell_locator: `build_request`
- formula_facts: `should_attempt_formula_facts` + deterministic plan neu co
- structured_facts: planner-gated branch khi config bat
- selection_decompose: `axis_of`
- codegen: fallback

Smoke:
artifact: artifacts/runs/capability_router_smoke2.jsonl
q770: formula_facts attempt=true, deterministic diff equity GAS-POW
q754: formula_facts attempt=false, reason note-like metric outside main-statement facts
```

Capability failure audit:
Them `scripts/report_capability_failures.py`, report doc-only tren run JSONL +
gold labels. Artifact:

```text
artifacts/audits/capability_failures_gold73_after_type4.jsonl
run: artifacts/runs/formula_facts_gold73_after_type4_entity_diff.jsonl
score_gold73: 40/73
```

Miss buckets:

```text
wrong_gold_used: 18
zero_answer: 7
wrong_gold_retrieved_not_used: 4
wrong_no_gold_retrieved: 4
```

Ket luan do duoc: bucket lon nhat la bang dung da duoc dung/show nhung doc/tinh
sai cell, nen answer bottleneck hien tai nghieng ve table understanding/cell
selection + table normalization hon la retrieval thuan. `cell_locator` 7/7 dung
va `formula_facts` 5/5 dung tren gold slice ma chung dam tra loi; codegen fallback
28/61.

Table profile + normalization:
Them `src/finance_qa/modules/solve/table_profile.py` lam deterministic typed map
cho mot bang: cot label/code/numeric, nam/unit suy luan, row label theo `.iloc`,
metric candidates neu match catalog, quality flags. Chua bat vao prompt mac dinh.

Trong luc profile cac miss `wrong_gold_used`, phat hien q120 khong chi la LLM doc
sai: `load_frame` parse layout bank bi lech, cot `Thuyet minh` dang chua so tien
nam hien tai vi hang data mat cell STT. Da sua `repair_shifted_bank_header` cho
pattern tong quat: header co `STT, Chi tieu, Thuyet minh, ...`, cot dau data la
label dai, cot ke la note ngan, cot cuoi gan rong thi dich header trai va bo cot
rong. Smoke:

```text
artifacts/runs/q120_after_stt_shift_fix.jsonl
q120: codegen -> 1041601.0, dung gold
Re-execute artifact gold73 cu bang pandas query cu tren load_frame moi:
40/73 -> 41/73, chi flip q120 sai -> dung, khong thay loss trong 73 gold.
Scan cac table xuat hien trong gold run thay pattern STT-shift nay 1 lan
(`KLB_financial_statements_2019_consolidated|8`), nen day la fix sach nhung
khong phai truc scale lon.
```

Live gold73 sau STT-shift fix:

```text
artifact: artifacts/runs/gold73_after_stt_shift_fix_live.jsonl
score_gold73: 44/73
audit: artifacts/audits/capability_failures_gold73_after_stt_shift_fix_live.jsonl
head-to-head vs formula_facts_gold73_after_type4_entity_diff:
  wins: q120, q526, q752, q754
  losses: none
```

Doc dung: q120 la win chac chan tu normalization fix (re-execute query cu cung
flip dung). q526/q752/q754 la live codegen churn co loi, khong gan credit cho
STT-shift/table_profile.

Table profile prompt treatment:
Noi `table_profile_context` vao `codegen.build_prompt` sau moi evidence grid bang
flag `SOLVE_TABLE_PROFILES=1`; mac dinh tat. Treatment chi them context prompt,
khong doi executor/route.

Targeted run tren 16 cau `wrong_gold_used` cua live audit:

```text
artifact: artifacts/runs/table_profiles_wrong_gold_used16.jsonl
audit: artifacts/audits/capability_failures_table_profiles_wrong_gold_used16.jsonl
baseline live slice: 0/16
profile prompt slice: 0/16
wins/losses: none/none
```

Ket luan: profile prompt co thay doi mot so answer va co vai cau gan hon, nhung
khong tao win. Khong nen bat full/default. Buoc tiep dung profile nen la
deterministic validator/locator hoac typed selection DSL, khong phai chi them text
vao prompt codegen.

Profile validator diagnostic:
Them `src/finance_qa/modules/solve/profile_validate.py` va flag
`SOLVE_PROFILE_VALIDATE=1`. Node chay sau `verify_answer`, doc final
`pandas_query`, parse cac mau `.iloc[...]`, map ve `TableProfile`, roi ghi
`diag.profile_validate`. No khong sua answer/query/evidence.

Audit offline tren live artifact hien tai, khong goi lai LLM:

```text
script: scripts/report_profile_validate.py
input: artifacts/runs/gold73_after_stt_shift_fix_live.jsonl
out high: artifacts/audits/profile_validate_gold73_after_stt_shift_fix_live.jsonl
out low: artifacts/audits/profile_validate_gold73_after_stt_shift_fix_live_low.jsonl

--min-confidence low:
scored 73, correct=44, wrong=29
any finding: correct=9, wrong=10
strong finding: correct=0, wrong=5
strong codes on wrong:
  execution_failed: 4
  zero_answer_untrusted: 4
  non_numeric_column_read: 1
```

Mot false-positive ban dau la q262: query doc `So dau nam` nhung answer dung vi
bang SJG 2019 bi lech layout, value cuoi nam dang nam duoi header `So dau nam`.
Da ha severity `column_year_mismatch` xuong weak khi profile co dau hieu shifted,
note/wide table. Ket luan hien tai: strong signal du sach de lam repair cho
execution/zero truoc; chua du de auto-repair row/year mismatch.

Type 2-4 audit va avg/median extension:
Them `scripts/audit_formula_type234.py` de tach simple formula shapes khoi
selection/note/detail. Audit tren artifact cu:

```text
input: artifacts/runs/gold73_after_stt_shift_fix_live.jsonl
out: artifacts/audits/formula_type234_after_financial_income_avg_on_oldrun.jsonl

type2_fixed_ratio: q674, deterministic_supported=True, artifact cu missing
type3_two_year_growth: 2/2 dung
type4_two_ticker_diff: 1/1 dung
avg_median_candidate: q820, deterministic_supported=True sau patch
```

Da them primitive `financial_income` (ma so 21, alias "doanh thu hoat dong tai
chinh") va deterministic avg/median cho 1 ticker + >=2 nam + 1 money metric +
cue trung binh/binh quan/trung vi. Targeted probes:

```text
q674 graph: formula_facts -> 5.275890245889254, OK
q820 graph before unit fix: formula_facts -> 406.90370993740004, sai scale
q820 graph after unit fix: formula_facts -> 4.069037099374, OK
slice q586,q674,q770,q820: formula_facts 4/4 dung theo gold/scored slice
```

Unit bug found while doing q820: `understand.unit_hint` co the mat "tram" va chi
giu "ty". Da sua target-unit resolve de plan target/question goc thang unit_hint
lossy trong fact executors, va `execute.apply_units` de question goc thang
unit_hint trong codegen scaling. Them regression test "tram ty" trong
`tests/test_solve_units.py`.

Khong them alias rong `loi nhuan thuan`: trong 1012 cau co nhieu nghia khac nhau
(sau thue, phan bo co dong, hoat dong tai chinh, note EPS). q753 Type4 bank diff
khong the giai bang long_format hien tai vi `VIB/MSB 2017 separate` khong co
facts trong long_format, nen can raw-table/TableProfile locator, khong phai mo
PRIMITIVES don gian.

## Ket luan

Nhanh nay hien tai co deterministic slices nho va kiem soat duoc: Type 2 ratio,
Type 3 growth/diff/avg/median main-statement, Type 4 main-statement diff, cong
voi fallback bank/no-ma-so cho primitive main-statement. Khi formula_facts tra loi
thi precision van cao trong targeted probes, nhung diem tong van bi gioi han boi
retrieval/cell selection/codegen tren bang note, bank/detail, va selection. Buoc
tiep theo hop ly: khong mo alias mo ho; xay raw-table/TableProfile locator cho
Type 4 detail/bank diff hoac profile-guided repair cho zero/execution.
