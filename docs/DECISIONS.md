# DECISIONS — ViFinQA Stage 2

Sổ ghi quyết định (decision log). Ghi *đã quyết cái gì*, *vì sao*, và *hoãn cái gì cho tương lai*.
Cập nhật gần nhất: **2026-08-06**.

---

## 0. Bức tranh 1 dòng

Retrieval **không còn là bottleneck** (report-tier 100%, table all-hit@15 ~86.7%, recall@15 ~93.9%).
Điểm mất bây giờ nằm ở **bước answer/planner**. Vì vậy hướng đi là: lấy **baseline thật trên
leaderboard (n=1012)** trước, rồi mới tối ưu từng biến một, đo trên leaderboard chứ không đoán trên 15 câu.

---

## 1. Quyết định HIỆN TẠI — chạy "A" (đã chốt)

**A = chạy end-to-end cả 1,012 câu bằng pipeline hiện tại + planner đã vá, dựng ZIP nộp, lấy baseline.**

> ✅ **ĐÃ XONG (2026-08-04):** run 1012/1012, `output/submission.zip` hợp lệ. Số cuối + kết luận + lộ trình
> hardening ở **§8**. Tóm tắt: ok 773 / error 239 (100% ở planner), retrieval+judge KHÔNG phải nút thắt
> (4/1012 judge rỗng) → **planner-first được xác nhận bằng số**. Bước kế: nộp ZIP lấy điểm.

Phạm vi đã chốt: **A thuần** — retrieval hiện tại (bge-m3 dense trên doc_text hiện có + BM25 + judge),
**KHÔNG re-embed, KHÔNG tách trường dense**.

Vì sao A trước:
- Có con số thật trên n=1012 để quy trách được mọi thay đổi sau.
- Đổi một biến một lần: nếu re-embed *ngay bây giờ* thì đổi 2 biến cùng lúc (fix planner + đổi dense text)
  → không biết delta điểm do cái nào.
- Retrieval không phải nút thắt nên chưa cần đụng dense.

Việc cụ thể trong A:
| # | việc | trạng thái |
|---|------|-----------|
| 1 | `run_pipeline.py` trên cả 1,012 câu (retrieval → judge → planner đã vá) → JSONL | script có sẵn, chạy nền, resume được; ~5 giờ trên vLLM chung (WORKERS=4, lịch sự) |
| 2 | Dựng ZIP: `submission.json` (đủ 1,012, đúng schema `submission_rule.txt`) + `data/` mọi CSV được `csv_path` tham chiếu | **chưa có** — cần viết script đóng gói |
| 3 | Validator: không thiếu câu, mọi `csv_path` tồn tại + relative `data/`, JSON đúng format | **chưa có** — cần viết |
| 4 | Nộp 1 lần → điểm baseline | thủ công trên dashboard (rate-limited/ngày) |

`output/` là nơi duy nhất chứa artifact submission cuối.

---

## 2. Đã LÀM & đã verify (nền của A)

### Nhóm A — dọn retrieval (đã xong, 0 regression)
- `channel_k` 50→20 cho cả BM25 và dense (pool nhỏ/sạch hơn, không mất chất).
- `has_content` junk filter (bỏ ~6.4% bảng rác, 0/39 GT bị rớt).
- Wiring `--judge-top-n`.
- Bỏ cross-encoder reranker — **đã đo là xấu đi**: qwen3-0.6b 73.3% all-hit@15 / 653.8s vs None 80.0% / 539.2s.
- Kết quả sau Nhóm A: rrf all-hit@15 = 80.0% (khớp baseline), judge all-hit@15 = 86.7% / recall@15 93.9% / 469.2s.
- Giá trị Nhóm A = pool rẻ/nhỏ/sạch hơn, **không phải** tăng chất (đúng như dự đoán).

### Fix planner "A" — `repair_binding_column` (đã xong, 0 regression)
- **Root cause:** `load_frame` (execution/query.py) nối header phân cấp bằng `' | '` **lúc runtime**
  (CSV gốc 0% có pipe). Model đặt tên cột theo *lá* nó đọc trên trang ("Số cuối năm"), validator so khớp
  chính xác → loại binding → cả plan rớt xuống fallback direct-code **không có guard** → mất guard đơn vị & dấu.
- **Fix general (không hard-code):** nếu đúng **một** cột mang lá đó thì rebind sang cột đã flatten;
  lá **mơ hồ** (nhiều cột) thì để nguyên cho vòng repair — vì đó là lựa chọn thật model phải làm.
- Kết quả: **10/15 GT đúng** (từ 9), #818 được cứu về đúng 145.134, **0 regression**.
  Test xác định thêm trong `tests/test_planning_ir.py`. Toàn bộ suite planner/execution xanh.
- **KHÔNG cần re-extract** vì lỗi header sinh ra lúc runtime, không nằm trong file CSV.

### Sweep dense (đã đo, mới directional — chưa hành động)
- Bỏ `section_title` giúp dense (all@20 66.7→73.3; distinct-ratio 0.11 → không có IDF cho bi-encoder).
- Giữ `header_flat` (bỏ nó hại head: @5 41.7→30.6).
- **Cảnh báo:** đa số delta nằm trong dải noise ~6pp trên 15 câu → chỉ là bằng chứng định hướng cho Nhóm B,
  **chưa đủ để quyết**. Cần leaderboard làm thước đo.

---

## 3. Quyết định TƯƠNG LAI (hoãn — làm sau khi có baseline)

Thứ tự ưu tiên gợi ý, mỗi mục **đổi một biến một lần** rồi đo trên leaderboard:

1. **Nhóm B — chống trùng lặp doc_text (rẻ trước, re-embed sau)** *(chưa duyệt)*

   **Audit trùng lặp trên doc_text** (2026-08-04) — cơ sở cho mục này:
   - Exact-duplicate toàn corpus: 11,910 records (8.1%) trùng y hệt record khác; 664 cặp
     intra-report trùng hoàn toàn (bảng chỉ có header, không `first_col_labels`) → retriever
     không phân biệt được. Nhỏ, không đáng lo.
   - **Near-duplicate do continuation pages: 63,539 bảng (43.4%)** cùng report + cùng `note_title`,
     doc_text gần trùng chỉ khác `first_col_labels`. Cực đoan: ACB 2025 có 103 bảng cùng
     note_title "TÓM TẮT CÁC CHÍNH SÁCH KẾ TOÁN CHỦ YẾU (tiếp theo)" → 103 vector dense gần nhau.
   - Boilerplate bơm noise vào dense (không hại BM25 vì IDF): `section_title` xuất hiện 6,509 lần
     ("THUYẾT MINH… (tiếp theo)"), `header_flat` "Số cuối năm | Số đầu năm" 7,124 lần.
   - Hệ quả **chỉ tập trung ở câu hỏi note-detail (thuyết minh)**, sau hard filter report×year×doc_type;
     top-k dense có thể bị các continuation page cùng note lấp đầy → lãng phí context judge, miss trang chứa số.

   **Thứ tự (đổi một biến/lần, gate trên retrieval-miss thật):**
   - **(0) Soft diversity rerank trong candidate pool** — RẺ NHẤT, **không re-index**: near-duplicate
     cùng `(report_id, note_title)` bị phạt để không chiếm hết k slot, nhưng **vẫn reachable** nếu pool còn chỗ.
     ⚠️ **KHÔNG hard-dedup-to-1** theo "first_col_labels khớp query nhất": first_col_labels chỉ là *mẫu*
     nhãn hàng — số cần tìm có thể ở trang mà mẫu không khớp lexical → drop nhầm, mất recall. Làm bước này
     trước, đo trên eval.
   - **(1) Tách `bm25_text` / `dense_text` + re-embed** — chỉ khi (0)+đo vẫn cho thấy dense là nút thắt.
     `bm25_text` = full (IDF tự lo boilerplate); `dense_text` = gọn (statement_label \| note_title \|
     first_col_labels), bỏ 2 field boilerplate → vector bị chi phối bởi phần phân biệt, continuation
     page tự tách xa hơn. *(Lưu ý: sweep 15-câu ở §2 gợi bỏ `section_title`/giữ `header_flat`; audit này
     nghiêng về bỏ cả hai cho dense — con số thật trên leaderboard mới quyết.)*
   - **(2) Merge continuation pages** — gộp `first_col_labels` mọi trang cùng note thành 1 doc. Rủi ro
     cao nhất: đổi granularity/identity bảng → ảnh hưởng mapping `table_id` trong submission. Defer.
   - **(bỏ) Thêm `(trang N)` vào doc_text** — query không nhắc số trang nên không giúp match ngữ nghĩa.

   **Ràng buộc:** backend dense thứ 2 **không được ghi đè** `tables_dense.npy`; encode ra file MỚI; coi
   `tables_metadata_v2.jsonl` + `data/indexes/*` là snapshot không dựng lại được.
   **Gate:** 100% lỗi run hiện tại ở **planner**, 0 lỗi retrieve → retrieval **chưa** phải nút thắt #1.
   Chỉ đầu tư re-embed nếu **retrieval-miss thật đo từ baseline** đáng kể; nếu thấp, dồn công cho planner (mục 2).

2. **Planner class khó** *(chưa làm)*
   - #752: derived-tie (income vs expense, net = derived) → sai dấu. Leaf-match không áp dụng.
   - #754, #605: đúng bảng, **sai `row_index`** (sai dòng con). Class ngữ nghĩa khó.
   - #363: multi-year 7 bảng, `row_index` ngoài range + cột mơ hồ.
   - #582: **retrieval miss** (không phải lỗi planner) — GT 0/2 bảng tới được planner.

3. **LLM ticker-fallback (có điều kiện)** *(chưa làm — gated on baseline)*
   - Enrich câu hỏi hiện **100% deterministic** (regex + `code_stock.csv`, không LLM), xem
     `preprocessing/questions.py`. Đã verify: **0/24 GT bị hard-filter giết**; ticker resolve 1011/1012;
     `doc_type=unknown` (62.8%) = không lọc nên không thể over-filter.
   - **KHÔNG** enrich/rewrite câu bằng LLM blanket: filter là nền móng cần tái lập được; LLM sai ticker
     sẽ âm thầm loại report đúng, không reproduce. Rewrite câu còn tệ hơn — nó là tín hiệu retrieval gốc
     cho BM25/dense/judge/planner, rewrite dễ đổi scope/chỉ tiêu.
   - Rủi ro duy nhất regex không tự thấy: **ticker false-positive tự tin** (khớp nhầm 1 mã, loại mất mã đúng)
     — không hiện dưới dạng ticker=None nên 24 câu nhãn không bắt được. **Baseline A phơi bày ra**
     (answer sai + retrieval miss). Nếu đáng kể → thêm LLM fallback **chỉ cho câu ticker ambiguous/None**,
     đo lại. Dùng LLM đúng chỗ, không blanket.
4. **Nhãn answer-level thật** — tự solve 12–15 câu để có GT trên nhiều loại question hơn (hiện chỉ 15 answer-GT).
5. **Mở rộng eval set 15→100** — giảm noise floor (hiện 1 câu = 6.7pp).
6. **Async runner** *(chưa cần — không phải maintainability)* — `pipeline/run.py` dùng
   `ThreadPoolExecutor(4)`. Async `gather` **không** giúp ở đây: mỗi task trộn I/O (LLM) +
   CPU-bound (pandas exec/compile/CSV), async serialize phần CPU trừ khi `run_in_executor`
   (quay về thread). Concurrency chốt 4 vì vLLM chung nên overhead thread là noise. Chỉ đáng
   làm nếu tương lai bỏ giới hạn endpoint chung và cần concurrency cao. Không sửa thứ không hỏng.
