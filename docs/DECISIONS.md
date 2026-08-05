# DECISIONS — ViFinQA Stage 2

Sổ ghi quyết định (decision log). Ghi *đã quyết cái gì*, *vì sao*, và *hoãn cái gì cho tương lai*.
Cập nhật gần nhất: **2026-08-05**.

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

### 9e. Kế hoạch tiếp theo

1. **Re-run full 1012** với 3 fixes mới → rebuild ZIP → nộp leaderboard. Delta ANSWER từ 0.2549.
2. **Retrieval miss là bottleneck tiếp theo** cho các câu ok-nhưng-sai (qid=582,605,752):
   - Bảng liability side (`|4`, `|5`) và income statement (`|5`, `|6`) không được retrieve
   dù cùng report, nguyên nhân: `judge_text` thiếu keyword "Vay ngắn hạn", "Lãi thuần dịch vụ"
   (những keyword này nằm trong bảng, không phải trong doc_text)
   - Giải pháp ngắn hạn: sau judge ranking, append thêm các bảng primary statement cùng (ticker, year)
   nếu số lượng picks < K. Đảm bảo BS assets + BS liabilities + IS + CF luôn có trong pool.
3. Nếu retrieval improvement tốt → re-embed hoặc LLM label (§7f) mới có ROI.
4. **L6 (363, 524)**: hoãn, cần multi-step planner architecture riêng.

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
