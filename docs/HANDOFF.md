# Handoff — ViFinQA Stage 2

Tài liệu này là điểm bắt đầu cho người tiếp tục dự án. Code và artifact được ưu
tiên hơn các ghi chú thiết kế cũ khi có mâu thuẫn.

## 1. Trạng thái hiện tại

Pipeline đã có hai khối chạy độc lập:

```text
Question metadata
  → hard filter
  → BM25 + dense candidate retrieval
  → LLM judge

Selected table IDs
  → load/normalize DataFrames
  → LLM symbolic plan
  → validate + repair contracts
  → compile pandas expression
  → execute expression
  → answer + evidence
```

Hai khối đã được nối bằng `scripts/run_pipeline.py` (resume, per-stage errors,
validate từng item). Chưa chạy full 1.012 câu và chưa có bước đóng gói ZIP
submission.

Snapshot dữ liệu đang dùng:

| Thành phần | Trạng thái |
|---|---:|
| OCR input | 1.973 file |
| Table CSV/index | 146.246 bảng |
| `tables_metadata_v2.jsonl` | 146.246 dòng |
| Câu hỏi enriched | 1.012 câu |
| Retrieval eval | 24 câu report-GT, trong đó 15 câu có table-GT |
| Planner eval | 15 câu có numeric answer + table-GT |

`data/` hiện khoảng 1,3 GB. `output/` chưa có submission hoàn chỉnh.

## 2. Cấu trúc và trách nhiệm

| Vị trí | Trách nhiệm |
|---|---|
| `src/finance_qa/preprocessing/` | metadata câu hỏi và text biểu diễn bảng |
| `src/finance_qa/retrieval/` | filter, BM25, dense encoder, LLM judge |
| `src/finance_qa/planning/` | symbolic IR, concept contracts, repair, compiler |
| `src/finance_qa/execution/` | normalize DataFrame và thực thi query an toàn |
| `src/finance_qa/pipeline/` | runner end-to-end: câu hỏi → submission item |
| `src/finance_qa/evaluation/` | evaluator dùng lại được cho retrieval/planner |
| `scripts/` | entrypoint và diagnostic; không coi script thí nghiệm là production API |
| `data/eval/` | ground truth chỉ phục vụ đánh giá |
| `artifacts/` | report, cache cũ, kết quả benchmark |
| `output/` | chỉ dành cho sản phẩm submission cuối |

Mọi đường dẫn mặc định của application code phải đi qua
`src/finance_qa/paths.py`; không hardcode đường dẫn checkout trong library.

## 3. Dữ liệu và dependency graph

Luồng artifact dự kiến:

```text
ViFinQA/financial_statements/*_extracted.txt
  → scripts/extract_tables.py
  → data/tables/** + data/metadata/tables_index.jsonl

table metadata + table CSVs
  → scripts/enrich_metadata_v2.py
  → data/metadata/tables_metadata_v2.jsonl
  → scripts/build_doc_text.py
  → data/indexes/tables_doc_text.parquet
  → scripts/build_dense_index.py
  → data/indexes/tables_dense.npy

ViFinQA/questions/questions.jsonl
  → scripts/enrich_questions.py
  → data/metadata/questions_enriched.jsonl
  → scripts/build_evalset.py
  → data/eval/evalset.json
```

Hiện graph này chưa tái tạo được từ đầu: `enrich_metadata_v2.py` và
`build_long_format.py` đọc `data/metadata/tables_metadata.jsonl` (v1), nhưng file
đó không có trong workspace. Vì vậy `tables_metadata_v2.jsonl` và các index nên
được coi là snapshot cần bảo toàn cho tới khi khôi phục v1 hoặc refactor builder
để có nguồn vào khả dụng.

### Cảnh báo extractor

`scripts/extract_tables.py` không có argparse, `--help`, dry-run hay output tạm.
Bất kỳ lần chạy nào cũng:

- quét toàn bộ 1.973 OCR file;
- ghi lại toàn bộ `data/tables/`;
- overwrite `data/metadata/tables_index.jsonl`;
- overwrite `artifacts/reports/extract_stats.md` và `extract_errors.log`.

Không dùng script này để smoke test. Nếu thực sự thay đổi extraction, trước hết
phải bổ sung output staging/atomic swap, fixture tests cho HTML lệch, và một
đường rebuild metadata/index đầy đủ. Sau đó mới chạy lại corpus.

