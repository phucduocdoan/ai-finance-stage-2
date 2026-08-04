# V0 Retrieval Pipeline — Design chốt

> **Trạng thái implementation:** Đây là nhật ký thiết kế và thí nghiệm, không
> phải mô tả chính xác tuyệt đối của entrypoint hiện tại. Policy tốt nhất ở các
> phần sau (`strip` query + primary expansion + `judge_text`) đang có trong
> `scripts/dump_pools.py`, nhưng `scripts/evaluate_retrieval.py` chưa dùng đủ ba
> phần. Xem `docs/HANDOFF.md` trước khi chạy hoặc diễn giải benchmark.

**Ngày**: 2026-08-03
**Nguồn**: /grilling session với user (Q1-Q7)
**Scope**: Retrieval-only baseline, eval nội bộ trên 24 manual_solutions. Chưa gắn LLM coder/executor.
**Input**: `data/metadata/tables_metadata_v2.jsonl` (146,246 bảng), `data/metadata/questions_enriched.jsonl` (1,012 câu, tickers/years đã resolved 99.9%)

---

## Pipeline

```
Question
  ├─ Rule enrich (99.9% verified): ticker, year, unit_hint,
  │                                 doc_type_if_explicit
  └─ LLM enrich (Qwen3-8B @ localhost:8990):
       statement_type_hint, note_topic_hint, metric_hint

Table candidates (146,246) — mỗi bảng 1 sample độc lập
  ├─ doc_text = statement_label | note_title | section_title
  │             | first_col_labels_joined | header_flat
  │             (KHÔNG có context_page_text, KHÔNG có cell values)
  │
  ├─ Hard filter: ticker AND year (+ doc_type nếu câu hỏi nói rõ)
  │             + has_content (num_rows > 2 AND first_col_labels)
  │             + prefer_consolidated khi câu không nói scope
  │             → shortlist med 205, max 463 (trên eval set)
  │
  ├─ BM25 top-20 ∪ bge-m3 dense top-20 (cùng doc_text)
  │             → UNION pool (med 38, max 95), KHÔNG cắt bằng RRF
  │             (RRF chỉ dùng để order prompt cho deterministic)
  │
  ├─ (bỏ cross-encoder — đo rồi, làm tệ hơn; xem "Reranker: negative result")
  │
  └─ LLM judge (Qwen3-8B, enable_thinking=true) → top-K final (≤10)
        Input thí nghiệm tốt nhất: câu hỏi + [{[i], report_id, judge_text}]
        Context được budget động; không truncate cố định 400 ký tự.
        Output: {"picks": [...index...]}

Submission: report_id + table_pos như trả về. KHÔNG expand continuation group.
Eval: recall@K (K=5,10,20) trên 24 manual_solutions, break theo L1-L6.
```

## 7 quyết định

### Q1 — Baseline dừng ở đâu? → **Retrieval-only (A)**
Build retrieval + eval `recall@K` trên 24 manual_solutions (ground truth `report_id|table_pos` verified) trước khi gắn LLM coder. Debug per-level rẻ hơn debug E2E leaderboard.

### Q2 — Kiến trúc → **LLM enrich + Filter + BM25 + Dense + Rerank + LLM judge**
Xác nhận theo đề xuất user. Bổ sung LLM judge cuối vì competition cần `relevant_docs` + `relevant_tables` chính xác top-K (không chỉ top-1).

### Q3 — LLM enrich schema → **C (Minimal semantic)**
LLM chỉ bù 3 field semantic (`statement_type_hint`, `note_topic_hint`, `metric_hint`). Giữ nguyên rule cho ticker/year/doc_type/unit (99.9% correct, LLM chạy lại là regression risk).

### Q4 — Filter chặt/lỏng → **B (Hard: ticker+year only)**
Chỉ hard filter 2 field rule-based đã verify. `doc_type`/`statement_type` là soft signal — không hard cut vì LLM hint chưa verify độ chính xác. Exception: câu hỏi nói rõ "công ty mẹ"/"riêng lẻ"/"hợp nhất" → hard doc_type cho câu đó.

**Semantics chính xác của hard filter** — implement ở `src/finance_qa/retrieval/filters.py`, đo trên `data/eval/evalset.json` (2026-08-03):

```
keep table nếu:
    table.ticker ∈ q.tickers
AND table.year   ∈ q.years                # q.years đã expand range "2016-2020"
AND ( q.doc_type == "unknown"             # câu không nói scope → KHÔNG filter
      OR table.doc_type == q.doc_type
      OR table.doc_type ∈ {aggregated, explanations} )   # luôn cho qua

THEN nếu q.doc_type == "unknown":         # ưu tiên mềm consolidated
    bỏ bảng `separate` của (ticker, year) nào cũng có consolidated
    hoặc có báo cáo không suffix scope
```

**`prefer_consolidated`** (thêm 2026-08-03, user chốt "ưu tiên mềm consolidated"): enrich trả `doc_type = "unknown"` cho **12/15** câu table-tier, nên chân `doc_type` ở trên thực tế **đã chết** — filter degrade về `ticker AND year` và shortlist đầy bản sao sai scope. #605: pool 68 candidate gồm 32 bảng `2024_separate` + 18 `2023_separate`, đẩy GT consolidated xuống rank 50. Trong cả 9 câu unknown mà GT có scope, GT **đều là consolidated** — đúng nghĩa: câu không nói "công ty mẹ"/"riêng" là đang hỏi về tập đoàn.

Ưu tiên là **mềm và theo từng (ticker, year)**, không global: một ticker nộp consolidated năm 2020 nhưng chỉ có separate năm 2021 thì phải giữ separate của 2021, không thì câu multi-year mất trắng năm đó. Verify: 0 GT bị loại trên cả 24 câu eval.

