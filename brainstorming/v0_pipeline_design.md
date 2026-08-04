# v0 — Brainstorming: Pipeline design cho ViFinQA Stage 2

**Trạng thái**: Brainstorming complete. Chưa build.
**Nguồn**: Session grilling sau khi giải tay 12 câu (L1-L6) và soi ~10k table đã extract.
**Ngày**: 2026-08-02
**Follow-ups**: `data/eval/manual_solutions/solutions.md`, `data/eval/manual_solutions/LESSONS.md`, `scripts/classify_ops.py`, `artifacts/reports/ops_report.md`.

---

## 0. Bối cảnh cuộc thi

### Dataset
- **1,973 báo cáo tài chính OCR** Việt Nam (dạng HTML), 100 mã cổ phiếu, đa ngành (non-financial / bank / securities / insurance).
- **1,012 câu hỏi** tiếng Việt, phân bố L1-L6 (đã stratify manually).
- Table đã được extract từ HTML → `data/tables/<report_id>/table_<pos>.csv`.

### Submission format (từ `submission_rule.txt`)
Mỗi câu bắt buộc có các trường:
- `id`, `question`, `answer` (float)
- `relevant_docs` (list report_id)
- `relevant_tables` (list `<report_id>|<pos>`)
- `evidence` (variable name → csv_path)
- **`pandas_query` (string executable)** — bắt buộc cho **mọi câu**, chạy trên CSV ở `data/` folder

⇒ Không thể skip pandas cho câu "dễ". Nhưng có thể template hoá pandas cho câu đơn giản.

### Ràng buộc scoring
- **10 lượt submit / ngày**
- **Chỉ trả về scalar score cuối cùng** — không tiết lộ câu nào sai
- ⇒ Submit **không dùng để debug per-question**. Chỉ dùng làm outer-loop validation.

---

## 1. Câu hỏi core được đặt ra

> "Làm sao pipeline giải được 1012 câu hỏi tài chính tiếng Việt trên 1973 báo cáo OCR, xuất ra được `pandas_query` executable, mà không có ground truth để debug per-question?"

Sub-questions phát sinh trong quá trình:
1. Storage: raw CSV hay chuẩn hoá long-format?
2. Table classification: rule hay LLM?
3. Row/metric canonicalization: dictionary, embedding, hay LLM?
4. Retrieval: filter cứng, BM25, embedding?
5. LLM prompt: single-shot, agentic, hay hybrid?
6. Eval: gold set tay, health metrics, hay dựa submit?
7. Op classification: có nên rule-classify để chọn template pandas?

---

## 2. Insight từ 12 câu giải tay (L1-L6)

Xem `data/eval/manual_solutions/solutions.md` cho chi tiết. Rút gọn quan sát:

### Metadata cần trên report
`report_id`, `ticker`, `year`, `doc_type` (consolidated/separate), `industry` (non_financial/bank/securities/insurance), `company_name`.

### Metadata cần trên table
Không đủ nếu chỉ `(report_id, table_pos)`. Cần:
- `statement_type`: `balance_sheet` | `income_statement` | `cash_flow` | `note` | `equity_change` | `entity_info`
- `statement_subtype`: `bs_assets` | `bs_liabilities` (BS thường tách 2)
- `note_id`, `note_title` (nếu là note)
- `period_columns`: list các cột kỳ (`2018_annual`, `31/12/2018_snapshot`)
- `has_ma_so_column`: bool (BS/PL/CF đều có, note thì không)

### Row indexing dual mode
- **BS/PL/CF**: index theo **`ma_so`** (stable, không phụ thuộc OCR quality)
- **Note**: index theo **`(note_id, label_normalized)` + `metric_canonical`**

### Long-format shape lý tưởng
`(report_id, table_pos, ma_so_or_note_row, metric_canonical, period_key, column_semantics, value_float)`

### Derived metrics cần dictionary
`net_profit_margin`, `de_ratio`, `roa`, `roe`, `interest_coverage`, `ebit`, `current_ratio`, `growth_pct`, `cash_equiv_over_assets`… — LLM planner cần công thức.

### Ticker resolution: 3 case
1. Có mã trong ngoặc `(VJC)` → trực tiếp
2. Chỉ có tên `"Ngân hàng TMCP Phương Đông"` → alias table
3. Tên gây nhầm `"Viễn thông FPT" → FOX ≠ FPT` → stopword-aware entity linking