Corpus hiện tại đã được khôi phục bằng parser BeautifulSoup nguyên bản. Lần xác
minh gần nhất cho kết quả: 146.246 index rows, 146.246 metadata-v2 rows, không
thiếu/thừa table ID, không lệch `num_rows`/`num_cols`, và error log rỗng.

## 4. Retrieval

Pool được dựng ở **một chỗ duy nhất**: `src/finance_qa/retrieval/candidates.py`.
Evaluator (`scripts/evaluate_retrieval.py`), runner end-to-end và các script
diagnostic đều đi qua nó, nên policy đo trên eval set đúng là policy production
chạy. Trước đây hai luồng lệch nhau; giờ hết.

```text
shortlist (ticker × year × doc_type, prefer_consolidated, has_content)
  → BM25 top-20 + dense top-20 trên query đã strip
  → RRF (k=60)
  → primary-statement expansion
  → judge đọc judge_text, trả tối đa 10 pick
```

Nhóm A (2026-08-04) — pool nhỏ hơn ở cùng chất lượng, chi tiết trong
`v0_retrieval_pipeline.md` mục "Nhóm A". Không cái nào sửa `doc_text` nên index
dense prebuilt vẫn đúng:

- `channel_k` 50 → 20: pool med 79→38, max 131→95; union all-hit@20 phẳng ở 93,3%
  từ k=15. Đây là knob quyết định hóa đơn judge.
- junk filter `has_content` (bỏ `num_rows ≤ 2` hoặc `first_col_labels` rỗng) đặt ở
  `shortlist`: 9 419 bảng (6,4% corpus) bị bỏ, **0/39 GT**. Đặt ở shortlist để chặn
  cả primary expansion; predicate hẹp có chủ ý (đừng thêm `is_continuation` — giữ 5
  GT, hay "thiếu note+section" — giữ 21 GT).
- `--judge-top-n` đã nối vào `evaluate_retrieval.py` + `pipeline/run.py`, default
  `None` = judge đọc cả pool.
- **Reranker: negative result, đừng thử lại.** qwen3-0.6b làm all-hit@15
  80,0% → 73,3% và +114 s. Backend giữ lại chỉ vì là interface đã test.

Run Nhóm A: `artifacts/runs/retrieval_judge_groupa.jsonl` — table @15 93,9/86,7,
@30 95,2/93,3; report 100/100; pool med 38/max 95; 469,2 s (baseline 539,2 s).

Ba policy đang bật mặc định, mỗi cái đo được trên 15 câu table-GT:

1. bỏ ticker, năm và token tên công ty khỏi retrieval query sau hard filter (pool
   recall 92,0% → 97,1%); chỉ *retrieval query* bị strip, judge vẫn đọc câu gốc vì
   cần năm;
2. luôn thêm mọi bảng `balance_sheet`, `income_statement`, `cash_flow`,
   `equity_change` trong shortlist vào pool (97,1% → 100,0% pool ceiling);
3. dùng `judge_text` thay vì `doc_text` cho prompt judge (−22% ký tự, không mất
   signal).

Artifact chuẩn — `artifacts/runs/retrieval_judge_default.jsonl` + `.summary.json`:

| | @5 | @10 | @15 | @30 | @50 |
|---|---|---|---|---|---|
| table tier (n=15) | 74,7/73,3 | 78,7/73,3 | 84,3/80,0 | 94,3/93,3 | 95,2/93,3 |
| report tier (n=24) | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 |

Judge trả tối đa 10 pick, nên @5/@10 đo *judge* còn @30/@50 đo *retrieval tail*
(`rerank_with_picks` giữ đuôi lại). Bước nhảy 84,3% → 94,3% giữa @15 và @30 chính
là phần judge bỏ sót mà pool vẫn giữ. Tập đánh giá nhỏ và vLLM không bit-exact,
nên chênh lệch dưới khoảng 6 điểm phần trăm được xem là noise.

Root cause retrieval đã biết:

- toàn bộ shortlist sau hard filter chứa 100% report/table GT trên eval set
  (đây là pool ceiling, không phải recall ở top-K khi chưa rank);
- bảng báo cáo chính chỉ chiếm khoảng 10% bảng/report và thường thua note giàu từ
  vựng, nên primary expansion giải quyết đúng cơ chế;
