# Handoff — ViFinQA Stage 2

Điểm bắt đầu cho người tiếp tục dự án. **Trạng thái hiện tại + hạ tầng bền vững.**
Lịch sử quyết định đầy đủ (planner cũ, các iteration v2→v9, baseline leaderboard) nằm ở
`docs/DECISIONS.md`. Code và artifact ưu tiên hơn ghi chú thiết kế cũ khi mâu thuẫn.

---

## 0. Pipeline hiện tại — GRAPH (phiên 2026-08-09)

> Luồng answer active là **graph** (`graph/graph.py::run_question`). Pipeline planner cũ
> (`run_pipeline.py`) đã bị thay; chỉ còn dùng lại phần retrieval/data snapshot bên dưới.

### Luồng graph
```
understand (LLM + rule-based ticker)  → resolve ticker từ code_stock.csv TRƯỚC, rồi LLM
  → retrieve_targeted (live: BM25+dense+reranker; fallback frozen nếu OOM/no-ticker)
  → load (normalize DataFrames)
  → _route:  op=lookup+single_cell → lookup_solver
             op∈{formula,compare,multi_step} → formula_solver (one-shot: render→reason→emit)
             còn lại / formula_skip → repl_solver
```
Chi tiết solver + vì sao one-shot (không ReAct) + vì sao tách 2 LLM call: `DECISIONS.md §9`
(mục "Solver flow hiện tại") và `§10`.

### Việc phiên này đã làm (3 fix tầng DATA, đã verify — `DECISIONS.md §10`)
| # | File | Nội dung |
|---|---|---|
| D1 | `preprocessing/canonical.py` `MA_SO_IS` | mã **62**=net_profit_attributable_to_owners, mã **70**=eps_basic, **71**=eps_diluted (trước map sai → rác 1e-11) |
| D2 | `preprocessing/canonical.py` `_build_year_map` | fallback theo **vị trí cột** khi header OCR mất năm (parse report_year từ table_id, current-before-prior, `setdefault` không đè) |
| D3 | `graph/nodes/understand.py` | resolve ticker **rule-based trước LLM** từ BTC `ViFinQA/code_stock.csv` — chặn 8B bịa mã (Nam Kim→NKM thay vì NKG) |

Nguyên tắc: **field có nguồn chân lý (ticker, mã số TT200) → deterministic từ nguồn đó, KHÔNG
để 8B đoán.** LLM chỉ giữ operation/metric/answer_shape.

### Trạng thái & bug còn lại
- gold20 live ≈ **5/20**. Retrieval + data KHÔNG còn là bug (Q363/Q371 đã xanh khi chạy live).
- **Đỏ còn lại = thuần tầng LLM 8B**: đổi đơn vị (Q390 nghìn tỷ) + suy luận multi-step
  (Q414, Q378, Q381, Q392, Q396, Q409, Q422, Q423, Q429, Q439, Q440).
- ⚠️ `graph/` và `preprocessing/canonical.py` hiện **untracked** — chưa commit.

### Việc tiếp theo (ưu tiên, chưa greenlit — hỏi user trước khi làm mới)
1. **Đổi đơn vị deterministic** [rẻ, chặn Q390]: dùng `detect_unit()` trong `questions.py` để ép
   chia/nhân sau khi model ra số thô, thay vì tin model tự đổi.
2. **Structured pick + tra deterministic**: model chỉ xuất JSON chọn năm/công ty; code đọc số từ
   canonical dict → bỏ số học sai của 8B.
3. **Abstain** khi thiếu metric / magnitude vô lý → None → repl (không bịa).
4. Chạy **full 1012** qua graph để đo lift thật (blocked khi GPU đầy — cần ~2GB encode query).

### Reproduce (GPU cần ~2GB free)
```bash
PYTHONPATH=src .venv_bge/bin/python scripts/test_formula_solver.py 390   # 1 câu: solver+match+reasoning
PYTHONPATH=src .venv_bge/bin/python scripts/_probe_coverage.py 390       # coverage canonical 1 câu
PYTHONPATH=src .venv_bge/bin/python scripts/eval_graph20.py              # full gold20 qua graph
```
Ràng buộc môi trường: vLLM `Qwen/Qwen3-8B-Instruct` @ port 8990 **dùng chung, KHÔNG restart**;
chỉ `tool_choice="required"` (không auto-tool-choice); dense index precomputed, chỉ query-encode
cần GPU local. Warning `libtinfo.so.6` mỗi lệnh Bash là noise vô hại.

---

## 1. Cấu trúc repo