- `q.doc_type` chỉ có 3 giá trị: `separate` (363 câu) / `consolidated` (13) / `unknown` (636). **KHÔNG có** `bank`/`securities`/`insurance` — đó là trục *ngành*, không phải scope, và không khớp bất kỳ bảng nào (vocab của corpus là `{consolidated, separate, aggregated, explanations}`). Bug cũ này kéo ceiling xuống 47.2%.
- `aggregated` = tên file report **không có** suffix `_consolidated`/`_separate` (vd `FTS_financial_statements_2021`). Với công ty standalone thì đó *chính là* báo cáo riêng ⇒ phải luôn cho qua. Không có passthrough này, Q8/Q336/Q786/Q809 ("công ty mẹ" FTS/HND) được 0 candidate.
- Câu nói **cả hai** scope (#952: "báo cáo công ty mẹ các năm 2022, 2023 và báo cáo hợp nhất các năm 2024, 2025") → `unknown`, không filter.
- **Degrade gracefully**: nếu `q.tickers` rỗng (#464 "trong các công ty…") hoặc `q.years` rỗng (#412) thì bỏ chiều đó thay vì trả shortlist rỗng. 2/1012 câu (0.2%). Đã implement ⇒ **0 câu** shortlist rỗng trên toàn bộ 1012. Giá phải trả: #464 nở ra 18.554 candidate (mọi bảng năm 2015+2016) — 1 câu, để rerank+judge xử.

Ceiling (recall trên shortlist, tức mức trần của mọi thứ downstream):

| Tier | Ceiling | L1 | L2 | L3 | L4 | L5 | L6 |
|---|---|---|---|---|---|---|---|
| report-level (24 câu, 58 group) | **58/58 = 100%** | 4/4 | 4/4 | 8/8 | 8/8 | 19/19 | 15/15 |
| table-level (15 câu, 36 group) | **36/36 = 100%** | 4/4 | 3/3 | 3/3 | 4/4 | 10/10 | 12/12 |

### Q5+Q6 — BM25 & Dense field → **Cùng 1 doc_text, chỉ text field**
Mental model: structured metadata → filter/rerank; text field → BM25+dense. Không trộn 2 loại.
- doc_text = `statement_label | note_title | section_title | first_col_labels_joined | header_flat`
  (bản trước ghi `parent_section` — field này **không tồn tại** trong `tables_metadata_v2.jsonl`)
- **Bỏ `context_page_text`** — có OCR noise, có thể chứa cell values, không cần cho retrieval routing (LLM coder query long_format, không đọc content từ index).

**`statement_label`** (thêm 2026-08-03): báo cáo chính **không phải** "note" nên không có `note_title`, và 4,696 bảng CĐKT cũng không có `section_title` — doc_text của chúng mở đầu bằng nhãn dòng thô ("C. NỢ PHẢI TRẢ I. Nợ ngắn hạn 1. Phải trả người bán…"), **không có gì nói bảng này là bảng gì**. 11/13 GT table của eval set chính là loại bảng đó. Fix: prepend tên tiếng Việt của `statement_type` (+ `statement_subtype` cho `bs_assets` / `bs_liabilities_equity`), chỉ cho 5 loại non-note (~19k/146k bảng ⇒ signal rất discriminative); 124,279 dòng `note` không gán nhãn vì thêm một string hằng thì vô nghĩa mà vẫn tốn 30 ký tự trong mỗi candidate LLM judge phải đọc.

`statement_type` nằm sẵn trong `tables_metadata_v2.jsonl` từ đầu và `build_doc_text.py` chỉ đơn giản là **chưa dùng**.

### BM25 baseline (implement `src/finance_qa/retrieval/bm25.py`, đo bằng `scripts/evaluate_retrieval.py`, 2026-08-03)

Không dùng `rank_bm25`: hard filter đã cắt còn median 226 candidate nên không bao giờ score full corpus. Chỉ cần **IDF global** (df trên cả 146,246 bảng — nếu tính IDF trong shortlist thì trọng số của "tiền" phụ thuộc câu hỏi), tf tính lazy trên shortlist. Vocab 29,539 term, avgdl 78.7 token, IDF build 4.8s, score 1.0 ms/500 candidate.

BM25-only, k1=1.5 b=0.75, trên 24 câu eval:

| tier | @5 | @10 | @15 | @30 | @50 |
|---|---|---|---|---|---|
| table (15 câu, 36 group) | 28.0% | 40.7% | **44.0%** | 65.3% | 82.0% |
| report (24 câu, 58 group) | 88.5% | **100%** | 100% | 100% | 100% |

Report tier về cơ bản **free** — hard filter làm gần hết việc, nên bài toán thật là table-level.

**Chẩn đoán 10 câu miss @15**: cả 4 câu miss 0% đều có GT là **báo cáo chính** (CĐKT / KQKD) bị xếp hạng 17-39, thua các bảng thuyết minh ngắn. Ví dụ #44 "Tổng tài sản STB 2016" → GT rank 39; #17 "Lãi thuần hoạt động dịch vụ SHB" → rank 17; #605 → rank 34. Cơ chế: BM25 chuẩn hoá độ dài (`b`) với giả định doc dài là doc "lan man", nhưng ở đây **độ dài ≈ số dòng của bảng**, mà CĐKT có 60 line item là chuyện bình thường. Length penalty đang phạt đúng những bảng giá trị nhất.

Sweep `b` xác nhận đúng chiều nhưng **chưa chốt**:

| b | @5 | @15 | @50 |
|---|---|---|---|
| 0.75 (default) | 28.0% | 44.0% | 82.0% |
| 0.10 | 28.0% | 56.0% | 86.7% |
| 0.00 | 21.3% | **62.7%** | 86.7% |

Giữ `b=0.75` ở V0, **chưa đổi**, vì: (1) @5 *tệ đi* khi b→0 và đường cong không monotonic; (2) 15 câu / 36 group ⇒ 1 group = 2.8pp, mức tăng 18.7pp ở @15 chỉ là ~6.7 group — đúng rủi ro overfit ghi ở mục 4 phần cần xác nhận; (3) dense được thêm chính là để giải quyết mismatch từ vựng + độ dài này, nên sau khi có RRF thì `b` có thể hết quan trọng. Quyết định lại sau khi có dense, và nếu đổi thì phải đổi vì cơ chế, không vì con số trên 15 câu.

**Kết luận `b` (2026-08-03, sau khi tì ra root cause): moot.** Chẩn đoán "báo cáo chính thua bảng note ngắn" ở trên là **cùng một lỗi** với `statement_label` thiếu — không phải length normalization sai, mà là bảng CĐKT/KQKD **không có tiêu đề trong doc_text** nên chỉ khớp được bằng nhãn dòng. Sweep `b` là dán băng lên triệu chứng. Sau khi thêm `statement_label`, BM25 với `b=0.75` nguyên bản nhảy từ 44.0% lên **72.0%** ở @15 — hơn cả `b=0` (62.7%). Giữ `b=0.75`, đóng hồ sơ.

### Q7 — Fusion + Rerank
- **Fusion**: RRF (k=60) — không cần calibrate scale giữa BM25 và cosine.
- **K₁=K₂=50** (mỗi kênh), **N=30** (input rerank), **top-15** (input LLM judge), **top-K final=5-10** (output submission).
- ⚠️ **Đã sửa sau khi đo** — xem "Dense + LLM judge" và "Nhóm A" bên dưới: cross-encoder bị bỏ (đo tệ hơn), pool đưa vào judge là **union** chứ không phải RRF top-30, và K₁=K₂ đã hạ **50 → 20**.
- **Bỏ soft signal hardcode** ở rerank (weight 0.10/0.05 tôi bịa, 24 sample không đủ tune).
- Metadata secondary (`statement_type`, `doc_type`, `has_ma_so_column`) đưa vào **LLM judge prompt** làm context, để LLM tự cân nhắc.
- **Bỏ `is_continuation` khỏi judge prompt** — `detect_continuation` quét cả `section_title`, nên `CONT_RE` khớp running page header của phần thuyết minh; ~65% giá trị `true` là noise. Semantics đúng của field vẫn ghi ở dưới, nhưng giá trị hiện tại không tin được.

### Dense + LLM judge (implement `src/finance_qa/retrieval/dense.py` / `src/finance_qa/retrieval/judge.py`, đo 2026-08-03)

User chốt: *"thêm dense xem thế nào nhé, chưa cần rerank model mà cứ dùng llm local làm rerank cũng được"*.

Table tier (15 câu, 36 group), sau khi đã có `statement_label` + `prefer_consolidated`. Format `recall / all-hit`:

| stage | @5 | @10 | @15 | @30 | @50 |
|---|---|---|---|---|---|
| BM25 | 34.0/26.7 | 72.0/66.7 | 72.0/66.7 | 78.7/73.3 | 83.3/80.0 |
| dense (bge-m3) | 30.0/26.7 | 50.0/46.7 | 50.0/46.7 | 77.3/73.3 | 86.0/73.3 |
| RRF (k=60) | 23.3/20.0 | 56.0/46.7 | **72.7/66.7** | **88.0/86.7** | 90.7/86.7 |
| **union pool** (ceiling của judge) | — | — | — | — | **92.0/86.7** |
| judge, no thinking, cắt 400 ký tự | 56.0/46.7 | 65.3/53.3 | 69.3/60.0 | — | — |
| judge, thinking, cắt 400 ký tự | 54–56/40–47 | 70.7–82.0 | 84.0–88.7 | — | — |
| **judge, thinking, full doc_text** | **61.3/46.7** | 72.0/60.0 | **85.3/80.0** | 92.0/86.7 | 92.0/86.7 |

(Dòng cuối là `eval_retrieval.py --stage judge` chạy end-to-end; @30 chạm đúng ceiling 92.0% vì pick của judge được đẩy lên đầu, phần còn lại giữ nguyên thứ tự retrieval.)

Report tier: **100% ở mọi K, mọi stage** — hard filter làm hết việc, bài toán thật vẫn là table-level.

Bốn kết luận:

1. **Dense một mình yếu hơn BM25** ở K nhỏ (50.0 vs 72.0 @15) nhưng **bù được ở đuôi** (86.0 vs 83.3 @50) và miss những câu khác BM25. Nó có giá trị như **nguồn candidate**, không phải như ranker.
2. **Union > RRF khi phía sau là LLM judge.** Judge đọc *toàn bộ* pool, nên thứ tự trong pool không quan trọng — chỉ recall của pool quan trọng. Union@50 = 92.0% vs RRF@30 = 88.0%. RRF làm *mất* candidate vì ranking dense đủ noisy để fusion đẩy hit xấu của dense lên trên hit tốt của BM25. ⇒ **Bỏ bước cắt top-30**; RRF chỉ còn dùng để order prompt cho deterministic.
3. **`enable_thinking=true` là bắt buộc.** Không thinking, judge lấp đủ quota 10 pick với precision kém (`picks med 10`, @15 69.3%); có thinking nó chọn `med 2-3` và @15 lên 84-89%. Giá: 6s → ~90-110s cho 15 câu ở 4 worker.
4. **`DOC_CHARS = 400` là bug thật, không phải tham số cần tune.** Đo `picks only` (đúng thứ đi vào `relevant_tables`, không có đuôi retrieval đệm) chỉ được 54–55%. Giả thuyết đầu tiên — "judge quá kiệm, chọn 3 bảng khi câu cần 5" — **sai**: bảng per-question cho thấy câu nhiều group đã tốt (#818 5/5, #524 5/5, #820 4/5, group thứ 5 nằm ngoài pool), còn hỏng là mấy câu **1 bảng** (#17, #55, #100, #605, #752) — judge chọn *sai* bảng dù GT nằm ở pool pos 6–12. Prompt bắt "đếm số bảng cần trước khi chọn" **thua** cả baseline (53.3% / 58.7%), đúng như dự đoán của chẩn đoán này.

   Nguyên nhân thật: **5/6 GT hỏng đều dài >400 ký tự và chỉ tiêu được hỏi nằm sau mốc cắt.** KQKD ngân hàng dài 750–950 ký tự, "Lãi thuần từ hoạt động dịch vụ" ở khoảng char 430; "TỔNG TÀI SẢN" là nhãn **cuối cùng** của bảng CĐKT 1,095 ký tự. Judge bị bắt phán mà không được xem bằng chứng. Bỏ truncation ⇒ `picks only` 54.7% → **61.1%** (mean 3 lần: 64.0/57.3/62.0), @5 55.0% → 62.9%. Chi phí: pool xấu nhất (86 candidate) ~17.5k token, vừa cửa sổ 32k với 4k thinking budget.

**Caveat về noise**: cùng config `thinking` chạy 2 lần cho @15 = 88.7% rồi 84.0%, tập miss khác nhau (`582` xuất hiện lần 2). `temperature=0` nhưng vLLM batch động ⇒ kernel không bit-exact. Với n=15 câu / 36 group, 1 group = 2.8pp, nên **mọi chênh lệch dưới ~6pp trên eval set này là noise**, kể cả số của chính bảng trên.

**`picks only` vẫn là bottleneck (61%), không phải pool (92%)** — nhưng bottleneck còn lại là *phân biệt giữa các bảng gần giống nhau trong cùng report*, và judge chỉ nhìn `report_id` + doc_text, **không nhìn `table_pos`**. Chưa xử ở V0.

**2 câu ngoài tầm mọi judge** (GT không có trong pool, cần sửa retrieval chứ không phải sửa prompt):
- **#363** (L6, 7/7 group absent): KBC 2016/2018/2020 consolidated.
- **#820** (L5, 1/5 group absent): `SNZ_financial_statements_2018_separate|7`.

`/tmp/pools.json` (cache cho `scripts/judge_ab.py`) dump bằng `scripts/dump_pools.py`; nó **stale ngay khi** doc_text hoặc dense index rebuild.

---

### Root cause của phần table-level còn lại (2026-08-04)

Report tier đã 100% ⇒ bài toán thật là **chọn đúng bảng bên trong 1 report đã tìm ra**. `scripts/diag_intra_report.py` đo đúng đại lượng đó: rank của GT **giữa các bảng cùng report** (không phải rank trong corpus).

| | top1 | top3 | med |
|---|---|---|---|
| BM25 intra-report | 30.6% | 36.1% | #8 |
| dense intra-report | 19.4% | 22.2% | #9 |

Tức là ngay cả khi đã biết đúng report, GT vẫn nằm hạng ~8/60–120. `scripts/diag_repr.py` tách nguyên nhân theo loại GT:

| statement_type của GT | n | top3 hiện tại | top3 nếu ép đúng type | loại này chiếm % bảng/report |
|---|---|---|---|---|
| note | 14 | 71.4% | 71.4% | 71% |
| income_statement | 11 | 81.8% | **100%** | 2% |
| balance_sheet | 11 | **18.2%** | **100%** | 5% |

**Toàn bộ thiệt hại nằm ở câu hỏi về báo cáo chính, đặc biệt bảng cân đối kế toán.** Cơ chế: CĐKT chiếm ~5% số bảng của một report, notes chiếm ~71%; câu hỏi về CĐKT ("D/E", "tổng tài sản", "vay ngắn hạn", "khả năng thanh toán") **không chứa từ nào khớp mặt chữ với nhãn dòng CĐKT**, nên thua các note dài, giàu từ vựng tài chính (VAY, VỐN CHỦ SỞ HỮU, HÀNG TỒN KHO). Câu hỏi về note thì ngược lại — nó trích gần nguyên `note_title`, nên đã tốt sẵn.

⇒ **Không phải lỗi của biểu diễn text.** Đo thẳng giả thuyết "đơn giản hơn thì tốt hơn" (bỏ nhãn dòng, chỉ giữ tiêu đề) và nó **thua nặng**: top5 44.4% → 13.9%. Nhãn dòng là tín hiệu phân biệt chính, không được cắt (nhất quán với việc bỏ `DOC_CHARS=400` ở trên). Cái thiếu là một **chiều "loại báo cáo"**, không phải thêm/bớt chữ.

**Hai sửa đổi, đo trên union pool recall (= ceiling của judge):**

| | pool recall | all-hit | pool med / max |
|---|---|---|---|
| hiện tại | 92.0% | 86.7% | 69 / 86 |
| `strip` | 97.1% | 93.3% | 70 / 86 |
| `primary` | 100.0% | 100.0% | 69 / 128 |
| **`strip` + `primary`** | **100.0%** | **100.0%** | 71 / 131 |

- **`strip`** — bỏ token ticker / năm / tên công ty khỏi **query retrieval** (giữ nguyên câu hỏi cho judge). Hard filter đã tiêu thụ xong ticker+year rồi: mọi candidate đã đúng công ty đúng năm, nên tên công ty trong câu hỏi chỉ còn tác dụng đẩy các bảng `entity_info` / "THÔNG TIN DOANH NGHIỆP" — chính là thứ đè GT xuống ở #820 và #100.
- **`primary`** — nhét thẳng vào pool **mọi bảng `balance_sheet` / `income_statement` / `cash_flow` / `equity_change`** của mọi report trong shortlist, vô điều kiện. Không cần query classifier, không cần đoán câu hỏi hỏi báo cáo nào: 4 loại này chỉ ~10% số bảng của một report nên chi phí nhỏ, đổi lại recall của báo cáo chính thành **đúng-theo-cấu-trúc** thay vì phụ thuộc BM25 xếp hạng.

Đây chính là thứ vớt được **cả 2 câu trước đây ngoài tầm**: 7/7 group của #363 là bảng CĐKT KBC, group thiếu của #820 là KQKD SNZ.

**Judge có convert được không** (cùng config thinking, full doc_text):

| pool | @5 | @10 | @15 | picks only |
|---|---|---|---|---|
| cũ (92% ceiling) | 61.3/46.7 | 72.0/60.0 | 85.3/80.0 | ~61% |
| **strip+primary (100% ceiling)** | **74.5/66.7** | **83.4/73.3** | 88.1/80.0 | 55.4/46.7 |

@5 +13pp và @10 +11pp — vượt ngưỡng noise 6pp, và cơ chế lẫn số liệu đồng thuận ⇒ nhận. `picks only` đứng yên trong khoảng noise: judge vẫn `picks med 2`, tức **bottleneck đã dịch hẳn từ retrieval sang judge**. Pool giờ hoàn hảo; mọi điểm mất còn lại là judge chọn thiếu/chọn sai.

---

### Context overflow — bug thật, không phải judge kém (2026-08-04)

Pool `strip+primary` max 131 candidate làm prompt tràn 32k: **92,620 ký tự = 32,775 token**, server trả HTTP 400 và `judge()` nuốt lỗi thành pick rỗng ⇒ #818 ăn 0/5 **dù GT nằm ngay pool vị trí 0–4**. Suốt 2 lần đo trước nó trông y hệt "judge chọn tệ".

Ước lượng cũ (~26k token) sai vì tôi lấy ~2 ký tự/token; **tiếng Việt trên corpus này là ~2.83 ký tự/token**. Sửa 3 chỗ:

1. **Tách 2 view trên cùng một hàng** — `scripts/build_doc_text.py` xuất cả `doc_text` (cho index) và `judge_text` (cho prompt). Retrieval và judge cần thứ khác nhau:

   | field | % ký tự prompt | có phân biệt được các bảng trong cùng report? | doc_text | judge_text |
   |---|---|---|---|---|
   | `first_col_labels` | 73.0% | **có — đây là tín hiệu chính** | ✅ | ✅ |
   | `header_flat` | 14.0% | không (cột kỳ, giống hệt nhau cả report) | ✅ | ❌ |
   | `section_title` | 8.1% | không (boilerplate "THUYẾT MINH BCTC HỢP NHẤT (tiếp theo)", 57.5% coverage) | ✅ | ❌ |
   | `note_title` | 4.9% | có | ✅ | ✅ |

   Bỏ 22% context của judge mà không mất tín hiệu. **Vẫn giữ trong `doc_text`** vì bỏ `header_flat` khỏi index làm *tụt* retrieval (intra-report top5 72.2% → 63.9%) — BM25 tự chiết khấu boilerplate bằng IDF, còn LLM thì không.
2. **Budget thay vì truncate cố định** — `CAP_LADDER` trong `llm_judge.build_prompt`: giữ **đủ mọi candidate**, chỉ siết dần độ dài từng bảng cho tới khi vừa cửa sổ. Pool là ceiling của recall nên bỏ 1 candidate luôn tệ hơn cắt ngắn 1 candidate.
3. **HTTPError in ra thật to** — để lỗi hạ tầng không bao giờ giả dạng lỗi chất lượng nữa.

Sau sửa: #818 0/5 → **5/5**.

### Judge sai kiểu gì (2026-08-04)

Dump thẳng picks vs GT của các câu miss: **4/5 cùng một kiểu** — judge chọn **thuyết minh chi tiết**, GT là **báo cáo chính**.

| qid | GT | judge chọn |
|---|---|---|
| #752 | `BÁO CÁO KQKD` (pool pos 0 và 3) | note `LÃI THUẦN TỪ HOẠT ĐỘNG DỊCH VỤ` |
| #17 | `BÁO CÁO KQKD` | note `Lãi thuần từ hoạt động dịch vụ` |
| #582 | `BẢNG CÂN ĐỐI KẾ TOÁN` | note `Phải trả khác / Vay ngắn hạn` |
| #754 | note `CHO VAY KHÁCH HÀNG` \|32,\|33 | note `CHO VAY KHÁCH HÀNG (tiếp theo)` \|35–\|38 |
| #100 | note `THÔNG TIN DOANH NGHIỆP` | `VỐN CHỦ SỞ HỮU` (ngược chiều) |

Cả hai bảng đều **thật sự chứa con số**. Đây là **quy ước gán nhãn**, không phải lỗi suy luận — nên không sửa được bằng retrieval, và cũng không nên sửa bằng cách ép "chỉ chọn báo cáo chính" (#100 ngược chiều).

Đã thử prompt `PROMPT_BOTH` ("chọn CẢ HAI, báo cáo chính lên trước") trong `scripts/judge_ab.py`, 2 lần chạy:

| | picks only run 1 | run 2 |
|---|---|---|
| default | 66.7% / 66.7% | 66.7% / 66.7% |
| `both` | 71.8% / 66.7% | 69.8% / **60.0%** |

Micro +3–5pp nhưng all-hit lúc bằng lúc tụt ⇒ **trong dải noise, chưa nhận**. Cũng tìm ra bug trong `judge_ab.run`: `doc_chars or 400` biến mọi run "default" thành run cắt 400 ký tự — đã sửa.

**Kết luận về đo đạc**: với n=15 câu / 36 group, 1 group = 2.8pp, ràng buộc hiện tại **không còn là pipeline mà là eval set**. Mọi thay đổi cấp prompt từ đây trở đi cần eval set lớn hơn (~100 câu) mới phân biệt được với nhiễu.

### Policy đã thành default thật, đo qua entrypoint chính (2026-08-04)

3 policy trên (`strip`, `primary`, `judge_text`) trước đây chỉ sống trong `scripts/dump_pools.py` + `judge_ab.py`, còn evaluator chạy không có chúng. Giờ cả hai đi qua một implementation duy nhất `finance_qa/retrieval/candidates.py`, nên số của evaluator **là** số của production.

Run tham chiếu — `.venv_bge/bin/python scripts/evaluate_retrieval.py --stage judge --output artifacts/runs/retrieval_judge_default.jsonl`:

| | @5 | @10 | @15 | @30 | @50 |
|---|---|---|---|---|---|
| table tier (n=15) | 74.7/73.3 | 78.7/73.3 | 84.3/80.0 | 94.3/93.3 | 95.2/93.3 |
| report tier (n=24) | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 |

candidates med 220 / max 506, pool med 79 / max 131. Khớp số diagnostic (74.5/66.7 @5, 83.4/73.3 @10, 88.1/80.0 @15) trong dải noise 6pp ⇒ không có policy nào bị mất khi hợp nhất. Miss @15 còn #754 (L4), #363 (L6), #582 (L3) — cùng 3 câu, cùng kiểu "judge chọn note thay vì báo cáo chính" đã phân tích ở trên.

Lưu ý đọc số: judge trả tối đa 10 pick, nên @5/@10 đo *judge*, còn @30/@50 đo *retrieval tail* (`rerank_with_picks` giữ đuôi lại). Bước nhảy 84.3% → 94.3% giữa @15 và @30 chính là phần judge bỏ sót mà pool vẫn giữ.

### Nhóm A — pool nhỏ hơn, rẻ hơn, sạch hơn (2026-08-04)

Ba thay đổi + 1 negative result. **Không cái nào sửa nội dung `doc_text`**, nên index dense prebuilt (`data/indexes/tables_dense.npy`, align theo row order của `tables_doc_text.parquet` và chỉ validate bằng row count) vẫn đúng — đây là tiêu chí chọn phạm vi cho nhóm này, không phải trùng hợp.

**1. `channel_k` 50 → 20** (`candidates.CHANNEL_K`). Q7 chốt 50 mà chưa đo. Pool là *union* của hai ranking, nên độ sâu mỗi kênh mua **kích thước pool** nhanh hơn nhiều so với mua recall:

| channel_k | pool med / max | union all-hit@20 |
|---|---|---|
| 10 | 28 / 89 | — |
| 15 | 34 / 94 | 93.3% |
| **20** | **38 / 97** | **93.3%** |
| 30 | 52 / 112 | 93.3% |
| 50 | 78 / 131 | 93.3% |

Phẳng từ k=15 trở lên. Judge đọc *toàn bộ* pool ⇒ đây chính là cái knob quyết định hóa đơn judge. Chọn 20 chứ không 15 để có đệm cho corpus lớn hơn eval set.

**2. Junk filter `has_content` trong `shortlist`** — bỏ bảng `num_rows ≤ 2` hoặc `first_col_labels` rỗng. Đo trên toàn corpus: **9,419 bảng (6.4%)** bị bỏ, **0 / 39 GT table** bị bỏ. Hai lý do đặt nó ở `shortlist` chứ ở chỗ khác:
- upstream của *cả hai* kênh và của cả primary expansion. `add_primary_statements` kéo mọi `balance_sheet`/`income_statement`/`cash_flow`/`equity_change` trong shortlist vào pool vô điều kiện, nên nếu filter chỉ chạy trên ranking thì mỗi report vẫn góp header CĐKT bị OCR cắt rời vào mọi pool.
- cả hai kênh score `doc_text`, mà phần phân biệt của nó là `first_col_labels` (67% ký tự). Bảng không có nhãn dòng chỉ có thể khớp bằng boilerplate.

Filter này **hẹp có chủ ý**. `is_continuation` (46% corpus) và "không có `note_title` lẫn `section_title`" (18%) trông cũng đáng bỏ như vậy nhưng giữ **5** và **21** GT table — trang tiếp thường chính là nơi có dòng mà câu hỏi hỏi. Đừng mở rộng predicate mà không đo lại GT.

**3. `--judge-top-n` được nối dây** vào `scripts/evaluate_retrieval.py` và `pipeline/run.py`. Knob này trước đây chỉ tồn tại trên `CandidateRetriever` nên không ai gọi tới được và không có test. Default vẫn là `None` = judge đọc cả pool (policy đã đo); nó chỉ cắt *cái judge được xem*, pool giữ nguyên đuôi để `rerank_with_picks` và các K sâu vẫn đo được ranking đầy đủ.

Run so sánh — `--stage judge --output artifacts/runs/retrieval_judge_groupa.jsonl`:

| table tier (n=15) | @5 | @10 | @15 | @30 | @50 | pool med/max | thời gian |
|---|---|---|---|---|---|---|---|
| baseline (k=50, không junk filter) | 74.7/73.3 | 78.7/73.3 | 84.3/80.0 | 94.3/93.3 | 95.2/93.3 | 79 / 131 | 539.2 s |
| **Nhóm A** (k=20 + junk filter) | 73.2/66.7 | 79.9/73.3 | **93.9/86.7** | 95.2/93.3 | 95.2/93.3 | **38 / 95** | **469.2 s** |

Report tier vẫn 100/100 ở mọi K. `candidates` med 220 → 205, max 506 → 463.

Đọc đúng bảng này: mục tiêu của Nhóm A là **rẻ hơn ở cùng chất lượng**, và nó đạt — pool giảm nửa, judge nhanh hơn 13%. Phần chênh chất lượng thì @5 all-hit −6.7pp và @15 all-hit +6.7pp **đều bằng đúng 1 câu trên 15**, tức nằm trong dải noise 6pp; chỉ recall@15 +9.6pp là ra ngoài dải, và nó đến từ 2 câu (#754, #582) hết miss. Không tuyên bố Nhóm A cải thiện chất lượng — tuyên bố nó không làm tụt. Miss @15 còn **#363** (29%) và **#524** (80%), cả hai L6.

**4. Reranker: negative result — đừng thử lại.** A/B ở stage judge, cùng seed, cùng pool:

| reranker | table all-hit@15 | recall@15 | thời gian |
|---|---|---|---|
| `None` (default) | **80.0%** | 0.843 | 539.2 s |
| qwen3-0.6b (DeepInfra) | 73.3% | 0.853 | 653.8 s |

All-hit tụt 6.7pp (1 câu) và tốn thêm 114 s cùng tiền API, đổi lấy recall +1pp. Cơ chế: cross-encoder xếp lại pool, nhưng judge **đọc cả pool** nên thứ tự không đổi được cái judge thấy — reranker chỉ có thể có ích nếu ta cắt pool sau nó, và `--judge-top-n` giờ đã có để thử ý đó *nếu* có eval set lớn hơn. Backend (`retrieval/clients.py::RERANKER_BACKENDS`, `--reranker`) vẫn giữ lại vì nó là interface đã test, không phải vì nó đang giúp.

---

## Sematics quan trọng (dễ hiểu nhầm)

### `is_continuation` KHÔNG phải "trang tiếp của bảng bị cắt"

TT200 convention: khi 1 note có nhiều pivot data khác nhau, các bảng phụ có `note_title` gốc + "(tiếp theo)". Đây là **các bảng độc lập** về data, chia sẻ chung note_title, KHÔNG phải fragment của 1 bảng gốc.

**Ví dụ note "TIỀN GỬI TẠI VÀ CHO VAY CÁC TCTD KHÁC"** — 5 bảng cùng note:

| table_pos | is_continuation | Pivot data |
|---|---|---|
| 23 | false | Theo kỳ hạn (không kỳ hạn / có kỳ hạn) |
| 24 | false | Theo loại tiền (VND / ngoại tệ) |
| 25 | true | Theo loại tiền + chi tiết chiết khấu |
| 26 | true | Theo loại tiền dạng khác |
| 27 | true | Theo chất lượng (Nợ đủ tiêu chuẩn...) |

**Hệ quả cho retrieval**:
- Câu hỏi "tiền gửi VND tại TCTD khác" chỉ match pos=24 (hoặc 26).
- Câu hỏi "phân theo chất lượng" chỉ match pos=27.
- **KHÔNG group/expand** 5 bảng thành 1 unit — mỗi bảng là 1 sample độc lập ở retrieval và submission.
- `first_col_labels` là signal discriminative giữa các pivot; BM25/dense/LLM judge phân biệt được.

### `note_pivot_dim` — defer

Vấn đề Nhóm B trong `metadata_audit.md`. Categorical hoá pivot ({sector, quality, customer_type, maturity, currency, other}) sẽ giúp filter chặt hơn. Nhưng `first_col_labels` đã đủ discriminative cho V0 — LLM judge nhìn labels tự phân biệt. Chỉ derive nếu recall@K trên L4-L5 fail.

---

## Value data flow — tại sao doc_text không cần cell values

Retrieval và value-lookup là 2 luồng độc lập:

| Cần gì | Nguồn |
|---|---|
| Retrieval trả `report_id\|table_pos` | doc_text (label/header level, không cần values) |
| LLM tính answer cho BS/IS/CF | `long_format.parquet` (đã extract sẵn, query pandas theo `ticker/year/ma_so`) |
| LLM tính answer cho note | Đọc raw CSV theo `csv_path` (retrieval trỏ đúng table_pos là đủ) |

⇒ Retrieval chỉ cần **route** đến table đúng. Cell values không thuộc trách nhiệm của retrieval index.

---

## Open (Q8+): eval methodology

Chưa chốt:
1. Metric — recall@K only, hay thêm MRR/nDCG?
2. Per-level breakdown format (L1-L6) — table markdown vs plot?
3. Threshold acceptance — recall@10 ≥ 80% để pass V0? Hay khác?
4. Sweep params — có sweep RRF-k, top-N rerank không? Overfit risk với 24 sample.

## Deferred (V1+)

- LLM coder (viết `pandas_query`) — sau khi retrieval baseline ok
- LLM executor + answer synthesis
- `note_pivot_dim` LLM-derive (Nhóm B)
- `equity_change` cho DN/bank (Nhóm B)
- `language` VN/EN field (Nhóm C)
- `is_semi_annual` / `period_quarter` (Nhóm C)

## Trạng thái readiness (2026-08-03)

Audit trước khi build. 5 blocker; B5 do user chốt, B1+B2 đã fix và verify.

| # | Blocker | Trạng thái |
|---|---|---|
| B1 | `find_years` không expand range → sai semantics câu argmax-over-range | ✅ fixed, ceiling 94.4% → 100% |
| B2 | `doc_type` câu hỏi trả nhãn *ngành*, không khớp vocab corpus | ✅ fixed, ceiling 47.2% → 100% |
| B3 | Eval set chưa đủ (15/24 có `report_id\|table_pos` explicit, 9/24 prose-only) | ✅ `scripts/build_evalset.py` → `data/eval/evalset.json`; 2 tier, mọi GT id validate được trong corpus |
| B4 | Môi trường: torch của base conda env không chạy được GPU, VRAM free chỉ 3.0/81.6 GB | ✅ fixed, xem "Môi trường chạy" bên dưới |
| B5 | `table_pos` numbering vs key của BTC | ✅ user chốt: giữ ordinal theo thứ tự xuất hiện (`submission_rule.txt` — `evidence.csv_path` trỏ vào `data/` của chính gói nộp) |

### Môi trường chạy (B4, verify 2026-08-03)

Interpreter: **`.venv_bge/bin/python`**, torch 2.7.1+cu126. Không dùng base conda env: nó có torch 2.11.0+cu130 nhưng driver là 565.57.01 (tối đa CUDA 12.7) → `RuntimeError: NVIDIA driver too old (found version 12070)`, tức base env **không dùng được GPU chút nào**, nặng hơn vấn đề VRAM đã ghi trước đó.

GPU chia sẻ với 4 service không liên quan (vLLM 58.3 GB, tritonserver 7.8 GB, CosyVoice 8.5 GB, 2 TTS server 3.4 GB) → free **3,057 MiB**. Không restart/không sửa service nào.

Đo thật, cả 2 model đều vừa 3 GB đó (chạy tuần tự, vector corpus precompute nên không cần load cùng lúc):

| Model | weights fp16 | peak VRAM | throughput |
|---|---|---|---|
| `BAAI/bge-m3` (dense, XLM-R large + CLS pooling + L2 norm) | 1.14 GB | 1.19 GB | 1,911 doc/s → 146,246 bảng ≈ 1.3 phút |
| `BAAI/bge-reranker-v2-m3` (cross-encoder, 1 logit/cặp) | 1.06 GB | 1.38 GB | 42 ms/câu (30 cặp) → 1,012 câu ≈ 0.7 phút |

Hai lược giản có chủ ý:

- **Không cài `FlagEmbedding` / `sentence-transformers`.** bge-m3 dense chỉ là XLM-R + CLS pooling + L2 normalize, viết bằng `transformers` thuần là đủ; cài thêm có khả năng downgrade transformers/torch.
- **Không cần `faiss`.** Hard filter đã đưa candidate về median 226/câu, nên dense retrieval là cosine brute-force trên ~226 vector đã precompute — index ANN không giải quyết vấn đề gì. Câu xấu nhất (#464, 18,554 candidate) vẫn chỉ là một matmul 18k×1024.

Sanity check ranking đều đúng (bge-m3: doc_text khớp 0.5908 vs distractor 0.4038/0.3562; reranker: bảng GT của #1 xếp đầu). Lưu ý margin của reranker mỏng — GT −2.494 so với distractor gần nhất −2.604 trong cùng report; cần LLM judge ở sau, đúng như design.

### Report bị ship 2 lần (`_1` / `_2`) — phát hiện khi build eval set

18 base report có suffix `_1`/`_2`. Hash toàn bộ CSV cho thấy **2 loại khác nhau**, không được đối xử giống nhau:

- **OCR twin** (8 base): cùng số bảng, chỉ lệch 1-2 bảng do noise OCR — NAB 2022/2023 consolidated, OCB 2022 consolidated + separate, HDB 2022 separate, MBB 2022 separate, NVB 2020 consolidated, VPB 2022 separate. Ví dụ NAB 2023: 111 bảng, khác nhau ở bảng 40 và 110. ⇒ `_1` và `_2` **thay thế được cho nhau**; eval tính hit nếu retrieve bất kỳ cái nào (`DUP_BASES` trong `build_evalset.py`).
- **partial + full** (4 base): số bảng lệch hẳn — HDB 2023 consolidated (51 vs 105), HDB 2023 separate (48 vs 106), MPC 2019 separate (44 vs 18), POW 2025 consolidated (57 vs 10). ⇒ **KHÔNG** thay thế được, phải retrieve đúng file.
- `PRT_2025_financial_statement_explanations_2` tồn tại mà không có `_1`.

Hệ quả submission: `relevant_docs` của các câu trúng OCR twin có rủi ro chấm sai nếu BTC chỉ nhận đúng 1 id. Chưa xử lý ở V0 (chỉ 8 base), ghi lại để nếu leaderboard lệch so với eval nội bộ thì nghi ngờ chỗ này trước.

Non-blocker đã ghi nhận: `context_page_text` off-by-one (`cur_offsets[tpos]` phải là `cur_offsets[tpos-1]`, field này không dùng trong doc_text); dup doc_text 6.69%; header 2 dòng bị truncate; `statement_type` misclassify; report split `_1`/`_2` (NAB 2022/23, OCB 2022 — **không** bao giờ dựng `report_id` bằng f-string); `enrich_v2_stats.md` stale (luôn đo lại từ jsonl).