- judge hay chọn note chi tiết thay cho báo cáo chính dù cả hai chứa cùng số;
- prompt quá dài từng gây HTTP 400 giả dạng quality miss; judge hiện budget theo
  context và phải log HTTP errors rõ ràng.

## 5. Planner và execution

Planner nhận table ID đã chọn, nạp toàn bộ bảng, tạo symbolic plan, validate các
contract rồi mới compile thành một pandas expression. `answer` luôn lấy từ kết
quả thực thi expression, không lấy số do LLM tự chép.

Các invariant quan trọng:

- numeric answer/tolerance chỉ nằm trong `data/eval/planner_answers.json` và
  production code không được đọc file này;
- compiler sở hữu unit conversion; formula không tự chia đơn vị lần nữa;
- binding phải giữ đúng company, period, row concept và table source;
- repair phải sửa trên canonical plan hiện tại, không dựng lại từ plan cũ;
- evidence chỉ liệt kê DataFrame thực sự được query dùng;
- header OCR chỉ được normalize khi cấu trúc suy ra đủ chắc chắn; không đoán bừa.

Artifact chuẩn hiện tại:

- `artifacts/runs/planner_gt15_after_fixes.jsonl`
- `artifacts/runs/planner_gt15_after_fixes.summary.json`

Kết quả: 15/15 executable, 15/15 correct, planner coverage 100%, không dùng
direct-code fallback; tổng latency 93,171 giây, trung bình 6,211 giây/câu. Đây là
regression set nhỏ chạy bằng ground-truth tables, không phải accuracy end-to-end
trên 1.012 câu.

15/15 này **không robust**: q818 nhận đúng 5 bảng GT đó nhưng theo thứ tự judge trả
về (không chronological) thì bind sai cột/sai hàng và không ra được số. Đã kiểm
bằng thí nghiệm có control (cùng câu hỏi, cùng 5 bảng, chỉ đổi thứ tự, 3 lần mỗi
thứ tự): GT-order 3/3 đúng, judge-order 0/3. Chi tiết ở `docs/v0_end_to_end.md`.
Đừng coi 15/15 là bằng chứng planner đã ổn định.

## 5b. End-to-end

`scripts/run_pipeline.py` → `src/finance_qa/pipeline/run.py`: câu hỏi enriched →
pool → judge → planner → submission item → `execution.query.validate`. Có
`--resume` (append-only, last-record-wins), `--retry-failed`, `--ids`, `--limit`,
per-stage error trong từng record (`status` ∈ `ok`/`invalid`/`error`, `stage` ∈
`retrieve`/`plan`/`validate`). GPU query encode batch trên main thread; chỉ LLM call
fan-out ở 4 workers.

Baseline kết hợp trên đúng 15 câu đó, dùng bảng **retrieve được** thay vì GT
(`artifacts/runs/pipeline_gt15.jsonl`): **7/15 correct**, 12/15 ra được item hợp
schema, throughput ~20 giây/câu ở 4 workers, judge đưa trung bình 3,7 bảng/câu,
10/15 câu có ít nhất một bảng GT trong input planner.

Hai failure class mới, đáng chú ý hơn miss thuần:

- **sai im lặng** — q752/q582 chạy được, ra scalar hữu hạn, qua `validate`, và sai
  (q752 đúng độ lớn, sai dấu). Không có tín hiệu nào ở runner để phát hiện;
- **unit conversion trùng** — q100 tự thêm `/1000000.0` vào ô đã ở đơn vị đồng, tức
  invariant "compiler sở hữu unit conversion" chưa chắc khi planner đọc bảng lạ.

Phân tích đầy đủ từng câu ở `docs/v0_end_to_end.md`.

## 6. Cách kiểm tra an toàn

Dùng `.venv_bge/bin/python`. Các test sau không gọi LLM:

```bash
.venv_bge/bin/python -m compileall -q src scripts tests
.venv_bge/bin/python tests/test_planning_ir.py
.venv_bge/bin/python tests/test_generation.py
.venv_bge/bin/python tests/test_query_execution.py
.venv_bge/bin/python tests/test_planner_evaluation.py
.venv_bge/bin/python tests/test_candidate_pool.py
.venv_bge/bin/python tests/test_pipeline_run.py
```

Kiểm tra planner labels mà không gọi model:

```bash
.venv_bge/bin/python scripts/evaluate_planner.py --list
```

Chạy một slice planner mới; dùng output mới hoặc `--resume`, vì evaluator từ
chối overwrite file có sẵn:

```bash
.venv_bge/bin/python scripts/evaluate_planner.py \
  --ids 1,752,363 \
  --output artifacts/runs/planner_smoke_next.jsonl
```

Retrieval không cần encoder ở hai stage đầu:

```bash
.venv_bge/bin/python scripts/evaluate_retrieval.py --stage filter
.venv_bge/bin/python scripts/evaluate_retrieval.py --stage bm25
```

Chạy end-to-end một slice; giống evaluator, runner từ chối overwrite output có sẵn
nếu không có `--resume`:

```bash
.venv_bge/bin/python scripts/run_pipeline.py --list --limit 5
.venv_bge/bin/python scripts/run_pipeline.py \
  --ids 1,17 \
  --output artifacts/runs/pipeline_smoke_next.jsonl
```

`dense`, `rrf` và `judge` cần GPU/index dense. `judge` còn cần endpoint OpenAI
compatible tại `http://127.0.0.1:8990/v1/chat/completions`, model
`Qwen/Qwen3-8B-Instruct`. Endpoint này thuộc service dùng chung; giữ concurrency
thấp và không restart service.

`pyproject.toml` hiện chỉ khai báo package layout, chưa khóa runtime dependencies.
`beautifulsoup4` không có trong `.venv_bge`; đây là lý do bổ sung để không chạy
extractor trong workflow thông thường.

## 7. Việc nên làm tiếp theo

Xong (2026-08-04): candidate-pool API dùng chung, retrieval judge đo lại qua
entrypoint chính, runner end-to-end có resume + per-stage errors, baseline kết hợp
15 câu.

Theo thứ tự ưu tiên:

1. Mở rộng table/numeric eval lên khoảng 100 câu. Việc này giờ **chặn** những việc
   sau, không còn là "nice to have": bộ 15 câu vừa cho thấy nó đo cả sampling noise
   (q818 mất chỉ vì permute thứ tự bảng), nên không phân biệt được thay đổi thật với
   nhiễu.
2. Sửa hai failure class mà end-to-end mới lộ ra, cả hai đều thuộc planner chứ không
   thuộc retrieval:
   - binding phải bám tên cột thật của **frame đó** và bất biến với thứ tự `dfN`
     (q818);
   - unit conversion không được áp hai lần khi bảng đã ở đơn vị đồng (q100).
3. Thêm submission validator ở mức corpus, trên `execution.query.validate` sẵn có:
   đủ 1.012 ID, answer scalar hữu hạn, query chạy lại được, evidence variables khớp
   query, mọi `csv_path` tồn tại dưới `data/`, và ZIP đúng cấu trúc.
4. Chạy full 1.012 câu qua `scripts/run_pipeline.py` (~20 giây/câu ở 4 workers ⇒
   khoảng 5–6 giờ; dùng `--resume`) rồi đóng gói ZIP.
5. Khôi phục/rebuild nguồn metadata v1 hoặc thay builder bằng nguồn vào được quản
   lý rõ ràng; chỉ sau đó mới xem extraction là reproducible.

Chưa nên làm decomposition planner hoặc mở rộng ontology chỉ dựa trên suy đoán.
Failure end-to-end đã có chỉ về phía **bảng nào được chọn** và **binding/unit của
planner**, không về phía decomposition.

## 8. Tài liệu còn lại

- `docs/v0_retrieval_pipeline.md`: nhật ký thiết kế, benchmark và root-cause
  retrieval. Có giá trị lịch sử nhưng không tự động phản ánh code entrypoint.
- `docs/v0_end_to_end.md`: runner end-to-end, baseline kết hợp 15 câu và phân tích
  từng câu mất.
- `docs/metadata_audit.md`: audit metadata và các field deferred.
- `docs/8020.md`: phân tích submission ban đầu; một số nhận định về việc chưa có
  CSV đã lỗi thời vì corpus CSV hiện đã được tạo.
- `brainstorming/v0_pipeline_design.md`: brainstorming ban đầu, không phải spec.
- `artifacts/reports/*.md`: output của từng script; có thể stale nếu upstream được
  rebuild, nên kiểm tra timestamp/nguồn trước khi dùng.