| Vị trí | Trách nhiệm |
|---|---|
| `src/finance_qa/preprocessing/` | metadata câu hỏi (`questions.py`: ticker/năm/đơn vị) + biểu diễn text bảng + `canonical.py` (mã số TT200 → metric) |
| `src/finance_qa/retrieval/` | filter, BM25, dense encoder, LLM judge, reranker |
| `src/finance_qa/graph/` | **pipeline answer active**: nodes (understand/retrieve_targeted/load) + solvers (lookup/formula/repl) |
| `src/finance_qa/planning/` | IR/repair/compiler của planner cũ (repl_solver còn dùng lại) |
| `src/finance_qa/execution/` | normalize DataFrame + thực thi query an toàn |
| `src/finance_qa/evaluation/` | evaluator dùng lại cho retrieval/planner |
| `scripts/` | entrypoint + diagnostic; không coi script thí nghiệm là production API |
| `data/eval/` | ground truth chỉ để đánh giá (`extended_gold.jsonl` = gold20 khó) |
| `artifacts/` | report, cache, kết quả benchmark; `artifacts/runs/full_1012.jsonl` = frozen fallback |
| `output/` | chỉ chứa sản phẩm submission cuối |

Mọi đường dẫn mặc định của application code đi qua `src/finance_qa/paths.py`; không hardcode
đường dẫn checkout trong library.

## 2. Data snapshot — PHẢI BẢO TOÀN

`tables_metadata_v2.jsonl` (146.246 dòng) + `data/indexes/*` (`tables_doc_text.parquet`,
`tables_dense.npy`) là **snapshot không rebuild được từ đầu**: `enrich_metadata_v2.py` và
`build_long_format.py` đọc `tables_metadata.jsonl` (v1) — file này **không có** trong workspace.
Coi các artifact này là bất biến cho tới khi khôi phục v1. Backend dense thứ 2 (nếu re-embed)
**không được ghi đè** `tables_dense.npy` — encode ra file mới.

Snapshot: OCR 1.973 file · 146.246 bảng CSV/index · 1.012 câu enriched · gold20 numeric (`extended_gold.jsonl`).

### ⚠️ Extractor footgun
`scripts/extract_tables.py` **không có** argparse/dry-run/staging. Mỗi lần chạy: quét toàn bộ
1.973 OCR file, **ghi đè toàn bộ** `data/tables/`, overwrite `tables_index.jsonl` +
`extract_stats.md` + `extract_errors.log`. **KHÔNG dùng để smoke test.** `beautifulsoup4` không
có trong `.venv_bge` (rào chắn thêm). Muốn đổi extraction thật: thêm output staging/atomic swap +
fixture tests + đường rebuild metadata/index đầy đủ, rồi mới chạy corpus.

## 3. Retrieval (hạ tầng, vẫn đúng)

Pool dựng ở **một chỗ**: `retrieval/candidates.py` (`CandidateRetriever`). Graph gọi qua
`graph/nodes/retrieve_targeted.py`.
```
shortlist (ticker × year × doc_type, prefer_consolidated, has_content)
  → BM25 top-20 + dense top-20 (query đã strip entity) → RRF (k=60)
  → primary-statement expansion (BS/IS/CF/equity_change)
  → reranker (qwen3-0.6b, DeepInfra API, remote) → judge_top_n=20
  → judge đọc judge_text → ≤10 pick
```
Retrieval document tier tốt (leaderboard DOCS_F2MACRO 0.93, `DECISIONS.md §9a`). Root cause đã biết:
judge hay chọn note chi tiết thay báo cáo chính → reranker + primary expansion xử lý.

> Lưu ý: ghi chú "reranker là negative result, đừng thử lại" trong các bản handoff cũ **đã bị đảo**
> — graph hiện dùng reranker (Decision 9, `DECISIONS.md §9` mục retrieval). Đừng gỡ reranker dựa
> trên ghi chú cũ đó.

## 4. Test an toàn (không gọi LLM)

Dùng `.venv_bge/bin/python`:
```bash
.venv_bge/bin/python -m compileall -q src scripts tests
.venv_bge/bin/python tests/test_planning_ir.py
.venv_bge/bin/python tests/test_generation.py
.venv_bge/bin/python tests/test_query_execution.py
.venv_bge/bin/python tests/test_candidate_pool.py
.venv_bge/bin/python tests/test_pipeline_run.py
```
Retrieval 2 stage đầu không cần encoder: `evaluate_retrieval.py --stage filter|bm25`.
`pyproject.toml` mới khai báo layout, chưa khóa runtime deps.

## 5. Tài liệu còn lại

- `docs/DECISIONS.md`: **sổ quyết định chính** — retrieval, planner cũ, baseline leaderboard,
  graph solver (§9), 3 fix data phiên này (§10). Đọc §9–§10 cho trạng thái mới nhất.
- `docs/v0_retrieval_pipeline.md`: nhật ký thiết kế + benchmark retrieval (giá trị lịch sử).
- `docs/v0_end_to_end.md`: runner cũ + phân tích 15 câu (lịch sử).
- `docs/metadata_audit.md`: audit metadata + field deferred.
- `docs/8020.md`: phân tích submission ban đầu (một số nhận định đã lỗi thời).
