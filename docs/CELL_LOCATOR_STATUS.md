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