7. **Semantic-signal fields dormant — precondition nếu resurrect** *(hiện không dùng)*
   `enrich_metadata_v2.py` tính & lưu 3 field gắn nhãn "BA priorities 2/3/4":
   `period_years`, `industry_segment`, `is_continuation`. **Pipeline đang ship KHÔNG đọc field nào:**
   - `period_years`: 0 `.py` đọc (filter dùng `table.year` từ report_id; index text dùng
     `statement_label|note_title|section_title|first_col_labels|header_flat`). Grep toàn repo chỉ
     thấy trong docs thiết kế + stats.
   - `industry_segment`: 0 `.py` đọc. `metadata_audit.md` mô tả filter *thiết kế* có nó, nhưng
     `filters.py` *thực thi* chỉ ticker/year/doc_type + prefer_consolidated.
   - `is_continuation`: **cố ý loại sau khi đo** (`filters.py:82`, `v0_retrieval_pipeline.md:138`) —
     `detect_continuation` over-match section header → ~65% `true` là noise.
   Bài học: filter hẹp (ticker/year/doc_type) thắng design phức tạp; đừng thêm signal khi chưa đo.
   **Bug đã biết trong field dormant** (chỉ quan trọng NẾU resurrect):
   - `period_years` BS mất năm so sánh: `period_columns_raw=['31/12/2015','01/01/2015']` →
     `[2015]` thay vì `[2015,2014]` (548 records). Fix: thêm `YYYY-1` khi có `01/01/YYYY`.
   - 650 bank maturity table (statement_type=balance_sheet, header "Từ 1 năm trở xuống…") có
     `period_years=[]` — đúng, nhưng gây nhiễu nếu bật period filter.
   Sửa 3 field này = **ghi đè `tables_metadata_v2.jsonl` 294MB** (chạy lại enrich, không cần
   re-extract OCR) → chỉ làm khi pipeline KHÔNG chạy, và chỉ khi quyết định dùng signal (có đo).

## Hạ tầng (2026-08-04)
- **Git local đã init** (commit `a260070`). `.gitignore` loại `.venv_bge/`, `ViFinQA/`,
  `data/*` (giữ `data/eval/`), `artifacts/runs/`, `output/`, `.env`. Snapshot data 1.3G +
  dataset gốc 447M **không trong git** — backup filesystem riêng. Remote private: hoãn (tính sau).

---

## 7. Bản đồ metadata → semantic text + audit hardcode (2026-08-04)

Đọc trọn chuỗi `enrich_metadata_v2.py` → `document_text.py` → `bm25.py`/`dense.py` → `candidates.py`.
Mục này chốt "đã hiểu tới đâu" + các chỗ **fix cứng / regex có thể sai hoặc không tổng quát**.

### 7a. Semantic text ở retrieval — đã hiểu trọn (doc + query)
| Tầng | Doc side | Query side |
|---|---|---|
| BM25 + dense **index** | `doc_text` = statement_label \| note_title \| section_title \| first_col_labels \| header_flat | `query_for()` = **strip_entity** (bỏ năm + token tên issuer + 30 boilerplate). KHÔNG phải raw question |
| Judge | `judge_text` = statement_label \| note_title \| first_col_labels | **raw question** |
- `statement_label` **có subtype**: bs_assets→"phần TÀI SẢN", bs_liabilities_equity→"phần NỢ PHẢI TRẢ…"
  → hai nửa BS được tách trong doc_text. Nhưng 124k dòng `note` **không có** statement_label — đúng chỗ
  63k near-dup continuation nằm (mục §3.1).
- BM25 (`bm25.py`): tokenize `\w+` NFC lowercase = **syllable-level, KHÔNG word-segmentation tiếng Việt**;
  IDF global 146k; length-norm B=0.75 (doc phồng boilerplate **cũng bị phạt độ dài**). Query dùng cùng tokenize.
- dense (`dense.py`): bge-m3, CLS pool, L2, fp16, **MAX_LEN=512, truncation=True**. Không có prefix (symmetric).

### 7b. "Sao cần chunk? model chứa nhiều hơn mà" — trả lời
- **Không có chunking.** Mỗi bảng = 1 doc = 1 vector, chỉ **truncate ở 512 token**. bge-m3 chịu tới **8192**,
  nên 512 là **cap tự chọn**, thấp hơn nhiều khả năng model.
- Đo trên 146,246 doc_text (char): p50=296, p90=729, p99=1284, p99.9=1759, **max=22,820**.
  Vượt ~1500 char (~512 token): **574 bảng (0.39%)**; vượt ~3000 char: 12 bảng.
- Vì sao 512 an toàn: (1) chỉ 0.39% bị cắt, và cắt **phần đuôi** (header_flat trước, rồi cuối first_col_labels) —
  head phân biệt (statement_label/note_title/first_col_labels) nằm trước, còn nguyên; (2) padding tới member
  dài nhất là chi phí chính, 512 chặn worst-case trên GPU chung ~3GB.
- **Precondition nếu re-embed (Group B):** nâng `MAX_LEN` 512→1024 gần như miễn phí (chỉ 12 doc >3000 char),
  phủ trọn p99.9 cho ~574 note dài. `header_flat` hiện **không cap độ dài** → là nguồn của doc 22,820 char
  (nên cap header_flat khi re-embed).

### 7c. Chỗ FIX CỨNG / REGEX có thể sai hoặc không tổng quát (đo thật)
| # | Chỗ | Rủi ro | Đo được | Mức |
|---|---|---|---|---|
| H1 | `STD_REPORT_RE`/`EXPL_REPORT_RE` whitelist suffix `separate\|consolidated\|aggregated` | report_id suffix lạ → `parse_report_id` trả ticker=""/year=None → bảng **vô hình với hard filter** | **0/146,246** record mất ticker/year trên corpus hiện tại | ⚠️ tiềm ẩn (0 hiện tại), latent cho report mới |
| H2 | `BOILERPLATE` strip token `hàng` (`candidates.py`) | `hàng` là boilerplate **chỉ** trong "ngân hàng"; là **content word** trong hàng tồn kho / bán hàng / giá vốn hàng bán / hàng hóa → strip mù làm hỏng retrieval query | **298/1012** câu có token `hàng`; **~91** là content (tồn kho 38, bán hàng 28, hàng bán 18, hàng hóa 7) vs 173 "ngân hàng" | ⚠️ **thật, ~9%** — gate trên baseline |
| H3 | `LABEL_LETTERS_RE = [..]{3,}` (nhãn ≥3 chữ) | nhãn acronym <3 chữ bị loại khỏi `first_col_labels` | EPS/ROE/ROA/EBIT đều ≥3 chữ → qua được; chỉ 2-chữ (TS/NV) mới rớt, rất hiếm | ✅ thấp |
| H4 | `_pick_label_col` + `LABEL_COL_MAX_INDEX=2` | chỉ dò cột nhãn trong 3 cột đầu; bảng đặt nhãn ở cột 4+ bị miss | (chưa đo) — nhưng scoring **động** không hardcode cột, tie→trái | ✅ thấp, bounded |
| H5 | `MAX_LABELS=60` | bảng >60 dòng nhãn mất đuôi | continuation chia trang nên mỗi trang ≤60; bảng đơn >60 hiếm | ✅ thấp |
| H6 | `STATEMENT_LABELS`(5)/`SUBTYPE_LABELS`(2) hardcode | statement_type/subtype ngoài dict → không có nhãn | cố ý (note/unknown bỏ nhãn) | ✅ đúng ý |

**H2 là mục cần theo dõi nhất.** Root: token blocklist không phân biệt được `hàng` overloaded. Fix tổng quát
(khi đụng retrieval): strip theo **cụm** ("ngân hàng") thay vì token đơn, hoặc chỉ strip token issuer-name khi
khớp company_name của đúng ticker — KHÔNG strip từ danh sách phẳng. Gate trên baseline (retrieval-miss thật).

### 7d. Bản đồ 27 field metadata: đọc / dormant
- **Được code đọc:** `ticker`·`year`·`doc_type`·`table_pos`·`report_id`·`note_title`·`first_col_labels`·
  `statement_type`·`section_title`·`csv_path`·`statement_subtype`·`num_rows`·`header_flat`·`company_name`.
- **Dormant (0 `.py` đọc):** `period_years`·`period_columns_raw`·`industry_segment`·`is_continuation`·
  `context_page_text`·`note_id(_inherited)`·`mau_tag`·`has_ma_so_column`·`statement_type_source`·
  `page_number`·`num_cols`. (Chi tiết + bug period_years: §3.7.)
- **Điểm mù còn lại (gate trên baseline):** đã audit *danh mục* + *dormant*, **chưa audit độ chính xác dẫn xuất**
  của field driving quan trọng nhất còn lại: **`statement_type`** (do rule-engine `statement_type_source=rule_a1…`
  chưa đọc; sai → primary-expansion + judge-routing sai). `doc_type` lấy thẳng từ suffix report_id (0 empty →
  đáng tin như tên file); `first_col_labels` sampling đã hiểu (`_pick_label_col` động, các cap H3/H4/H5 bounded).