### Pitfalls đã quan sát
1. Ticker giả (FPT vs FOX)
2. "công ty mẹ" = separate (không phải consolidated)
3. Metric ambiguity: "LN ròng" = mã 60 vs mã 61
4. Sub-metric note vs total BS: "vay ngân hàng" ≠ "vay và nợ ngắn hạn"
5. Flow vs stock: "khấu hao trong năm" vs "khấu hao lũy kế"
6. Bank/securities/insurance có schema riêng — không dùng "Doanh thu thuần"
7. Note dạng ma trận (roll-forward TSCĐ)
8. Column semantics trong note (giá gốc / carrying / fair_value / recoverable)
9. 1 giá trị xuất hiện ở nhiều bảng → cần rule ưu tiên
10. Answer type: hầu hết float VND-ish, nhưng L3.2 argmax → float year

---

## 3. Thí nghiệm: rule-classify op trên 1012 câu

**Mục đích**: Kiểm tra giả thuyết "95% câu là template-able, chỉ 5% L6 cần LLM planner".

**Script**: `scripts/classify_ops.py` với 9 op (lookup/growth/diff/ratio/sum/avg/argmax/count/complex).

**Kết quả** (`artifacts/reports/ops_report.md`):

| op | count | share |
|---|---:|---:|
| `lookup` | 560 | 55.3% |
| `ratio` | 243 | 24.0% |
| `growth` | 55 | 5.4% |
| `argmax` | 51 | 5.0% |
| `diff` | 41 | 4.1% |
| `avg` | 22 | 2.2% |
| `sum` | 19 | 1.9% |
| `complex` | 11 | 1.1% |
| `count` | 10 | 1.0% |

**Sanity check** phát hiện rule sai ở đa số bucket:
- `ratio` gộp cả "tỷ lệ sở hữu" (lookup từ note) với "tỷ suất lợi nhuận" (compute) — thổi phồng.
- `growth`/`argmax` chứa nhiều L6 nested ("Trong nhóm ... xét các doanh nghiệp có ...") — rule complex hẹp quá.
- `diff` lẫn `count`: "**có bao nhiêu** doanh nghiệp có ... **hơn** ..." → count nhưng match `hơn` trước.
- `sum` lẫn `argmax`: "cao nhất trong các năm ..." không phải sum.
- `count` lẫn `lookup`: "số lượng cổ phiếu ... là bao nhiêu" là lookup 1 cell.

**Kết luận**: Rule-classify op để chọn template pandas là hướng **fragile và premature**. LLM classifier hoặc bỏ hẳn khái niệm op-based routing.

**Reframe quan trọng**: Không cần phân loại op để chọn template. **LLM luôn viết pandas**, khác nhau chỉ là **retrieval breadth và context size feed vào**.

---

## 4. Reframe pipeline (post-experiment)

Trục quyết định thật không phải "template vs LLM" mà là **"context feed rộng hay hẹp"**:

```
Question
  ↓
Retrieval: chọn tables liên quan
  ↓
Context feed cho LLM (rộng/hẹp tuỳ độ phức tạp câu):
   - Tables (raw CSV + schema)
   - Metric hint từ dictionary
   - Unit hint từ regex
  ↓
LLM sinh pandas_query
  ↓
Executor chạy → answer
```

Op classifier (nếu có) chỉ đóng vai **retrieval-breadth selector**, không sinh code.

---

## 5. Quyết định pipeline (8 chốt)

### #1. Storage layer → **Hybrid (raw CSV + long-format index)**

**Không chọn**:
- Raw CSV only: LLM phải parse "208.253.201.298" và unit mỗi lần
- Long-format only: submission bắt buộc `csv_path` trỏ tới CSV chạy được

**Chọn**: Raw CSV là evidence (submission requirement). Long-format là index để retrieve. LLM viết pandas trên tên cột raw (`2018VND`) và tên hàng raw (`Lãi tiền gửi`), nhưng đã được dẫn tới đúng chỗ nhờ long-format index.

### #2. Long-format schema → **Two-tier**

**Không chọn**:
- Minimal (chỉ retrieve): bỏ lỡ cơ hội canonicalize BS/PL/CF
- Full uniform: canonicalize note table tốn công gấp 10, không chắc đúng

**Chọn**: Full long-format cho **BS/PL/CF** (dùng `ma_so` làm anchor stable — cover 60-70% câu lookup metric chính). Minimal cho **note tables** (giữ raw, retrieve bằng row_label + BM25).

### #3. Table type classifier → **Rule + LLM Haiku fallback**

**Không chọn**:
- Rule-only: OCR có noise, một số bảng thiếu tiêu đề rõ
- LLM-only: ~10k call tốn không cần thiết cho case dễ

