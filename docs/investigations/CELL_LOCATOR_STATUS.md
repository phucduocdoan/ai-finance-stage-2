# Cell Locator Status

## Muc tieu

Buoc nay khong sua prompt codegen de hy vong model doc dung hon. Muc tieu la tach mot lop
deterministic nho cho cau hoi L1: neu cau hoi chi can doc mot cell, he thong tu xac dinh
row/column/cell va chi de pandas executor lam viec con lai nhu parse so va doi don vi.

Huong nay giu LLM o vai tro semantic preprocess: understand ticker, year, broad metric, unit.
Phan locate va execute khong de LLM tu sinh logic tuy tien.

## Da lam

- Them `src/finance_qa/modules/solve/cell_locator.py`.
  - Khai bao schema Pydantic `CellRequest` va `CellHit`.
  - Gate rat bao thu: chi nhan cau hoi mot ticker, mot nam, dang lookup cell.
  - Tu choi cau hoi derived/comparison/ratio/growth/argmax/argmin.
  - Match row bang phrase trong cau hoi + alias metric tong quat.
  - Match column bang nam, dau ky/cuoi ky, annual/current/prior.
  - Fallback neu gan hoa, khong ep chon cell khi ambiguous.

- Sua/bo sung `src/finance_qa/modules/solve/lookup.py`.
  - Them `label_column(df)` de nhan dien cot chi tieu that.
  - Ly do: nhieu bang co cot dau la `STT`/ma hang, label thuc nam o cot sau.
  - Row search gio dung cot label thay vi mac dinh cot dau tien.

- Noi vao graph theo co cau opt-in.
  - Them flag `SOLVE_CELL_LOCATOR=1`.
  - Mac dinh van OFF.
  - Flow khi bat flag:

```text
understand -> retrieve -> solve_single_cell -> verify_answer
                              \-> structured/selection/codegen fallback
```

- Them test:
  - `tests/test_cell_locator.py`
  - `tests/test_solve_lookup.py`
  - Kiem tra label column sau STT, chon cot dau/cuoi ky, sign expense, cash-flow signed,
    khong add alias lung tung, chan ty trong/derived, chan total-vs-component, fallback khi gan hoa.

- Them script audit:
  - `scripts/report_gold_types.py`
  - Muc dich: chia score theo level/proxy type va theo solver de biet sai o dau.

## Ket qua do duoc

Command da verify:

```bash
PYTHONPATH=src .venv_bge/bin/python tests/test_cell_locator.py
PYTHONPATH=src .venv_bge/bin/python tests/test_solve_lookup.py
PYTHONPATH=src .venv_bge/bin/python tests/test_solve_units.py
PYTHONPATH=src .venv_bge/bin/python tests/test_metric_hints.py
PYTHONPATH=src .venv_bge/bin/python tests/test_structured_facts.py
PYTHONPATH=src .venv_bge/bin/python -m compileall -q src scripts tests
```

Run gold73 voi `SOLVE_CELL_LOCATOR=1`:

```text
artifacts/runs/cell_locator_gold73_v2.jsonl
score: 43/73
baseline full1012_qwen35: 38/73
head-to-head: +5 / -0 tren gold73
```

Dieu can doc dung:

- Nhung cau thuc su di qua `solver=cell_locator`: 7/7 dung.
- Khong nen noi toan bo +5 la do locator, vi cac cau con lai van qua codegen va codegen co churn giua cac run.
- Gain chac chan nhat: locator lam dung cac cau L1 ma codegen cu doc sai cell/sign.
- Flag van nen de OFF cho den khi chay full 1012 va build submission treatment.

## Codegen hien co kha nang gi

Codegen hien tai khong chi lam duoc Type 1. No la fallback linh hoat: nhan top raw tables tu RAG,
sinh mot pandas expression, executor chay/repair, units doi don vi, verifier doc lai cell thuc te.
Vi vay no co the giai Type 1-5 khi bang dung va semantic don gian, nhung khong co dam bao.