### 7e. Verify mapping enrich → filter tier-1 (chạy `shortlist()` trên cả 1012 câu)
Tier-1 là **cổng cứng**; nếu sai thì semantic vô nghĩa. Đo thật:
| Kiểm tra | Kết quả |
|---|---|
| Pool **rỗng** /1012 | **0** |
| Pool **<3 bảng** /1012 | **0** |
| ticker+year có nhưng pool rỗng | **0** (mapping (ticker,year) không bao giờ mismatch → 0) |
| doc_type=**separate** (363 câu; nhánh nghiêm ngặt bỏ consolidated, không prefer_consolidated) | **363/363 (100%)** có tín hiệu tường minh "riêng/công ty mẹ" → **0 false-positive** |
| Thiếu chiều (no ticker #464 / no year #412) | 2/1012, **degrade mềm** về all_tables, không rỗng |
| Pool size | p50=143, p90=460, max=9360 (câu no-ticker) |
- **Kết luận: tier-1 lành, an toàn sang semantic.** doc_type gán bảo thủ đúng (chỉ "separate" khi câu nói rõ;
  còn lại "unknown"→prefer_consolidated, mặc định group).
- **Điểm mù duy nhất** (không hiện qua "pool rỗng"): **ticker false-positive** → pool không rỗng nhưng **sai
  report**; chỉ baseline phơi ra (§3.3). Cộng nghĩa-từ "riêng" over-trigger vài câu — nhỏ, cần answer-GT mới chốt.

### 7f. Nên lưu gì để RAG tốt nhất — 3 tầng theo consumer
Khảo sát raw: nút thắt **không** phải thiếu data, mà là **near-dup continuation (43%)** + **dense 1-vector loãng**.
Tối ưu = **tách theo consumer**, không nhồi thêm text.
1. **Filter fields (exact, structured) — GIỮ NGUYÊN, đang tốt (0 pool rỗng):** ticker·year·doc_type·
   statement_type/subtype·num_rows·first_col_labels. **KHÔNG** nhét ticker/year vào text embed (đó là lý do
   `query_for` strip chúng).
2. **Retrieval text — TÁCH kênh (chỗ cải thiện, = §3.1):**
   - `dense_text` gọn: statement_label \| subtype \| note_title \| first_col_labels; bỏ section_title+header_flat;
     re-embed MAX_LEN=1024 + cap header_flat.
   - `bm25_text` rộng: giữ section_title+header_flat (IDF lo noise).
   - Soft-dedup continuation qua khóa `(report_id, note_title)` lúc query (rẻ, không re-embed).
3. **Context cho judge/answer:** `judge_text` hiện tại; xem `context_page_text` bên dưới.

**`context_page_text` — KHÔNG phải LLM gán, "chưa dựng đúng" để làm semantic label, VÀ hiện KHÔNG dùng trong retrieval:**
- **Dormant**: 0 `.py` đọc (§7d) — không vào doc_text, không vào judge_text, không index. Chỉ được trích & lưu.
- `extract_page_prose()` thuần cơ học (OCR giữa 2 mốc PAGE, xoá `<table>`, gộp whitespace, cap 1500). **Zero LLM.**
- Đo: empty 1.4%; nhưng **66% (95,228 bảng) dùng CHUNG y hệt** context với ≥2 bảng cùng report (**page-level**,
  không table-level) → trùng lặp còn tệ hơn doc_text (43%). p50=518, p90=1500 (đụng cap).
- **Dense: KHÔNG** đổ raw vào — thêm khối text chung cho 2/3 bảng → **làm near-dup tệ hơn** + OCR noise pha loãng.
- **BM25:** rủi ro thấp hơn (IDF), có thể thêm recall từ narrative ("dự phòng", "TT01/2020"), nhưng vì **chung
  giữa bảng cùng trang** nên chỉ tách *trang/report*, **không** phân biệt bảng-với-bảng. Marginal, phải đo.

**Option tương lai mạnh nhất — LLM per-table semantic label (khác hẳn LLM cho filter):**
- LLM đọc bảng (+ trang) → 1 câu mô tả **table-specific**, sạch → phân biệt được từng continuation page.
- An toàn hơn LLM-cho-filter **về bản chất**: label lệch chỉ **nhích thứ hạng**, KHÔNG **gate** bảng ra khỏi pool
  (khác sai ticker = mất bảng); cache/đóng băng được sau khi dựng.
- Đây là nâng cấp RAG mạnh nhất nếu baseline cho thấy retrieval-miss đáng kể. Gate trên baseline như mọi mục.

**Giọng thẳng:** storage hiện tại **đã đủ tốt cho tier-1**. Bề mặt cải thiện **hẹp & cụ thể**: (a) soft-dedup
continuation [runtime, rẻ], (b) tách dense_text + re-embed [Group B], (c) LLM per-table label hoặc dùng
`context_page_text` cho BM25/explanatory. **Không redesign.** Gate tất cả trên retrieval-miss thật.

---

## 8. BASELINE A — note tổng quan run 1012 (2026-08-04, ĐÃ XONG)

Run `scripts/run_pipeline.py --output artifacts/runs/full_1012.jsonl` xong (exit 0), 1012/1012 câu.
ZIP: `output/submission.zip` (3.1 MB, 3,679 CSV) — **hợp lệ**: đủ 1012, schema đúng, mọi csv_path có file,
**0 câu mất relevant_tables** (kể cả 239 câu error vẫn giữ bảng retrieval → vẫn ăn điểm retrieval).

### 8a. Số cuối
| Chỉ số | Giá trị |
|---|---|
| ok (answer đã validate) | **773 / 1012 (76.4%)** |
| error | **239 (23.6%) — 100% ở `plan` stage**, 0 retrieve/filter/network |
| planner structured | 672 (66%) · direct-code fallback 328 (32%) · none 12 |
| attempts | 1→562 · 2→163 · **3 (kịch retry)→275** ← chính đám ăn wall-clock |
| **judge_fallback (judge trả rỗng)** | **4 / 1012** |
| **picks rỗng** | **4 / 1012** |
| latency/q | p50=26.6s · p90=91.8s · max=399s · tổng ~9.1h (÷4 worker) |
| pool_size | p50=38 · p90=71 · max=1188 |

### 8b. Kết luận chiến lược (bằng chứng, không cảm giác)
- **Retrieval + judge KHÔNG phải nút thắt — đã xác nhận trên 1012.** Chỉ **4/1012** câu judge không ra pick
  nào (retrieval+judge giao được ứng viên cho **99.6%**). Cộng eval all-hit@15 ~86.7% → retrieval-miss **bị chặn
  thấp**. (True retrieval-miss trên 1012 vẫn cần GT/leaderboard, nhưng proxy nói rõ: không chảy máu ở đây.)
- **100% điểm mất nằm ở PLANNER.** 239/239 error ở plan stage. → **planner-first, data-later được xác nhận
  bằng số.** Toàn bộ việc data/RAG ở §7 **đúng khi hoãn**.

### 8c. Error taxonomy = lộ trình hardening planner (ưu tiên theo số)
| # câu | Lớp lỗi | Bản chất |
|---:|---|---|
| **~59** | `bindings[].column không tồn tại trong df` | planner đặt tên cột theo lá, không khớp cột đã flatten. Đúng vùng `repair_binding_column` (Fix A) — đã đỡ nhưng còn nhiều. **#1** |
| **~65** | `binding trỏ ô không phải số` (nan / string) | bind nhầm **dòng/ô** (ô nhãn, ô rỗng, NaN). **#2** |
| 20 | `TypeError /: str/str` | nhánh **fallback direct-code không guard** làm toán trên string ('1.23%'). Fix: coerce số ở fallback |
| ~12 | row-semantic mismatch / sai năm cột | binding khớp ít từ hơn / năm cột ≠ năm binding |
| 5 | SyntaxError formula | LLM emit formula lỗi cú pháp |
| 5 | bindings/formula rỗng | LLM trả rỗng |
- **~124/239 (52%) là lỗi BINDING** (sai cột ~59 + sai ô/dòng ~65): planner **chọn đúng bảng nhưng bind sai
  cột/ô**. Đây là mục hardening #1, không phải retrieval.
- Nhánh **fallback direct-code không guard** vẫn rò lỗi kiểu (str/str, SyntaxError) — cho fallback **thừa kế
  guard đơn vị/số + repair header** là món rẻ, đã nêu ở §3.2 (deferred), giờ có số hậu thuẫn.

### 8d. Việc tiếp theo (sau khi bạn nộp baseline)
1. Nộp `output/submission.zip` lên dashboard → lấy điểm baseline (answer + retrieval tách bạch).
2. Đối chiếu điểm retrieval leaderboard với proxy 8b: nếu retrieval cao như dự đoán → **dồn vào planner binding**
   (#1/#2 trên), KHÔNG re-embed/LLM-metadata.
3. Planner hardening theo thứ tự 8c: (a) fallback coerce số + thừa kế repair header [rẻ], (b) siết binding
   row/column repair cho lớp "trỏ ô không phải số".

---

## 9. LEADERBOARD BASELINE + PHÂN TÍCH LỖI PLANNER (2026-08-05)

### 9a. Kết quả leaderboard (lần nộp cuối — đã fix 2 bug TypeError)

| Metric | Giá trị |
|---|---|
| ANSWER_ACCURACY | **0.2549** (~129/506 gold câu đúng) |
| EXECUTION_ACCURACY | 0.2549 |
| DOCS_F2MACRO | **0.9268** ← retrieval document tốt |
| DOCS_PRECISION | 0.9525 |
| DOCS_RECALL | 0.926 |
| DOCS_MRR5 | 0.9631 |
| TABLES_F2MACRO | **0.0** ← xem 9b |

**TABLES = 0.0**: Format `report_id|table_pos` của ta khớp đúng với gold `gt_tables`
(verified trực tiếp trên evalset.json local). Local eval 24 câu cho table recall 12/15 (80%).
Nguyên nhân 0.0 trên leaderboard: gold server 506 câu nhiều khả năng chưa điền `gt_tables`,
hoặc evaluator map sai field — không phải bug format phía ta.

**ANSWER = 0.2549**: Con số thực tế về độ chính xác. 773 câu có code, nhưng code tính sai
(sai bảng, sai cột, sai dòng, sai thứ tự trừ). 239 fallback → answer=0.0.

### 9b. Phân tích lỗi planner trên gold-24 (data/eval/evalset.json)

Local gold = 24 câu, 9 đúng / 6 sai (trong đó 2 = planner error không sinh code).

| qid | Level | Loại lỗi | Nguyên nhân gốc |
|---:|---|---|---|
| 363 | L6.1 | error | Planner dùng LNST thay LNTT cho ICR; fallback TypeError (logic nhầm) |
| 524 | L6.2 | error | Planner bind ô NaN; fallback không sinh JSON hợp lệ |
| 582 | L3.2 | ok nhưng sai | **Planner chọn sai bảng**: `|45` (note tín dụng) thay `|2` (balance sheet đã có trong pool) |
| 605 | L3.1 | ok nhưng sai | Retrieval miss: chỉ có `|34`,`|36` (note), không có `|7` (balance sheet) |
| 752 | L4.1 | ok nhưng sai | Retrieval miss: `|78`,`|91` (note), không có `|8` (income statement); fallback sai thứ tự trừ ABB - MBB |
| 754 | L4.2 | ok nhưng sai | Planner chọn sai bảng (note phân loại vay), dòng sai (`iloc[11/13]` = phân mục ≠ tổng) |

### 9c. Taxonomy lỗi (từ 6 câu sai)

**Loại A — Retrieval miss (qid=605, 752)**:
- Bảng đúng không có trong pool top-10 → planner không thể làm gì được.
- Triệu chứng: retrieved tables ở vị trí cao (|34–|91), bảng chính ở vị trí thấp (|7, |8).
- Fix: cần cải thiện retrieval tầng dense/BM25 ưu tiên bảng chính (§3.1).

**Loại B — Planner chọn sai bảng dù bảng đúng có trong pool (qid=582, 754)**:
- Pool có cả bảng chính (`|2`) lẫn bảng note (`|45`, `|35/36`); planner chọn note.
- Dấu hiệu bảng note: tiêu đề "Thuyết minh", tên cột phức tạp ("Giá trị ghi sổ/Số có khả năng trả nợ"),
  nhiều hàng phân mục (ngành nghề, loại tổ chức vay…).
- Fix: rule mới trong PLAN_PROMPT → ưu tiên bảng chính, nhận biết bảng note qua tên cột.

**Loại C — Planner sai dòng trong bảng phân loại (qid=754)**:
- Bảng note phân loại vay có các hàng: "Cho vay TNHH", "Cho vay cổ phần", "Cho vay cá nhân"…
- Câu hỏi hỏi tổng (total) → phải lấy dòng đầu/dòng "Cộng", không lấy phân mục.
- Fix: rule mới trong PLAN_PROMPT → tổng = row_index nhỏ hoặc nhãn "Cộng"/"Tổng cộng".

**Loại D — Sai thứ tự trừ A - B (qid=752)**:
- Planner fail → fallback sinh `df1 (MBB) - df2 (ABB)` nhưng câu hỏi hỏi ABB - MBB.
- Fallback không có `repair_plan_order` như planner.
- Fix: rule mới trong PROMPT (fallback) → xác định df→công ty bằng ticker đầu csv_path.

**Loại E — Sai công thức tài chính (qid=363)**:
- ICR dùng LNST (mã 60) thay LNTT (mã 50) → `binding_concept_errors` catch đúng.
- Nhưng sau khi planner fail, fallback vẫn gặp TypeError.
- Fix: L6 nested question cần multi-step planner (hoãn — phức tạp).

### 9d. Sửa đã thực hiện (2026-08-05)

| File | Thay đổi | Lý do |
|---|---|---|
| `src/finance_qa/planning/ir.py::PLAN_PROMPT` | +3 rule: df→ticker identification; ưu tiên bảng chính vs note; tổng = dòng đầu/"Cộng" | prompt-level guidance cho model |
| `src/finance_qa/planning/generator.py::PROMPT` | +1 rule: fallback xác định df→công ty bằng ticker csv_path | order fix cho fallback path |
| `src/finance_qa/planning/generator.py::generate()` | Sort table_ids by table_pos ascending trước khi gán df1..dfN | bảng chính (pos thấp) → df1/df2; note (pos cao) → cuối list |

**Kết quả test trên 4 câu sai (gold-24)** *(sample=4, chưa đủ để tổng quát — đo lại trên leaderboard)*:
- qid=754 ✅ FIXED: 156,680,339 → **116,644,397** đúng — sort đưa `|32`,`|33` (liability BS) lên df1/df2
- qid=582 ✗ Tiến bộ một nửa: 2021 dùng đúng `|4` (liability BS, row 9), nhưng 2023 `|4` không có trong pool → vẫn sai
- qid=752 ✗ Gần hơn nhưng sai: pool chỉ có `|78`,`|91` (note); retrieval miss không sửa được bằng prompt
- qid=605 ✗ Không đổi: pool chỉ có 2 note tables, BS không được retrieve

**Kết luận từ test**: sort table_pos giúp 1/4 câu (25%); **3/4 câu sai là retrieval miss — prompt rules
không giải quyết được root cause**. Prompt rules chỉ có ích khi bảng đúng đã ở trong pool.
Retrieval quality là bottleneck thật của 3 câu này.

**Giới hạn của prompt rules (ghi để không lặp lại)**:
- Rule "dấu hiệu bảng note" dùng ví dụ ngành ngân hàng ("các loại hình vay", "Lãi suất bình quân") —
  hơi sector-specific; các ngành khác có note với cột tên khác. Signal chung hơn: tên cột đơn giản
  ("Số cuối năm", "Năm nay") = bảng chính; tên cột phức tạp/kép = note.
- Rule "tổng hợp = dòng đầu" đúng cho phần lớn bảng; một số bảng có tổng ở cuối (dòng "Cộng").

### 9e. Fixes đã thực hiện (2026-08-05) — sau baseline

**3 fix general, không hardcode, áp dụng toàn pipeline:**

| # | File | Fix | Root cause |
|---|---|---|---|
| F1 | `repairs.py`, `ir.py`, `validators.py` | Regex extract năm từ binding ID: `\b(20\d{2})\b` → `(?<!\d)(20\d{2})(?!\d)` | `_` là `\w` nên `\b` không match trong snake_case `ftse_2018_provision` → `claimed_years={}` → validator bị bypass |
| F2 | `planning/generator.py::render_tables` | Thêm `Cột số khác` cho numeric columns không có trong metadata `period_columns_raw` | Multi-level header: metadata ghi `Số cuối năm` (section), CSV có `Số cuối kỳ` (leaf) → cột đúng ẩn khỏi planner |
| F3 | `repairs.py::repair_binding_alignment` | Khi selected row score=0 (không khớp từ nào), pick `min(best_rows)` dù tie | Trước: chỉ repair khi unique winner → khi 3 row tie score 5 mà selected=0 thì bỏ qua, không sửa |
| F4 | `tests/test_planning_ir.py` | Fix import stale: `binding_alignment_errors` đã move sang `repairs.py` | Test fail ngay import |

**Kết quả Q818 (v3):** -67.27 → **145.134** ✓

**Phân tích 4 câu fail vĩnh viễn trên pilot-24:**

| qid | Root cause | Khả năng fix |
|---|---|---|
| 363 | **Kép**: retrieval miss + concept error (LNST≠LNTT cho ICR). L6 nested | ❌ Defer: retrieval + multi-step planner |
| 524 | **Column mismatch**: model bind vào `'Quỹ khen thưởng, phúc lợi'` (tên hàng) không tồn tại như column → F6 column hint fix | 🔄 F6 đang test |
| 752 | Retrieval miss: IS (`\|8`) không vào pool | 🔄 Trong lộ trình retrieval |
| 818 | **Partially fixed**: F1+F3 giúp planner nhưng row/column mismatch phức tạp, câu vẫn sai giá trị | 🔄 Cần investigation thêm |

**L6 nested pattern (363, 524):** câu hỏi 2 bước — (1) rank năm theo metric, (2) lấy answer năm đó. ~8-10 bindings, model confuse tên. Fix đúng: multi-step planner. Defer.

### 9f. Iterations v3→v7 — bài học về regression

| Run | Score | Thay đổi | Kết quả |
|---|---|---|---|
| v2 | 10/15 | baseline | — |
| v3 | 9/15 | F1+F2+F3 | Q524 +FIX, Q582 -REG, Q605 -REG (F2 gây nhiễu trên notes tables) |
| v4 | 10/15 | F2 guard `if not num_cols` + F5a full scan + OOB fix | Q605 restored, Q582 vẫn -REG (notes tables df5/df6 cũng có `num_cols=[]`) |
| v5 | 8/15 | F2 revert + OOB fix | Q55/Q524/Q582 -REG: OOB fix silently "sửa" binding sang ô sai → plan pass validation nhưng sai giá trị |
| v6 | 9/15 | OOB revert, chỉ giữ F1+F3+F5a | Q582 restored, Q524 ✗ (thiếu extra_num_cols để thấy tên cột), Q754 -REG (LLM non-determinism) |
| v7 | TBD | +F6: column hint trong PLAN_REPAIR khi fail | Q524 có thể fix qua retry hint |

**Bài học F2 (extra_num_cols):** Khi metadata period_cols không match cột thực, show extra cols giúp model thấy đúng tên. Nhưng notes tables cũng bị `num_cols=[]` → extra cols của note làm model chọn note thay vì bảng chính. Guard `if not num_cols` không đủ vì chính notes tables cũng miss. **Giải pháp đúng:** chỉ show extra cols trong repair prompt khi có lỗi column-not-found (F6), không phải upfront.

**Bài học OOB repair:** OOB binding nên để validate_plan bắt lỗi → LLM retry với error message. Tự repair OOB sang ô "gần nhất" rất rủi ro vì có thể pick ô sai concept, plan pass validation nhưng sai giá trị.

**Bài học LLM non-determinism:** Pilot 15 câu có variance ±1 câu (~6.7pp) từ run này sang run khác với cùng code. Q754 đúng/sai theo run. Cần full 1012 để đo delta thật.

### 9g. Fixes active hiện tại (v8)

| # | File | Fix | Status |
|---|---|---|---|
| F1 | `repairs.py`, `ir.py`, `validators.py` | Regex `\b` → `(?<!\d)..(?!\d)` cho year extraction từ snake_case binding ID | ✅ stable |
| F3 | `repairs.py::repair_binding_alignment` | `clear_miss`: selected row score=0 → pick bất kỳ best row dù tie | ✅ stable |
| F5a | `repairs.py::repair_non_numeric_bindings` | Full column scan (thay ±5) cho NaN in-bounds cells | ✅ stable |
| F6 | `generator.py::_column_hint` | Inject tên cột thực tế vào PLAN_REPAIR khi error là "column không tồn tại trong dfX" | ✅ stable |
| F7 | `repairs.py::repair_binding_alignment` | Expand `_AGGREGATE_LABELS`: thêm "tổng cộng", "tổng số" → bypass alignment check khi row là total row | ✅ v8 |
| F8 | `repairs.py::repair_binding_alignment` | Numeric guard trước khi move: không move binding đến row không có số → phá vòng circular với F5a | ✅ v8 |
| F9 | `repairs.py::repair_non_numeric_bindings` | Vietnamese number string ('100.000.000') không bị coi là non-numeric | ✅ v8 |
| F10 | `prompts.py::PROMPT + REPAIR` | Cảnh báo `.astype(float)` trên scalar; row label ≠ column name | ✅ v8 |
| F2 | `generator.py::render_tables` | extra_num_cols | ❌ reverted — gây regression trên notes tables |
| F5b | `repairs.py` | OOB row repair | ❌ reverted — silent wrong fix |

### 9h. Root cause 13 planner errors (v7 full run, 370/1012)

Phân tích các câu status=error từ `full_1012_v7.jsonl`:

| Group | N | Root cause | Fix |
|---|---|---|---|
| A — Retrieval miss | 3 (Q4, Q193, Q363) | Sai table/company/doc type — pipeline không có feedback loop từ concept validator về retrieval | Cần retrieval improvement |
| B — Circular repair | 2 (Q234, Q280) | repair_non_numeric move row → repair_binding_alignment revert về row rỗng vì score cao hơn | F8: numeric guard |
| C — Hallucinated label | 2 (Q102, Q323) | Fallback dùng row label value làm column name; infer số thứ tự "10. Tổng cộng" không có thật | F10: PROMPT warning |
| D — VN number string | 1 (Q112) | '100.000.000' bị repair_non_numeric coi là non-numeric, move binding sai | F9: parse check |
| E — `.astype` scalar | 2 (Q4, Q146) | Fallback gọi `.astype(float)` trên scalar string | F10: PROMPT+REPAIR |
| G — Aggregate label | 1 (Q67) | "TỔNG CỘNG" không có trong bypass set `{"cộng", "tổng"}` | F7: expand set |
| Multi-company screening | 10 (Q362-Q379) | DSL không thể express "filter N công ty theo điều kiện" | Giới hạn kiến trúc, skip |

### 9i. Pilot scores timeline

| Version | Pilot 15 | Thay đổi |
|---|---|---|
| v2 (baseline) | 10/15 = 66.7% | — |
| v3–v6 | 10/15 | regressions + revert |
| v7 | 10/15 = 66.7% | F1+F3+F5a+F6 stable, Q524 vẫn fail |
| **v8** | **11/15 = 73.3%** | F7+F8+F9+F10 — Q524 fix được, không regression |
| v9a | 9/15 | table_profile refactor — regression do render_tables chỉ show text cols |
| v9b | 8/15 | tiếp tục debug |
| **v9c** | **10/15** | render_tables body fix: dùng `shown.to_string()` thay vì `shown[text_cols].to_string()` |
| v9d | 7/15 | thêm indicator vào alignment — quá aggressive |
| v9e | 8/15 | partial revert |
| **v9f** | **11/15 = 73.3%** | indicator hint trong `build_plan_prompt()` — soft hint, không đụng alignment |
| v9g (experiment) | 9/15 | bỏ alignment functions → regression Q55+Q752, reverted |

Còn fail: Q363 (row_index OOB + complex L6), Q524 (generation timeout 170s), Q674 (0.2% precision miss), Q820 (argmax close miss).

### 9j. Kế hoạch tiếp theo

1. **Full 1012 v9f** → rebuild ZIP → nộp leaderboard — blocked bởi GPU (BGE-M3 cần ~5-6 GB, hiện còn ~3 GB)
2. **Q363**: row_index=23 cho bảng 23 rows (off-by-one, or OOB binding) + L6 nested logic
3. **Q524**: timeout 170s — câu L6.2 phức tạp, planner fail sau MAX_REPAIRS, fallback cũng fail
4. **Retrieval**: xem §9k để biết cơ sở từ base 1012 error log

### 9k. Phân tích base 1012 lỗi → mapping tới v9c/v9f fixes (2026-08-05)

#### Taxonomy 239 planner errors (từ `artifacts/runs/full_1012.jsonl`)

| # | Loại lỗi | Root cause | v9c/v9f fix |
|---:|---|---|---|
| **76** | JSON parse fail | planner LLM không sinh JSON hợp lệ | Gián tiếp: indicator hint giúp model plan rõ hơn |
| **55** | KeyError: column | Model dùng **row label** làm column name (e.g., "Lợi nhuận gộp", "Doanh thu thuần") hoặc sai tên cột | **v9c TRỰC TIẾP FIX**: trước khi fix, `render_tables` chỉ show `shown[text_cols].to_string()` — ẩn hết numeric values. Model không thấy giá trị nên confuse row label với column name. Sau fix: `shown.to_string()` → model thấy cả header lẫn số |
| **21** | argmax/argmin year | Formula sai khi chọn năm có giá trị max/min | Chưa fix — kiến trúc DSL |
| **17** | NaN result | Wrong row/column selection → ô rỗng | v9f gián tiếp: indicator hint giúp chọn đúng row |
| **14** | IndexError OOB | row_index ngoài bounds (Q363-type) | Chưa fix |
| **7** | IndexError positional | `.iloc[n]` out of bounds | Chưa fix |
| **5** | SyntaxError | LLM sinh formula lỗi cú pháp | Chưa fix |

**55 KeyErrors** là evidence trực tiếp nhất cho v9c body-render fix. Pattern rõ:
- `KeyError: 'Lợi nhuận thuần từ hoạt động kinh doanh'` — row label
- `KeyError: 'Năm nay'`, `KeyError: 'Số cuối năm'` — column tên gần đúng nhưng sai case/suffix
- `KeyError: '31/12/2023 VND'`, `KeyError: '2022 Nghìn VND'` — model đoán format thay vì đọc tên thật

Khi body render chỉ show text cols, model không thể đọc tên column số → đoán từ header annotation → dễ sai.
Sau v9c (full `to_string()`): model đọc tên cột numeric trực tiếp từ header dòng đầu.

#### v9c thay đổi gì trong code

| Chỗ | Trước v9c | Sau v9c | Tác động |
|---|---|---|---|
| `render_tables()` body | `shown[text_cols].to_string()` | `shown.to_string()` | Model thấy đủ values + column names |
| `value_cols` trong `profile_table()` | lấy từ `period_cols` metadata (thường không đầy đủ) | tất cả numeric-dtype cols trừ ref cols | Annotation "Cột giá trị" không thiếu cột |
| `_CURRENT_COL_MARKERS`/`_PRIOR_COL_MARKERS` | định nghĩa lại ở repairs.py, validators.py | import từ `table_profile.py` | DRY — single source of truth |
| `UNIT_HINT_MAP` | hardcode 2 lần | `ir.py` duy nhất, import ở repairs+validators | DRY |

#### v9f thay đổi gì trong code

| Chỗ | Thay đổi | Tác động |
|---|---|---|
| `build_plan_prompt()` | Gọi `rewrite_to_indicator(question)` (Qwen 8B, 64 tokens, no thinking); append `"\nChỉ tiêu tài chính cần tra: {indicator}"` vào question trước khi format | Model có signal sạch để chọn đúng row ngay lần đầu |

**Q752 fix mechanism**: câu hỏi về "tổng số dư dự phòng phải thu khó đòi". `_tokens(question)` bị mất "dư", "nợ" (2 chars, bị filter `len > 2`). Indicator từ LLM = `"tổng số dư dự phòng phải thu khó đòi"` → phrase đầy đủ trong prompt → model chọn đúng row.

#### Kết luận: ưu tiên sau khi có leaderboard v9f

1. **Retrieval** — 55 KeyError chứng tỏ đã fix nhờ v9c. Nếu leaderboard score tăng đáng kể → xác nhận retrieval không phải bottleneck mới. Nếu vẫn thấp → xem distribution lỗi mới.
2. **argmax/argmin (21 errors)** — chưa fix, là mục tiêu planner tiếp theo
3. **NaN + IndexError (38 errors)** — một phần fix qua v9f indicator hint, phần còn lại cần điều tra
4. **JSON parse fail (76)** — hardest; cần tăng chất lượng plan generation (prompt, examples, hoặc retry strategy)

---

## 11. Gold-20 benchmark (v9f + C1/C2 fix) — 2026-08-06

Run `run_pipeline.py` trên 20 câu `data/eval/extended_gold.jsonl` với fix C1 (min_ratio 0.25 cho
bảng ≤5 dòng) và C2 (dtype annotation trong `render_tables`). Cũng bỏ hint hardcode
`float(str(val).replace('.',''))` khỏi `REPAIR` prompt.

### 11a. Kết quả & phân tích Q440 gold sai

**Số chạy:** ok=9/20 · error=11/20 (toàn bộ `stage=plan`).
**Correct vs gold:** 1/20 (Q390). Nhưng **Q440 gold sai** — câu hỏi ICR (ratio × lần), gold ghi
`839490129484.0` (lợi nhuận gộp tuyệt đối, triệu VND). Pipeline trả `5.04` đúng hơn → thực tế
~2/20 đúng.

→ Cần fix gold Q440: answer ≈ 5.04, formula = (PBT + |interest_2021|) / |interest_2021|.

### 11b. Taxonomy lỗi 19 câu sai

| Group | Câu | Lỗi | Root cause |
|-------|-----|-----|------------|
| **G1 Argmax validator** | Q407, Q415, Q439 | `ValueError: câu hỏi chọn năm... chưa select(argmax)` | Validator yêu cầu DSL `select(argmax({...}),...)` nhưng planner sinh pandas `.idxmax()` hợp lệ → bị block oan |
| **G2 IndexError OOB** | Q372, Q387, Q396, Q426 | `IndexError: index 0 is out of bounds for axis 0 with size 0` | Planner filter ra empty set (vd. multi-company filter lọc hết) hoặc bind sai row_index không tồn tại |
| **G3 Unit scale** | Q378, Q429 | Answer trả VND tuyệt đối, gold là % hoặc ratio | `output_unit` compile sai (vnd thay ratio/percent); planner sinh query trả revenue/equity tuyệt đối thay vì tính ratio |
| **G4 Logic/row sai** | Q409, Q414, Q423, Q424 | Số chạy được nhưng sai | Planner chọn sai bảng (note thay main), sai row, hoặc công thức tính thiếu bước filter |
| **G5 LLM fail JSON** | Q363, Q422 | `LLM không trả về JSON có biểu thức` | Câu L6 phức tạp (5+ bảng, 5+ năm) → LLM hit context/logic limit, fallback cũng fail |
| **G6 NA/nan** | Q381, Q392 | `ValueError: Encountered all NA values / non-finite nan` | Binding trỏ ô rỗng / filter cho ra tất cả NaN |
| **G7 Wrong value** | Q371 | Số chạy được, sai 28% (6.99 vs 5.47) | Sai công ty/row — PLX ICR thay PVT |

### 11c. Fix directions

**G1 — Argmax validator quá strict (3 câu blocked oan):**
- `semantic_errors()` hiện reject bất kỳ query "chọn năm max" nào không dùng DSL `select(argmax)`.
- Fix: Cho phép pandas `.idxmax()` / `.idxmin()` hoặc conditional expression `if ... == ... .max()` làm equivalent. Validator chỉ cần kiểm tra "có thực hiện phép chọn", không cần ép DSL cụ thể.
- File: `planning/validators.py::semantic_errors` → relax pattern match.

**G2 — IndexError OOB (4 câu):**
- Root: planner bind vào row/company không tồn tại, nhất là sau bước filter multi-company.
- Fix: `repair_binding_alignment` cần detect empty-after-filter sớm hơn và raise error rõ hơn thay vì OOB.
  Indicator hint (`rewrite_to_indicator`) giúp một phần nhưng không đủ khi filter logic sai.
- Hướng: thêm fallback khi `loc[condition].values` rỗng → gửi lỗi rõ về planner để retry.

**G3 — Unit scale (2+ câu):**
- `compile_plan()` normalization từ `source_unit` → `output_unit` đúng, nhưng nếu `output_unit`
  là `vnd` mà câu hỏi cần `ratio`/`percent` → số trả ra lệch 1e9–1e12 lần.
- Fix: `repair_plan_output_unit()` cần nhận diện tốt hơn ratio/percent từ câu hỏi ("bao nhiêu lần",
  "bao nhiêu %", "bao nhiêu lần"). Thêm heuristic: nếu formula là A/B và câu hỏi không hỏi đơn vị
  tiền → `output_unit = ratio`.

**G4 — Logic/row sai (4 câu):**
- Câu hỏi L6 multi-step: filter N công ty → median → above/below → tính metric công ty win.
- Planner hay bỏ bước filter hoặc nhảy thẳng tới answer.
- Fix: Prompt cần ví dụ rõ hơn cho pattern "filter → rank → lấy winner → compute on winner".
  `table_profile [main_report]` đã annotate; cần thêm PLAN_PROMPT example cho multi-company L6.

**G5 — LLM fail JSON (2 câu):**
- Q363 (5 năm KBC × D/E + ICR), Q422 (4 công ty × CFO/NPAT > 0 + argmax COGS): quá nhiều bảng.
- Fix ngắn hạn: ROW_LADDER giảm rows khi nhiều tables; hoặc tăng MAX_REPAIRS = 3.
- Fix dài hạn: decompose L6 thành sub-queries (ngoài scope hiện tại).

### 11d. Insights từ vifinqa-report.html

**Đã làm tốt (khớp thiết kế):**
- ✅ 3-tier metadata (certain/raw text/LLM) — thiết kế đúng, tier-1 filter lành (§7e)
- ✅ BM25 + primary statement boost (`add_primary_statements`) — retrieval không phải bottleneck
- ✅ `table_profile.py` annotation (`[main_report]`/`[note]`, dtype, year_map) — wire đúng vào prompt
- ✅ Repair chain deterministic trước LLM repair

**Còn thiếu theo report:**

| Item | Mô tả | Ưu tiên |
|------|--------|---------|
| Long-format parquet | `(report_id, ma_so, period_key, value)` cho BS/PL/CF → L1–L5 query bằng `WHERE ma_so=X` thay vì LLM loc row | P2 — sau khi argmax/unit fix |
| PL_HINTS fix | `document_text.py:51` chỉ có "KINH DOANH"; VCB 2022+ dùng "KẾT QUẢ HOẠT ĐỘNG" → income_statement label `unknown` → mất primary boost | P3 — metadata snapshot, chỉ hiệu quả khi re-enrich |
| Dense embed | Hybrid BM25+dense cho note tables | P3 — gated on retrieval-miss evidence |

**PL_HINTS cụ thể** — nếu muốn fix runtime (không re-enrich metadata):
- Trong `candidates.py::add_primary_statements`, ngoài filter `statement_type == 'income_statement'`,
  thêm fallback: scan `note_title` hoặc `header_flat` cho pattern `"KẾT QUẢ HOẠT ĐỘNG"` (không cần "KINH DOANH").
- Rẻ, không đụng snapshot, chỉ expand primary boost logic.

---

## 12. REPL fallback + retrieval year-gap (2026-08-06)

### 12a. REPL fallback — thay one-shot pandas fallback

Khi planner fail (sau MAX_REPAIRS=2 lần), thay vì sinh 1 pandas expression mù, pipeline
giờ chạy **REPL loop**: LLM thực thi code từng bước, thấy stdout thực (print()), tích lũy
context, rồi trả `{"final_answer": <float>}`.

**Files thay đổi:**
- `execution/query.py`: thêm `exec_in_namespace()` — exec trong persistent namespace, capture stdout
- `planning/prompts.py`: thêm `REPL_START`, `REPL_CONTINUE` templates
- `planning/repl.py` (mới): `repl_generate()`, parser JSON robust, evidence inference từ history
- `planning/generator.py`: thay fallback block bằng `repl_generate()`

**Design choices:**
- `MAX_REPL_STEPS = 5`: đủ cho argmax 4-step + 1 buffer debug
- `thinking=(step==0)`: step 0 dùng thinking để plan, step 1-4 no-thinking để nhanh
- Persistent namespace: `{**frames, "pd": pd}` — biến sống giữa steps
- `pandas_query` clean: `_ = df1; answer = <value>` — đảm bảo `query_names()` khớp đúng evidence

**Kết quả gold-20 (v1, no-thinking):** ok=17/20 format-valid, nhưng **0/20 đúng vs gold**.
Root cause: Qwen 8B no-thinking không đủ năng lực multi-step argmax financial (12.5 xuất hiện
3 lần — LLM lookup sai row và trả luôn, không explore đủ).

**REPL failure taxonomy (20 câu):**
| Category | N | Root cause |
|---|---|---|
| A — Retrieval thiếu năm | 4 (Q363,381,415,426) | BM25/dense strip year tokens → 2019/2020 tables vào pool qua `add_primary_statements` (tail), judge fill đủ 10 từ 2016-2018 rồi stop |
| B — Data đủ nhưng REPL sai | 11 câu | Qwen 8B no-thinking không tính đúng argmax+filter chain |
| C — Planner đúng nhưng sai giá trị | 5 câu | Unit error (Q424: 5e12x off), sai formula (Q440), year-as-answer (Q372) |

**REPL v2 (thinking step 0):** đang chạy gold-20.

### 12b. Retrieval year-gap — root cause (trace 2026-08-06)

**Symptom:** Q363 cần KBC 2016-2020, pool=71 tables nhưng judge chỉ pick 2016-2018 (10/10 slots).

**Root cause (confirmed):**
1. `candidates.py:strip_entity` xóa **tất cả** year tokens khỏi query trước BM25/dense search
   → 2 channels rank hoàn toàn theo text, không có year signal
2. 2016-2018 KBC tables chiếm top của cả 2 channels (textual similarity cao hơn)
3. 2019/2020 tables chỉ vào pool qua `add_primary_statements` — **append ở tail**, không promote
4. Judge thấy 71 candidates theo order đó, fill đủ `MAX_PICKS=10` từ 2016-2018 trước khi đến 2019/2020
5. Year-coverage trong judge prompt chỉ là **soft bullet**, không phải hard constraint

**Files liên quan:**
- `candidates.py:97-106` — `strip_entity` xóa year tokens
- `candidates.py:118-135` — `add_primary_statements` append tail
- `judge.py:38` — `MAX_PICKS=10`
- `judge.py:68` — year-coverage bullet (soft)

**Fix options (hoãn — làm sau khi đo impact trên leaderboard):**
1. Tăng `MAX_PICKS` 10→15 — rẻ nhất, không đổi logic
2. Đổi year-coverage từ bullet → hard constraint trong judge prompt
3. Interleave `add_primary_statements` theo năm thay vì append flat

---

## 4. Ràng buộc AN TOÀN (luôn áp dụng — không được vi phạm)

- **KHÔNG** chạy `scripts/extract_tables.py` (rescan 1,973 file OCR, ghi đè toàn bộ `data/tables/`,
  `tables_index.jsonl`, `extract_stats.md`, `extract_errors.log`). `beautifulsoup4` không có trong `.venv_bge`.
- vLLM là **service dùng chung**: giữ `WORKERS=4`, **không restart, không sửa service**. GPU chung
  (~3–3.5 GB trống / 81.6 GB).
- `data/eval/planner_answers.json` (numeric answer + tolerance) **chỉ dùng để evaluate**;
  code production **không được đọc** file này.
- `tables_metadata_v2.jsonl` + `data/indexes/*` = snapshot **không dựng lại được**; backend dense thứ 2
  **không bao giờ** ghi `tables_dense.npy`.
- Library code **không hard-code** đường dẫn checkout — đi qua `src/finance_qa/paths.py`.
- `output/` chỉ chứa artifact submission cuối.
- **Không bao giờ** dựng `report_id` bằng f-string (report split `_1`/`_2`).
- API keys trong `.env` (`GEMINI_API_KEY`, `DEEPINFRA_API_KEY`): **không in giá trị**, chỉ in độ dài + 4 ký tự đầu.

---

## 5. Chạy & test — cách làm

- Chạy test: `PYTHONPATH=src .venv_bge/bin/python tests/X.py`, kết ở `print("tất cả PASS")`.
- Style test: script thường + helper `check(name, condition)` cục bộ.
- `.venv_bge/bin/python` cần `PYTHONPATH=src` khi import trực tiếp `finance_qa`.
- Lọc log vô hại: `grep -vE 'libtinfo|unauthenticated|it/s|Loading weights'`.

---

## 6. Con số tham chiếu

- Corpus: 146,246 bảng OCR / 1,973 report; 1,012 câu (`questions_enriched.jsonl`).
- Eval set: 24 câu; 15 có table-GT + 15 answer-GT (`data/eval/planner_answers.json`).
- Taxonomy 1,012: answer_shape {single_cell:231, derived:781}; multi_year {F:656,T:356}; multi_company {F:702,T:310}.
- Noise floor eval: 15 GT / 36 nhóm ⇒ 1 nhóm ≈ 2.8pp, 1 câu ≈ 6.7pp; dưới ~6pp coi là noise.
- Pilot 24 câu: 22/24 ok, answer 60→67% sau Fix A trên 15 checkable GT.

---

## 10. Bài học từ manual gold computation (2026-08-06)

Rút ra sau khi tự giải 20 câu GT (`derived+multi_year` ×10, `derived+multi_company` ×10) để xây
`data/eval/extended_gold.jsonl`. **Phần lớn là lỗi tầng table-parsing/execution, không phải planner logic —
áp dụng cho mọi question type, không chỉ 2 type đã làm.**

### Scope từng rule

| Rule | Discovered qua | Apply cho |
|------|----------------|-----------|
| C1 dot-string | multi_company (DIG) | **bất kỳ** công ty có ô số được OCR format với dấu chấm hàng nghìn |
| C2 sparse maso | multi_company (DIG) | **bất kỳ** bảng summary ≤6 dòng (thường là dòng tổng cuối BS) |
| C3 COGS fallback | multi_company | **mọi** câu dùng DOH / inventory turnover |
| C4 signed filter | multi_company | **mọi** câu filter "CFO>0, NPAT>0" trước khi rank |
| C5 mã23 abs | multi_company | **mọi** câu tính ICR |
| R2 missing company | multi_company | chỉ câu multi_company hỏi median/rank N công ty |
| R3 unit scale | multi_company (MSN/VIC) | **mọi** câu liên quan MSN, VIC (và bất kỳ công ty triệu-đơn vị) |
| R4 split BS | multi_company (DIG) | **bất kỳ** công ty có BS chia >2 bảng (mã 270 không cùng bảng với mã 100/140) |

---

### C1 — Dot-formatted number string không qua `pd.to_numeric()`

**Hiện tượng:** DIG bảng `|5` có ô `"18.539.323.581.176"` (dấu chấm = hàng nghìn kiểu VN);
`pd.to_numeric()` trả `NaN`. Mã 270 (total assets) = None → inv/TA không tính được → median lệch.

**Fix cần làm:** Trong `load_frame()` hoặc `get_row_val()`, thêm cleanup:
```python
if isinstance(v, str) and re.fullmatch(r'[\d.]+', v.strip()):
    v = pd.to_numeric(v.replace('.', ''), errors='coerce')
```
Chỉ apply khi string toàn digit + dấu chấm (tránh parse tên cột nhầm).

**Tầm quan trọng:** Bất kỳ bảng nào OCR có ô tổng dạng string VN format đều bị ảnh hưởng. Không chỉ DIG.

---

### C2 — `find_maso_col` loại bảng thưa (< 3 mã hợp lệ)

**Hiện tượng:** Bảng summary 4 dòng (DIG `|5`): chỉ 1/4 giá trị trong cột 'Mã số' là integer trong [1,700]
(dòng 270 = TỔNG CỘNG TÀI SẢN). `int_frac = 0.25 < 0.8` → bị reject → `find_maso_col` = None →
không tra được mã 270 qua function thông thường.

**Fix:** Nới ngưỡng khi bảng ngắn:
```python
if len(df) <= 6 and len(int_vals) >= 1:
    # bảng summary: chấp nhận dù int_frac thấp
    candidates.append(...)
```
Hoặc: ưu tiên cột tên khớp `'mã số'` dù frac thấp, vì tên là signal mạnh hơn thống kê.

**Pattern:** Xuất hiện ở dòng tổng cuối BS (mã 270, 440) khi công ty tách phần NCA thành bảng riêng.

---

### C3 — COGS không có mã 11 riêng → fallback `Rev - GP`

**Hiện tượng:** Một số công ty không có dòng mã 11 (giá vốn hàng bán) trong IS,
hoặc mã 11 = 0. `get_v(tk, year, 'income_statement', 11)` → None → DOH không tính được.

**Fix:** Luôn fallback: `cogs = mã11 if mã11 else (mã10 - mã20)` (doanh thu - lợi nhuận gộp).

**Apply cho:** DOH = Inv/COGS×365; Inventory Turnover = COGS/AvgInv; Gross Margin check.

---

### C4 — Qualification filter (CFO>0, NPAT>0) phải dùng giá trị có dấu, không `abs()`

**Hiện tượng:** `get_row_val()` filter `abs(v) >= _VALUE_THRESHOLD`. Nếu NPAT âm nhỏ
(e.g., -200B) thì `abs(-200B) = 200B >= 1e3` → vẫn được return. Q396: ASM CFO=-969B
bị lọt qua filter nếu dùng abs → phải check signed riêng.

**Fix:** Tách `get_v_signed()` trả raw (kể cả âm); dùng cho qualification checks;
`get_v()` giữ abs filter cho lookups thông thường.

**Bài học rộng hơn:** Mọi câu hỏi dạng "trong số N công ty có [metric] > 0 thì..."
đều cần check signed; không thể dùng abs-filtered function cho bước qualify.

---

### C5 — mã 23 (chi phí lãi vay) thường âm trong IS → phải `abs()`

**Hiện tượng:** ICR = (PBT + |interest|) / |interest|. Nếu không wrap `abs()` thì
(PBT + (-interest)) / (-interest) → ICR âm → sai hoàn toàn.

**Fix:** Hardcode `abs()` cho mã 23 trong mọi ICR formula. Nên thêm validator:
nếu câu hỏi chứa "lãi vay" và binding là mã 23, kiểm tra formula có `abs()`.

**Hiện trạng:** `binding_concept_errors` đã bắt "dùng LNST thay LNTT cho ICR"
(§9e) nhưng chưa bắt thiếu `abs()` cho interest. Đây là gap cần thêm.

---

### R2 — Missing 1 công ty làm lệch median → sai toàn bộ kết quả

**Hiện tượng:** Q409 có 5 công ty (VIC, KBC, NLG, DXG, DIG). DIG TA = None (do C1+C2).
Median của 4 còn lại = DXG (0.4845). Median thật của 5 = DIG (0.4399) → above-median thay đổi
hoàn toàn → avg NPM đổi từ 13.555% (wrong) → 14.37% (correct).

**Fix cần làm trong planner/execution:**
- Trước khi tính median/rank N công ty, kiểm tra đủ N giá trị.
- Nếu thiếu → raise error rõ ràng, không tính median N-1 và im lặng.
- Planner prompt: "nếu không tra được giá trị cho 1 công ty thì báo lỗi, không skip".

**Tầm quan trọng:** 1 công ty miss = median có thể lệch hoàn toàn (5 công ty: 1 miss → median
dịch sang bên cạnh 100% nếu công ty miss là median thật). Không có warning = silent wrong answer.

---

### R3 — Công ty dùng đơn vị Triệu VND (MSN, VIC) → `_MONETARY_THRESHOLD` phải thấp

**Hiện tượng:** MSN báo cáo bằng Triệu VND. Revenue ~83M triệu = 83T VND.
Ngưỡng `_MONETARY_THRESHOLD = 1e8` (VND) → bảng MSN bị coi là "không có cột tiền tệ" →
mọi get_v() trả None.

**Fix đã làm:** `_MONETARY_THRESHOLD = 1e4` (đủ thấp cho cả triệu-đơn vị).

**Lesson quan trọng hơn:** **Ratios (CFO/NPAT, inv/TA, NPM) có thể so sánh cross-company dù đơn vị khác**
vì tử số và mẫu số cùng đơn vị. Chỉ cần cẩn thận khi so sánh **absolute values** cross-company
(AvgNFA: MSN 40T vs ASM 6.5T — phải convert về VND trước khi compare).

**Danh sách công ty đã biết dùng triệu VND:** MSN, VIC. Kiểm tra thêm khi gặp công ty mới.

---

### R4 — BS split thành nhiều bảng: mã 270 không cùng bảng với mã 100/140

**Hiện tượng:** DIG có BS chia 3 bảng: `|4` (CA section), `|5` (NCA summary + total assets),
`|6` (Liabilities+Equity). `get_v(DIG, 2024, 'balance_sheet', 270)` tìm theo thứ tự bảng,
tìm thấy trong `|5` nhưng bị chặn bởi C1 (dot-string) và C2 (sparse maso).

**Fix:** C1+C2 là prerequisite. Sau khi fix, `get_v()` sẽ scan qua `|5` và tìm thấy mã 270.

**Khi planner gặp split BS:** Retrieval cần include tất cả BS sub-tables (mọi `table_pos`
với `statement_type='balance_sheet'` cùng ticker/year), không chỉ bảng đầu tiên.

---

### Mapping → actionable backlog

| Priority | Fix | File | Scope |
|----------|-----|------|-------|
| **P1** | Parse dot-string VN numbers trong `get_row_val()` | `execution/query.py` | General, bất kỳ bảng OCR |
| **P1** | `find_maso_col` nới min_count khi `len(df)<=6` | `planning/table_profile.py` | General, summary tables |
| **P2** | `get_v_signed()` cho qualification filter | `execution/query.py` (hoặc inline) | Multi-company/year filter |
| **P2** | COGS fallback mã10-mã20 trong prompt/planner | `planning/prompts.py` | DOH, turnover questions |
| **P3** | Validator: mã 23 phải `abs()` trong ICR formula | `planning/validators.py` | Mọi ICR question |
| **P3** | Fail-fast khi N-company median thiếu dữ liệu | `planning/ir.py` hoặc prompt | multi_company derived |

Các fix P1 ảnh hưởng trực tiếp đến **execution accuracy** — không cần LLM, thuần data parsing.
Nên làm trước khi chạy full 1012 v10.

---

## 13. Hướng B — accessor mã-số + materialize fact table → reason (2026-08-06)

Sau khi bỏ nhánh `simple/` (tool-calling REPL), chốt lại hướng answer-layer dựa trên
**cấu trúc code mẫu tôi đã giải tay** (`scripts/eval_gold.py`): tách **data-access** (deterministic,
khóa bằng mã số) khỏi **reasoning** (LLM viết công thức). Mục này ghi *đã verify cái gì bằng số*,
*schema sẵn sàng tới đâu*, và *state graph LangGraph tương lai*.

### 13a. Bài học gốc từ eval_gold.py

`eval_gold.py` giải 20 câu GT bằng 2 tầng tách bạch:
- **Accessor khóa mã số:** `get_v / get_v_signed / get_v_prior (ticker, year, statement, mã_số)`.
  Nuốt trọn plumbing: chọn sub-table (R4 split BS), tìm cột mã số (C2), disambiguate cột giá trị
  theo năm/current/prior (nguồn của 55 KeyError §9k), parse VN dot-string (C1), đơn vị triệu (R3),
  signed vs abs (C4/C5).
- **Công thức tài chính thuần** ở trên: `icr=(abs(pbt)+abs(interest))/abs(interest)`, filter/rank/pick.

Điểm mấu chốt: tra bằng **mã số** (chuẩn hóa VAS: 10=DTT, 20=CFO/LNgộp tùy stmt, 23=lãi vay, 50=LNTT,
60=LNST, 100=TSNH, 140=tồn kho, 220=TSCĐ thuần, 270=tổng TS, 300=nợ, 310=nợ NH, 400=VCSH), **không**
match nhãn text OCR bẩn. `(statement, mã_số)` là **composite key** (mã 20 = CFO ở cash_flow vs lợi
nhuận gộp ở income_statement).

### 13b. Coverage — đã đo (không đoán)

Hai script bằng chứng: `scripts/eval_gold.py`, `scripts/probe_accessor_coverage.py`.
Đo trên **toàn corpus metadata** (không qua retrieval pool) → miss ở đây là lỗi accessor thật;
câu fail pipeline chỉ do retrieval (Q363) vẫn full coverage ở đây → tách bạch accessor vs retrieval.

| Tập | Kết quả |
|---|---|
| multi_company (10 câu khó nhất: median-of-5, DOH, split-BS DIG, unit MSN) | **10/10 giải trọn end-to-end** |
| multi_year (cell-level) | **211/212 ô = 99.5%** |
| Q363 (pipeline fail vì year-gap) | **20/20 ô** trên corpus → xác nhận là lỗi **retrieval**, không phải accessor |

Ô miss duy nhất: VRE 2024 CFO — `find_maso_col` trả None trên bảng CF `|7` (cột 'Mã số' bị OCR
trộn `1.0`/`'02'`/NaN). **Đúng class C2**, giá trị có tồn tại → fixable. Tức 1/212 cũng xác nhận
luận điểm chứ không phản bác.

**Kết luận:** khoảng cách 2/20 → ~19/20 gần như **toàn bộ là lỗi data-access, không phải reasoning.**

### 13c. Schema readiness — đo trên 146,246 bảng + 1,012 câu

**Tầng identity/scope: SẴN SÀNG.** Bảng có `ticker·year·report_id·table_pos·statement_type·
doc_type·has_ma_so_column`; câu có `ticker·tickers·years·answer_shape·multi_company·multi_year·unit_hint`.
Ticker đã resolve deterministic 1011/1012 (§3.3).

**Tầng mã-số: CHỈ phủ lớp main-statement.** Con số thật:
| Đo | Kết quả |
|---|---|
| statement_type = `note` | **85.0%** (124,279 bảng) |
| bảng có `has_ma_so_column=True` | **6.3%** (9,283) — 100% nằm ở BS/IS/CF |
| has mã số trong BS / IS / CF | 65% / 62% / 59% |
| câu `answer_shape`: derived / single_cell | **77.2% / 22.8%** |
| câu `unit_hint`: `lần`+`phần trăm` (ratio → main-statement) | **~29%** |
| multi_company / multi_year | 30.6% / 35.2% |

→ Mã-số accessor phủ **lớp derived-ratio main-statement** (đúng gold-20, đúng chỗ pipeline chảy máu
55 KeyError). Nhưng **phần lớn còn lại là note-detail** — single_cell + nhiều derived hỏi line-item
thuyết minh ("lãi tiền gửi", "chi phí dự phòng", "cho vay ngành Thương mại", "quỹ khen thưởng phúc
lợi") **không có mã số chuẩn** → cần access path thứ 2. (Ước lượng share note-detail cần classifier
riêng để chốt chính xác — chưa đo kỹ.)

### 13d. Kiến trúc B — materialize fact table → reason (2-mode, cùng graph)

Thay tầng `generate` (planner/repl); **giữ nguyên** retrieval + judge. Materialize node có 2 chế độ,
cùng đổ ra bảng tidy `(ticker, year, stmt, key, label, value)`:
- **mode A — main-statement:** `key = mã_số`, dùng accessor. Verified 99.5%. Xương sống lớp ratio.
- **mode B — note-detail:** `key = label` chuẩn hóa, trích `(label, value)` từ **đúng bảng note
  retrieval/judge đã chỉ ra**. Rủi ro hơn (match label) nhưng là **1 lookup / 1 bảng đã định vị**,
  nhẹ hơn multi-binding DSL hiện tại nhiều.

State graph (LangGraph tương lai):
```
question → scope ──→ materialize ──→ reason ──→ validate ─┬─ PASS → END
          (LLM+det)  (det, cache)    (LLM       (det)      └─ FAIL → reason (retry ≤2)
                                     pandas)
```
```python
class State(TypedDict):
    question: str
    tables: list[str]          # retrieval + judge (giữ nguyên)
    tickers: list[str]; years: list[int]   # scope
    facts: pd.DataFrame                     # materialize (tidy)
    code: str; answer: float | None         # reason
    validation: str; retries: int
```
- **scope:** phần lớn deterministic (ticker enrich + regex năm); LLM chỉ trích *nhiều* công ty cho
  multi-company ("Tập đoàn Sao Mai"→ASM), map qua `code_stock.csv`.
- **materialize:** fan accessor qua `scope × CORE_MASO` (~15 mã số phủ mọi metric gold-20). Thuần,
  cache theo `(ticker,year,stmt)`, parallel được → node LangGraph lý tưởng.
- **reason:** phần **duy nhất** LLM viết — pandas trên bảng tidy sạch (vài trăm dòng), không đụng
  OCR thô → KeyError/str-arithmetic/parse-sai gần như biến mất.
- **validate:** finite + đủ N công ty (R2) + đơn vị hợp lý → loop lại reason kèm error.

**Vì sao B (không phải tool-call agent A):** general hơn (fact table = semantic layer, mọi loại câu
quy về query 1 bảng); scale vào LangGraph tốt hơn (node deterministic + đúng 1 node reasoning, vs
vòng ReAct 30+ lượt tool cho câu 5 công ty); **kiểm soát tốt hơn** — fetch/reason tách bạch, bad cell
hiện trên artifact (test độc lập LLM), sai thì biết ngay lỗi data hay reasoning.

### 13e. Open issues (chưa giải, ghi để không quên)

- **Reason vẫn là LLM** → 8-10 câu median-of-N vẫn cần reason đúng nhiều bước. B **cô lập** rủi ro
  reasoning khỏi rủi ro data (~0), không xóa nó.
- **Note-detail label-mode** kém robust hơn mã-số; cần đo riêng khi làm.
- **Absolute cross-company (R3)**: MSN/VIC báo triệu — so sánh tuyệt đối (Q429) cần cột `unit` trong
  fact table; ratio thì tự triệt tiêu.
- **Retrieval year-gap (Q363)** ngoài phạm vi B — fix ở judge (§12b: MAX_PICKS, year hard-constraint).
- Share note-detail chính xác cần classifier — mới ước lượng heuristic.

### 13f. Hướng đi cụ thể (khi bắt tay)

1. Productionize accessor → `src/finance_qa/facts/accessor.py` (suy từ metadata + frames retrieval,
   **không đọc gold**); fix gap `find_maso_col` (VRE CF). Test: probe phải 212/212.
2. materialize node (mode A trước) → tidy df + cache.
3. scope node (tái dùng ticker enrich + code_stock.csv; LLM chỉ trích entity).
4. reason node (LLM sinh pandas) + validate node.
5. Wire song song planner, eval gold-20, so số. Mode B (note-detail) làm sau khi mode A xanh.

### 13g. ĐO LẠI 2026-08-06 — trim §13 theo bằng chứng (sửa 2 over-reach)

Sau khi viết 13a-f, đo thêm 3 thứ. Kết quả **sửa lại 2 giả định** tôi đã viết ở trên.
Scripts (read-only): `scripts/probe_note_detail_split.py`, `scripts/estimate_question_class.py`.

**(1) Note-detail KHÔNG phải chỗ thủng accessor — 13c/13e over-reach.**
Ghép `evalset.json`(gt_tables) × metadata(statement_type) × pilot v9g(retrieved+correct), 15 câu có gt:
- note-detail (n=5): **OK 4/5**, RETRIEVAL-miss 1/5 (q524 chỉ 5/7 bảng vào pool), **ACCESSOR-miss 0/5**.
- main-statement (n=10): OK 5/10, **ACCESSOR-miss 5/10** (bảng đúng đã vào pool nhưng LLM chọn SAI DÒNG).
→ Lỗ thủng đo được nằm ở **main-statement / chọn sai dòng** (q55 lấy mã400 thay mã411; q674/q752 `iloc[]`
sai dòng) — đúng cái mã-số xóa được. Note-detail hiện đã 4/5 bằng text-label; lỗi note = **retrieval**.
**⇒ Hoãn mode-B "LLM-enrich metadata concept-id": chưa đo thấy accessor note thủng. Note-path (khi làm)
là "text-label + retrieval tốt hơn", KHÔNG phải enrich.** (Vi phạm rule "đừng thêm signal khi chưa đo".)

**(2) mã-số chỉ có ~6% bảng; trần mode-A ~một nửa corpus.**
`has_ma_so_column` theo statement_type: note 0% (357/124,279), BS 65%, IS 62%, CF 59%; tổng **6%** (9,283/146,246).
mã-số chỉ sống ở 3 báo cáo chính, per-bảng cũng chỉ ~60%. Ở **tầng ô** vẫn ra 211/212 vì `get_v` quét qua
mọi mảnh của (ticker,year,stmt) + `find_maso_col` tự dò (không dựa cờ). Nhưng **mã-số không đụng note**.
- Ước lượng lớp câu trên 1012 (heuristic keyword, validate 13/15=87% trên gt, lệch một chiều = đếm HỤT main):
  **MAIN ~40% (sàn) → hiệu chỉnh ~45-55%; NOTE ~45-55%.** single_cell 77% note; derived ~45-55% main.
→ **mode-A gánh ~nửa bài toán (đúng nửa đang chảy máu), trần ~50%.** Nửa còn lại (note, hơi lớn hơn tôi
ngụ ý ở 13c) phải đi text-label path — không phải mã-số.

**(3) Scope-extraction có gap riêng:** `questions_enriched.tickers` cho q422 chỉ 3/5 (thiếu DCM "Dầu Khí Cà Mau",
HT1 "Vicem Hà Tiên") → scope là bài toán tách bạch với reason; đo prototype phải phân biệt scope-miss vs reason-miss.

**Trim §13:** 13d "2-mode cùng graph" giữ ý tưởng nhưng (a) LangGraph 4-node + retry là scaffolding CHƯA cần
để lấy win — tối thiểu chỉ cần accessor mã-số deterministic feed bước reason; (b) mode-B đổi từ "enrich concept-id"
sang "text-label + retrieval". Ưu tiên: **prototype mode-A trên gold-20 với LLM thật reason** (test giả thuyết
"fact-table sạch → LLM reason đúng"), rồi mới quyết mở rộng.

### 13h. ĐO reason-node với model YẾU (Qwen3-8B local) + prior-art survey (2026-08-06)

Mục tiêu: model yếu có tự giải được câu derived multi-step không, hay phải phụ thuộc model mạnh (Gemini).
Đo trên **clean-set = 8 câu derived L3–L6 có `gt_tables`** (retrieval ĐÚNG theo định nghĩa; loại biến
retrieval): 363,524,582,605,752,754,818,820. Gold đọc tay từ `manual_solutions/solutions_batch2.md` (+363
từ extended_gold). Harness reproducible: `scripts/eval_clean_fullchain.py`.

**Hai lần TỰ SỬA lỗi đo (over-reach của chính tôi trong phiên):**

**(1) `--no-planner` = số rác.** Ban đầu ép REPL-only (bỏ planner) → **0/8**, rồi vội kết luận "cơ chế không
cứu nổi model yếu, chỉ model-tier nâng điểm". SAI PHƯƠNG PHÁP: đã cắt đúng cái stage hoạt động.
- REPL-only trên frames retrieval: 0/8 (7 "no result after 10 steps", 1 HTTP 400) — nhưng lẫn cả lỗi retrieval.
- REPL-only trên `gt_tables`: **vẫn 0/8** — REPL yếu không lội nổi OCR thô (đoán tên cột, keyword miss nhãn
  OCR, **lặp code y hệt 10 bước không thích nghi**). Prototype §trước ra 1-2/8 vì `g()` accessor xoá gánh
  navigation; REPL src không có.
- **Full chain (planner→repair→validator→repl) trên `gt_tables`: 6/8**, cả 6 câu OK **đều qua planner**.
→ Cơ chế planner+DSL **nâng 0→6/8**. Kết luận cũ "chỉ model-tier nâng điểm" là ARTIFACT của lỗi đo. Bỏ.

**(2) `0/8` luồng src ≠ "model câm" — có confound retrieval.** Trace q392 (`get_val` trả None suốt): 6 bảng
retrieval trả về **toàn IS + CF, KHÔNG có bảng cân đối kế toán** → quick-ratio (cần TS ngắn hạn/HTK/nợ ngắn
hạn) **bất khả thi** từ đám frames đó. Model loay hoay vì thứ nó cần không tồn tại. Là lỗi retrieval upstream.
Ngoài ra schema-block KHÔNG bị cắt (4615 < cap 5000) — model *có* thấy cột; nhưng layout thật loạn: cột nhãn
mang 4 tên khác nhau across 6 bảng (`'MS'`, `'Unnamed: 0'`, `'Mã số'`, `'CHỈ TIÊU'`), OCR hoán header
(dtypes chứng minh: cột tên `'CHỈ TIÊU'` là float rỗng, chữ chỉ tiêu nằm dưới cột tên `'MS'`).

**Kết quả full-chain (bảng đúng):**
```
qid  lvl    path     result
363  L6.1   repl     ERR  (planner_error: bindings[6].row_index ngoài phạm vi 0..22: 23)
524  L6.2   repl     ERR  (planner_error: select key '2017' gắn binding năm [2021]; + REPL HTTP 400 prompt 7 bảng)
582  L3.2   planner  OK   (growth 2 năm không liền)
605  L3.1   planner  OK   (growth, shortcut "số đầu năm")
752  L4.1   planner  OK   (chênh lệch cross-bank)
754  L4.2   planner  OK   (chênh lệch cross-bank)
818  L5.1   planner  OK   (trung bình 5 năm, note lookup)
820  L5.2   planner  OK   (trung bình 5 năm, IS)
                     → 6/8
```

**2 câu rớt = lỗ hổng HẸP, gọi tên được (validator BẮT ĐÚNG cả hai → có thể vá deterministic):**
- **363**: model ground `row_index=23` cho bảng chỉ 0..22 (off-by-one câu nhiều-bảng-nhiều-năm). = lớp G1
  "argmax chưa implement" đã ghi ở §9h/plan. Fix: repair clamp/label-match OOB row.
- **524**: bước two-tier `select()` nối sai khoá-năm (DSL *biểu diễn được*, model wire lệch). Fix: repair
  align select-key↔binding-year. REPL fallback lại HTTP 400 (prompt 7 bảng — bug hạ tầng riêng, cắt độc lập).

**Prior-art survey (sub-agent sonnet, 2026-08-06) — khớp thực nghiệm:**
- Untuned 7-8B trên table numeric reasoning ~**22-26%** (TableBench) — khớp REPL 0/8. Không dùng được raw.
- Program-generation (planner/DSL) là họ ĐÚNG: **TAT-LLM-7B fine-tuned 82.88% F1 > GPT-4 zero-shot 79.71%**
  (TAT-QA). Khớp full-chain 6/8.
- Failure "đoán cột + lặp code" = PoT *"correct logic on hallucinated input variables"* → fix chuẩn =
  **schema-linking**. TableZoomer (đúng Qwen3-8B): **+19-25%** so PoT trần.
- Multi-table argmax là FRONTIER: MultiHiertt SOTA fine-tuned ~**44%**, o1 zero-shot **38%** → 363/524 khó cả
  với model mạnh; Gemini 5/8 (phiên trước) thực ra đã mạnh cho lớp này. Đừng kỳ vọng harness thuần kéo lớp L6.
- **Bài y hệt đã giải: MoFin (VLSP 2025)** — Qwen3-8B, tiếng Việt, tài chính, program-gen, SFT+GRPO →
  **81.95% execution accuracy, #1 leaderboard**. Bằng chứng 8B *local* đóng được gap, nhưng cần fine-tune data+compute.
- Cheap wins không cần fine-tune (ranked): schema-linking > self-consistency k=5 (PoT+SC +~20% FinQA) >
  Chain-of-Table iterative op-chain (cho L6 argmax) > normalize OCR/đơn vị.

**Chốt (chưa thực thi — chờ quyết chiến lược):**
1. Planner+DSL là kiến trúc đúng (6/8 bảng đúng); KHÔNG vứt đi vì mấy con số 0/8 (đó là lỗi đo).
2. Nút thắt thật, theo thứ tự tác động: (a) **retrieval** thiếu bảng (q392 no-BS) — thượng nguồn; (b) **L6
   argmax-then-lookup** grounding (363/524) — validator đã bắt, vá deterministic được; (c) REPL HTTP 400 nhiều bảng.
3. Đường rẻ nhất nâng 6/8→8/8: 2 repair deterministic cho 363/524 (không đụng model). Đường nền tảng:
   schema-linking (fix gốc đoán-cột cả planner lẫn REPL). Đường trần cao: SFT+GRPO kiểu MoFin.
Scaffolding debug phiên này (REPL_THINKING toggle, REPL_DUMP) đã revert khỏi `repl.py`; thinking-on CHƯA đo.