**Chọn**: Rule chạy trước, log **confidence** (high = có tiêu đề + cột `Mã số`; medium = 1 signal; low = không có). LLM Haiku chỉ chạy trên medium+low (~20% bảng). Rẻ + có ground truth verify.

### #4. Row canonicalization → **Layer 1 alias dictionary + Layer 3 LLM (skip embedding)**

**Không chọn**:
- Chỉ dictionary: kém với biến thể ("LN ròng" = "LNST" = "lãi sau thuế")
- Chỉ embedding: false positive nguy hiểm ("chi phí lãi vay" vs "lãi tiền gửi")
- Chỉ LLM: cost mỗi query

**Chọn**:
- **Chiều A** (build-time): `ma_so → metric_canonical` dictionary tay ~50-100 entries cho BS/PL/CF.
- **Chiều B layer 1** (query-time): alias dictionary tay match rõ (`"Doanh thu thuần"` → `10`).
- **Chiều B layer 3** (query-time fallback): LLM Haiku khi layer 1 miss/ambiguous.
- **Embedding**: skip ở brainstorm, add sau nếu eval cho thấy BM25 miss ở note.

### #5. Period column parser → **Rule regex** (không grilling)

Regex trên tên cột: `2018VND`, `31/12/2018`, `Năm 2018` → `{period_type, year, snapshot_date}`.

### #6. Retrieval strategy → **Structured filter + BM25 + embedding (full stack)**

**Không chọn**:
- Structured filter only: không phân biệt note nào trong ~20-40 note của 1 report
- Structured + BM25: đủ 90% nhưng miss câu semantic mờ

**Chọn (for safety)**: Full stack.
- Structured filter (`ticker + year + doc_type + statement_type`) — signal mạnh nhất
- BM25 trên `(note_title + row_labels)` — cho note
- Embedding fallback — cho câu semantic mờ ("vay ngân hàng" ↔ "vay và nợ thuê tài chính")

### #7. LLM prompt shape → **Two-stage (selector + coder)**

**Không chọn**:
- Single-shot top-1: retrieval sai 1 → hỏng
- Full agentic tool-use: cost cao, khó cap, premature

**Chọn**: Two-stage.
- **Stage 1 (selector)**: LLM thấy `[list of K tables với title + 5 dòng đầu]` → chọn tables cần dùng + lý do.
- **Stage 2 (coder)**: LLM thấy full CSV của tables đã chọn + metric_hint + unit_hint → viết `pandas_query`.
- 2 stage có thể trong 1 call (CoT) hoặc 2 call riêng.

**Mode A vs Mode B**: 1 pipeline auto-adjust context size, không rẽ nhánh cứng. Mode = độ dài context feed vào Stage 2, không phải architecture riêng.

**Fallback tương lai**: Full agentic tool-use chỉ dùng cho câu L6 fail ở Stage 2 → add sau khi có eval.

### #8. Eval harness → **50-câu gold set + health metrics + submit outer-loop**

**Không chọn**:
- Multi-model cross-check (B): consensus giả nhiều
- Self-consistency (C): không đo correctness tuyệt đối

**Chọn (A + D)**:
- **Gold set**: mở rộng 12 câu → **50 câu tay** stratified L1-L6 (~8/L). Là kênh **debug duy nhất** ở granularity câu.
- **Health metrics D** trên full 1012:
  - `%` `pandas_query` chạy không lỗi
  - `%` answer là float finite
  - `%` answer trong range hợp lý theo unit_hint
  - `%` `relevant_tables` retrieve ra tồn tại
- **Submission**: outer-loop validation only, không debug per-question. Routine:
  - Baseline: 1 submit khi pipeline chạy hết 1012 không crash
  - Sau đó chỉ submit khi gold set A improve rõ, hoặc health D cải thiện ≥5%
  - Còn dư slot: A/B experiment cuối

---

## 6. Pipeline shape kết hợp (v0)