| Type | Kha nang hien tai cua codegen | Diem yeu chinh |
|---|---|---|
| Type 1 / L1 | Doc mot cell truc tiep kha tot khi gold table nam trong prompt va row/column ro. | Hay sai row gan nghia, sai cot dau/cuoi ky, sai dau am/duong, sai cot label neu bang co STT/ma hang. Cell locator moi xu ly subset bao thu cua nhom nay. |
| Type 2 / L2 | Tinh cong thuc 2-3 primitive cell duoc neu cac metric deu ro va trong 1-2 bang. | Chua co formula registry deterministic, nen model co the chon sai numerator/denominator, sai metric thanh phan, sai don vi hoac sign. |
| Type 3 / L3 | Tinh growth/YoY duoc khi hai nam cung trong bang hoac deu vao prompt. | De sai nam goc/nam hien tai, cong thuc ty le tang truong, percent vs percentage point, hoac mat bang nam truoc do retrieval/budget. |
| Type 4 / L4 | Lam duoc diff/compare giua hai report khi RAG dua du bang vao top prompt. | Nhay cam voi `codegen_max_tables=3`; neu mot bang bi cat khoi prompt thi codegen khong tu cuu duoc. |
| Type 5 / L5 | Co the sum/avg/min/max tren nhieu nam/cong ty neu day du table va labels de doc. | Yeu nhat trong L1-L5: de thieu mot nam/cong ty, sai aggregation, sai filter scope, hoac lay nham cung metric o bang gan nghia. |

Ket luan: codegen la fallback tot, nhung khong nen la engine chinh cho L1-L5. Huong tot hon la
mo rong deterministic executor theo thu tu:

1. L1 cell locator: dang co, can chay full 1012 de quyet dinh bat default hay khong.
2. L2 formula registry: dung cell locator de lay primitives, Python tinh cong thuc.
3. L3/L4 period-pair executor: cung mot metric, hai period/report, cong thuc growth/diff.
4. L5 aggregation executor: lap qua tap nam/cong ty da xac dinh, verify du primitive truoc khi tinh.
5. L6 moi can planner semantic day du.

## Kiem tra gate cell_locator (2026-08-22)

Kiem tra bang script moi `scripts/gate_cell_locator_funnel.py`, chay hoan toan
ngoai tuyen: khong goi LLM, khong chay pipeline, khong build lai index, khong
nop bai. Output day du luu o `artifacts/runs/gate_cell_locator_funnel.out`.

### Dieu kien claim, dung thu tu code

`build_request` (cell_locator.py:208-235):
- P1 (dong 213-214): dung 1 ma va 1 nam trong `state["tickers"]`/`state["years"]`.
- P2 (dong 215-216): khong `multi_year` va khong `multi_company`.
- P3 (dong 217-218): khong khop `_DERIVED_MARKER` (ty le/tang truong/so sanh/max-min/binh quan).
- P4 (dong 219-220): `operation` phai la `""` hoac `"lookup"`, tru khi `answer_shape == "single_cell"`.
- P5 (dong 222-224): `direct_metric_phrases(question, metric)` phai tra ve it nhat mot cum tu.

`locate_single_cell` (cell_locator.py:356-414):
- S6 (dong 368-370): danh sach bang ung vien (`table_ids` + `shortlist`) khong rong.
- S7 (dong 372-381): `search_rows` tren tat ca cum tu phai ra it nhat mot `CellHit` hop le (bang doc duoc, vi tri hang hop le, chon duoc cot theo nam/ky).
- S8 (dong 390-396): confidence cua cell tot nhat >= 0.78.
- S9 (dong 397-408): khong mo ho -- neu co cell thu hai khac ban ghi (bang/hang/cot) va cach cell tot nhat duoi 0.04 diem, tu choi.

Qua het S6-S9 thi `diag["done"] = True` va cell_locator claim cau hoi.

### Lo hong do luong: state ngoai tuyen khong tai tao het duoc