```
Raw HTML (1973 reports) [DATASET]
  ↓ [extract_tables] ✅ DONE
Raw CSV per table (~10k)
  ↓ [table_type_classifier: rule confidence + LLM Haiku fallback]  ⚠ BUILD
Tables labeled: statement_type, note_id, period_columns, has_ma_so
  ↓ [long_format_builder]                                          ⚠ BUILD
  │   ├─ full: BS/PL/CF (ma_so → metric_canonical, value_float)
  │   └─ minimal: note (row_label_raw only)
  ↓
Long-format index (parquet)  ← STORAGE LAYER
  ↓
  + [BM25 index on note (note_title + row_labels)]                 ⚠ BUILD
  + [embedding index for semantic fallback]                        ⚠ BUILD
  ↓
─────────────────────────── (build-time above / query-time below)
  ↓
Question
  ↓ [question_parser: LLM Haiku]                                   ⚠ BUILD
Intent JSON: {ticker, year, doc_type, metric_hint, unit, complexity}
  ↓ [retrieval: structured filter → BM25 → embedding rerank]       ⚠ BUILD
Top-K candidate tables (K=3-5)
  ↓ [LLM Stage 1: selector — pick tables + reason]                 ⚠ BUILD
Chosen tables (1-N subset)
  ↓ [LLM Stage 2: coder — write pandas_query]                      ⚠ BUILD
pandas_query string
  ↓ [executor: sandbox pandas eval on raw CSV]                     ⚠ BUILD
answer: float
  ↓
Submission row: {id, question, answer, relevant_docs, relevant_tables, evidence, pandas_query}
```

Song song (không nằm trong pipeline):
- **Gold set 50 câu tay**: debug per-question, đo accuracy
- **Health metrics D** trên full 1012: proxy quality không cần label

---

## 7. Việc cần làm sau brainstorming (thứ tự)

1. **Mở rộng gold set** 12 → 50 câu tay, stratify L1-L6.
2. **Long-format schema definition** (parquet, `.py`).
3. **Table type classifier** rule prototype, log confidence trên ~10k bảng.
4. **Question parser** prompt design cho Haiku, test trên 50 gold.
5. **Alias dictionary** tay ~80 entries cho BS/PL/CF metrics chính.
6. **Executor** hàm chạy `pandas_query` an toàn (sandbox eval trên df).
7. **Baseline pipeline** end-to-end trên gold 50 → đo accuracy; rồi trên full 1012 → đo health D.
8. **Submit smoke test** khi baseline chạy full không crash.

---

## 8. Câu hỏi mở (chưa chốt, cần làm sau brainstorm)

### 8.1. Metadata / storage
- **8.1.1** Long-format parquet lưu ở đâu? 1 file monolithic hay chia partition theo `ticker`/`year`? (partition tốt cho retrieval filter)
- **8.1.2** Có nên tách bảng note-matrix (roll-forward TSCĐ) thành shape đặc biệt không? Hay giữ raw + để LLM Stage 2 xử lý?
- **8.1.3** Column semantics trong note (cost/carrying/fair_value/recoverable) — có canonicalize không, hay để row_label OCR tự nói?
- **8.1.4** [POST-V0] **Sub-header trước table** (`(a)`, `(b)`, `(c)` trong VD trang note): thêm field `table_subtitle` khi extract — dễ, đáng làm sớm.
- **8.1.5** [POST-V0] **Paragraph có số ngoài bảng**: v0 quyết định **KHÔNG index** (option B từ discussion 2026-08-02). Rủi ro: câu hỏi kiểu *"lãi suất tiền gửi năm 2018 của VJC là bao nhiêu %"* — số nằm trong đoạn văn thuyết minh, không bảng nào chứa. Ví dụ observed từ VJC 2018: `Line 633: "lãi suất năm từ 5,5% đến 8,3%"`, `Line 664: "giá trị thanh lý 16.271.500.000 VND"`, `Line 635: "gửi tại HDBank 1.749 tỷ VND"`. **Sẽ đo tỉ lệ fail** sau khi có baseline eval + gold set, mới quyết định add hay không. Nếu add cần: (a) extract paragraph có số VND-ish, loại boilerplate `Mẫu B`, `Thông tư`, header/footer; (b) index BM25+embedding cùng note tables; (c) fallback CSV-of-chunks giả cho `pandas_query` executable (submission bắt buộc).

### 8.2. Retrieval
- **8.2.1** BM25 index tokenize thế nào cho tiếng Việt (accent-sensitive? underthesea? space-only)?
- **8.2.2** Embedding model nào cho tiếng Việt tài chính? `bge-m3`, `vietnamese-embedding`, hay multilingual-e5?
- **8.2.3** Top-K bằng bao nhiêu? 3 (tight) hay 5-8 (recall cao)?
- **8.2.4** Có nên rerank K bằng cross-encoder không?

### 8.3. LLM prompt / model
- **8.3.1** Stage 1 và Stage 2 cùng model hay khác? (Haiku Stage 1, Sonnet Stage 2?)
- **8.3.2** Few-shot examples nào cho Stage 2? Mỗi op 1 example, hay universal 3 examples?
- **8.3.3** Temperature = 0 hay 0.2? (0.2 cho creative L6, 0 cho reproducibility)
- **8.3.4** `pandas_query` được sinh dạng gì: `df.query(...)`, `df[...]`, hay code block đa dòng `import pandas as pd; df = pd.read_csv(...); result = ...`?
- **8.3.5** Nếu LLM sinh code có lỗi thì retry với error message như tool feedback không? (giới hạn 2-3 retry)