P1, P2, P4 doc `state["tickers"]`/`["years"]`/`["multi_year"]`/`["multi_company"]`/
`["operation"]`/`["answer_shape"]`, tat ca den tu node `understand` -- mot lenh
goi LLM (`agents/finance/understand.py`). `output/submission_v9_sign/submission.json`
khong luu state hay ten solver (chi co id/question/answer/relevant_docs/
relevant_tables/evidence/pandas_query), nen khong co cach doc lai state thuc su
ma tung cau da chay qua. Script dung proxy xac dinh, khong LLM:

- `tickers`: dung dung ham `find_tickers` ma `understand.py` cung goi -- chinh xac, khong xap xi.
- `years`/`multi_year`/`multi_company`/`doc_type`/`answer_shape`: lay tu
  `data/metadata/questions_enriched.jsonl`, san pham cua `enrich()` trong
  `modules/data/preprocessing/questions.py` -- mot pipeline rule-based KHAC,
  khong phai cai `understand()` dung khi chay thuc. La xap xi, co the lech voi
  state LLM thuc cua v9.
- `operation`: khong co gi thay the ngoai tuyen. Script ep `operation=""` de P4
  luon qua, nen o phe duoi cot P4 ghi "khong do duoc", khong phai "0 cau bi loai".
- `metric`: dat `""`. Cum tu chinh van tach duoc tu cau hoi, chi mat nhanh
  alias-theo-metric-key ma LLM moi dien duoc.
- danh sach bang cho S6-S9: dung `relevant_tables` cua submission da nop, la
  danh sach CUOI CUNG sau khi executor da chay xong, khac shortlist retrieval
  luc cell_locator thuc su nhin thay (rong hon, ~106 bang qua hard filter).

Vi hai ly do do, so "claimed" duoi day la uoc luong voi gate, khong phai so
cell_locator thuc su da claim khi chay v9.

### Phe tren 37 cau L1 (tap eval sach)

| buoc | y nghia | con lai | bi loai |
|---|---|---|---|
| bat dau | | 37 | |
| P1 | dung 1 ma + 1 nam (proxy) | 34 | 3 |
| P2 | khong multi-axis (proxy) | 34 | 0 |
| P3 | khong dau hieu derived/so sanh | 34 | 0 |
| P4 | lookup-shaped (ep qua, khong do duoc) | 34 | 0 |
| P5 | co cum tu chi tieu | 33 | 1 |
| S6 | co bang ung vien | 33 | 0 |
| S7 | tim duoc cell so | 25 | 8 |
| S8 | vuot nguong tin cay 0.78 | 20 | 5 |
| S9 | khong mo ho | 15 | 5 |
| **claimed** | | **15** | |

Buoc loai nhieu nhat: S7 (tim duoc cell so), loai 8 cau: 266, 267, 51, 308, 185,
703, 347, 255 -- voi dung bang trong `relevant_tables` da nop, khong tim duoc
hang nao khop nhan hoac khong chon duoc cot (nam/ky) hop le. S8 (duoi nguong tin
cay) loai them 5: 164, 714, 87, 360, 109. S9 (mo ho giua hai cell) loai 5: 257,
9, 10, 142, 32. P1 (proxy sai so ma/nam) loai 3: 4, 167, 506. P5 loai 1: 227.

15 cau duoc claim: 7, 72, 78, 139, 169, 172, 180, 211, 238, 273, 284, 306, 310,
313, 332. Trong 15 cau nay, submission v9 da dung 11/15 va sai 4/15 (139, 169,
284, 306) -- xem phan duoi.

### 14 cau L1 sai co bao cao vang trong relevant_tables da nop

Dung dung tieu chi cua `gate_type_split.py` (report_id la substring cua chuoi
noi `relevant_tables`): 14 cau khop -- 32, 51, 87, 109, 139, 164, 169, 185, 255,
267, 284, 306, 308, 703. Khop voi con so 14 team lead da nam.

Trong 14 cau do, gate cell_locator (proxy) claim duoc 4: 139, 169, 284, 306. 10
cau con lai bi tu choi truoc khi claim -- S7 (khong tim duoc cell): 51, 267,
185, 308, 703; S8 (duoi nguong tin cay): 164, 87, 109; S9 (mo ho): 32, 255.