### 8.4. Ticker & question parsing
- **8.4.1** Question parser (Haiku intent extract) có return `metric_canonical` luôn không, hay chỉ `metric_hint` string?
- **8.4.2** "Công ty mẹ" trigger `doc_type=separate` — rule tuyệt đối hay có exception?
- **8.4.3** Câu hỏi có nhiều ticker (L4/L5 cross-company) — retrieve từng ticker rồi merge, hay retrieve chung?
- **8.4.4** Multi-year question (L3/L5) — retrieve từng năm rồi merge, hay retrieve chung?

### 8.5. Derived metric
- **8.5.1** Derived metric dictionary được nhét vào prompt LLM (system prompt) hay dùng như tool để LLM query?
- **8.5.2** ROA/ROE dùng "TTS bình quân" hay "TTS cuối kỳ"? (theo VAS chuẩn là bình quân, nhưng nhiều báo cáo tính cuối kỳ)
- **8.5.3** EBIT tính theo mã 50 + mã 23 (LN trước thuế + chi phí lãi vay), nhưng chi phí lãi vay đôi khi nằm ở note, không cột PL — xử thế nào?

### 8.6. Evaluation
- **8.6.1** 50 câu gold stratify chỉ theo L1-L6, hay thêm axis doc_type (bank/securities/non-financial/insurance)?
- **8.6.2** Health metric D có "range hợp lý" cụ thể như nào? (VND > 1e15 = red flag, nhưng "tổng tài sản Vietcombank" thì đúng > 1e15)
- **8.6.3** Có nên track thời gian sinh mỗi câu để bắt câu bị agentic loop không?
- **8.6.4** Nếu submit v1 = 0.6 và v2 = 0.55, làm sao biết là do regression hay do variance? (cần chạy pipeline 2 lần cùng version để đo variance)

### 8.7. Cost & scale
- **8.7.1** Budget LLM total cho toàn dataset là bao nhiêu? (ảnh hưởng chọn Haiku vs Sonnet cho các stage)
- **8.7.2** Có nên cache LLM output (question_parser, Stage 1 selector) để tăng tốc thử nghiệm?
- **8.7.3** Table type classifier chạy 1 lần một cho tất cả 10k bảng, hay lazy compute?

### 8.8. Cạnh tranh / submission strategy
- **8.8.1** 10 submit/ngày — dùng thế nào tối ưu? Khi baseline > 0.5 mới bắt đầu A/B?
- **8.8.2** Có nên submit sớm (1 tuần đầu) để biết baseline scoring khoảng nào không, kể cả pipeline chưa tốt?
- **8.8.3** Câu bị `pandas_query` fail thì submit `answer=0.0` hay bỏ trống? Rule scoring xử lý thế nào?

---

## 9. Không chốt ở phiên này (parking lot)

- **Full agentic tool-use** (Q6 option 4): parking, add sau baseline
- **Bisection submit strategy** (Q eval): parking, dùng khi có ≥2 candidate cuối cùng
- **Metric embedding** (Q4): parking, add nếu dictionary + LLM miss > 15% ở gold
- **Multi-model cross-check eval**: parking, add nếu 50-câu gold không scale

---

## 10. Trạng thái hiện tại

**Đã có**:
- ✅ Table extraction từ HTML (`scripts/extract_tables.py`, `data/tables/`)
- ✅ Question taxonomy L1-L6 doc
- ✅ 12 câu giải tay (`data/eval/manual_solutions/solutions.md`)
- ✅ Lessons doc (`data/eval/manual_solutions/LESSONS.md`)
- ✅ Op classifier experiment (`scripts/classify_ops.py`, `artifacts/reports/ops_report.md`)
- ✅ HTML data viewer (raw mode) [đã bỏ structured mode]

**Chưa có** (từ mục 7):
- ⏳ Gold set 50 câu (bottleneck công tay)
- ⏳ Long-format builder + storage
- ⏳ Table type classifier
- ⏳ Question parser
- ⏳ Retrieval index (BM25 + embedding)
- ⏳ Two-stage LLM pipeline
- ⏳ Executor
- ⏳ Baseline submission

**Bước tiếp theo đề nghị**: mở rộng gold set 12 → 50 câu tay (bước 1 trong mục 7). Đây là bottleneck rẻ nhất về infra, đắt nhất về công tay, nhưng là kênh debug duy nhất khi không có label.