Luu y: khong the goi 4 cau nay la "co hoi bi bo lo" cua cell_locator.
`output/submission_v9_sign/submission.json` duoc tao luc 2026-08-22 18:05:50,
SAU commit 119729d (07:14:53 cung ngay) doi default `SOLVE_CELL_LOCATOR` tu
False sang True. Khong co file `.flags` nao ghi lai v9_sign chay voi
`SOLVE_CELL_LOCATOR=0`. Neu v9_sign chay voi default hien tai, cell_locator da
THUC SU la solver dau tien nhin 4 cau nay, va co kha nang chinh no da tra loi
sai (chon nham hang/cot nhung van dat confidence >= 0.78) -- khong phai mot
solver khac tra loi sai roi cell_locator bi bo qua oan. Submission khong luu
field "solver" nen khong kiem chung truc tiep duoc; day la gioi han thuc, khong
phai suy dien theo huong co loi cho cell_locator.

### Vi tri trong SOLVER_CHAIN, co solver nao cuop cau hoi khong

`SOLVER_CHAIN` (graph.py:1074-1081), dung thu tu: cell_locator -> formula_facts
-> raw_table_linker -> selection_facts -> raw_selection_linker -> structured_facts.

cell_locator dung DAU TIEN. `make_solver_router(config, after=None)` duoc goi
ngay sau `trace_capabilities` (graph.py:1146-1150). Voi `after=None` thi
`diag_key=None` (graph.py:1092-1096) nen `route()` khong kiem tra "done" cua
solver nao ca -- no chi lap qua toan bo `SOLVER_CHAIN` tu dau va tra ve node
dau tien co flag True (graph.py:1099-1105). `cell_locator` la phan tu dau danh
sach va flag `cell_locator` default True (config.py:144), nen moi cau hoi den
`solve_single_cell` truoc bat ky solver nao khac trong `SOLVER_CHAIN`. Khong co
solver nao cuop cau hoi truoc cell_locator: 0/37.

(`solve_selection` la nhanh rieng ngoai `SOLVER_CHAIN`, chi vao khi
`selection_decompose=True` -- default False, config.py:388 -- va cau hoi co
truc nam/ma; theo topology cua `build_graph` no khong the chay truoc
`trace_capabilities`/`solve_single_cell`.)

### Mau thuan voi noi dung cu o tren

- Dong 74 cua doc nay: "Flag van nen de OFF cho den khi chay full 1012 va build
  submission treatment." Code hien tai (config.py:144, tu commit 119729d ngay
  2026-08-22) dat default `SOLVE_CELL_LOCATOR=True`, va full 1012 da chay xong
  voi default nay (`artifacts/runs/full_1012_v9.jsonl`, `submission_v9_sign`).
  Khuyen nghi "de OFF" trong doc khong con dung voi trang thai code.
- Dong 71: "Nhung cau thuc su di qua `solver=cell_locator`: 7/7 dung." TAI KIEM
  CHUNG DUOC: `artifacts/runs/cell_locator_gold73_v2.jsonl` co 7 ban ghi
  `solver == "cell_locator"` (id 17, 27, 44, 86, 88, 115, 161); doi chieu qua
  `score_gold75.py` (`data/eval/unbiased60_gold.jsonl` + `manual15_gold.jsonl`),
  ca 7 khop gold trong dung sai 1%. Khong mau thuan -- nhung con so nay do tren
  gold73, tap ma `config.py` (comment o flag `raw_selection_linker`) tu ghi la
  "contaminated" (27/75 id xuat hien trong `src`/`tests`), va 2 trong 7 id nay
  (86, 88) duoc `tests/test_solve_units.py` neu ten truc tiep nhu vi du da biet
  truoc. Khong phai hardcode `{id: answer}`, nhung cung khong nen doc 7/7 nhu
  mot uoc luong khong thien vi ve ty le dung cua cell_locator tren du lieu chua
  tung thay.

Lenh da chay:
```bash
PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_cell_locator_funnel.py \
    output/submission_v9_sign/submission.json
```

