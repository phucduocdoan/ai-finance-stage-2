# Preprocessing vs BTC slide — đối chiếu cho retrieval (2026-08-21)

Đối chiếu `docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf` với tầng preprocessing
hiện tại, để trả lời đúng một câu hỏi: **preprocessing nào còn thiếu và làm retrieval chính
xác hơn được?**

Mọi số trong file này đo trên data của repo này, ngày 2026-08-21. Số lấy từ nguồn khác được
ghi rõ nguồn. Đọc kèm `CONTEXT.md`, `docs/HANDOFF.md`, `docs/DECISIONS.md`,
`docs/v0_retrieval_pipeline.md`, `docs/metadata_audit.md`.

---

## 0. Kết luận

**Recall của retrieval đã gần kín. Chỗ preprocessing còn giúp được là *thứ tự* trong top-20,
không phải recall.**

BM25-only (tắt dense, tắt reranker, tắt judge), 60 câu gold có `evidence_table_id`:

| Bảng gold nằm ở đâu | Số câu |
|---|---:|
| trong shortlist (hard filter) | 59/60 — 98.3% |
| trong pool | 58/60 — 96.7% |
| **trong head-20 (cửa sổ judge)** | **58/60 — 96.7%** |

Phân bố *rank* của bảng gold trong pool đó:

```
rank 1        18  (30.0%)
rank 2-3      15  (25.0%)   → trong top-3 = cửa sổ codegen_max_tables: 33/60 = 55.0%
rank 4-5       8  (13.3%)
rank 6-10     11  (18.3%)
rank 11-20     6  (10.0%)
absent         2  ( 3.3%)
```

Khoảng 96.7% → 55.0% là bài toán **xếp hạng trong 20 ứng viên**, đúng phần reranker + judge
đang gánh (`docs/HANDOFF.md`: table recall vào `table_ids` cuối cùng 83/97 = 85.6%).

Vì sao preprocessing vẫn liên quan: nó là **đầu vào duy nhất** của hai tầng đó.
`CandidateRetriever._rerank_inputs` chấm điểm trên `doc_texts[key]`; judge đọc `judge_text`.
Sửa preprocessing = sửa tín hiệu xếp hạng. Không phải = tăng recall.

Cách lặp lại: xem §5.

---

## 1. Hai giả thuyết đã bị loại

Ghi lại để không ai đi lại:

- **`MAX_LABELS = 60` cắt mất row label?** Không. Số label nhiều nhất toàn corpus là **56**;
  **0 bảng** chạm trần 60.
- **`first_col_labels` thiếu row gold?** Không đáng kể. Trên 60 câu gold: 47 nhãn gold có mặt
  đầy đủ (coverage ≥ 0.8 theo token ≥ 4 ký tự), 3 khớp một phần, 4 không có token đủ dài để
  chấm, 6 không thấy (phần lớn là bảng rollforward / tài sản giữ hộ).
  `first_col_labels` — 67% ký tự của `doc_text` theo docstring `filters.py` — đang **khoẻ**.
- **doc_text trùng nhau trong cùng report?** Chỉ **1.0%** (1.453/146.246, 664 nhóm).
  `judge_text` trùng **3.9%** (5.659).
- **Adaptive top-k?** Luật `k = 2 × số doc` (đo ở repo refactor, +0.146 F2 ở đó) **đã được
  thoả** ở 97.3% câu với `CHANNEL_K = 20` hiện tại — chỉ 27/1012 câu vượt. Không phải chỗ có
  điểm ở repo này.

---

## 2. Đang khớp BTC

Slide BTC prescribe stack `metadata hard filter → BM25 → dense → RRF → rerank → LLM judge`;
repo đang chạy đúng stack đó (`docs/v0_retrieval_pipeline.md`). Per-table metadata schema của
BTC là Company / Year / Report Type / Statement / Table ID / Unit — repo có Company (`ticker`,
`company_name`), Year (`year`), Report Type (`doc_type`), Statement (`statement_type`,
`statement_subtype`). Primary-statement expansion là bonus không có trong slide.

Hai món trong schema BTC còn thiếu: **Unit** (§3.1) và một phần **Statement** (§3.3).

`Table ID` kiểu `VCB-2023-Table-17` của BTC là ngõ cụt đã đóng: 11 lượt submit dò cách đánh số
của `relevant_tables`, trần thực tế ~0.11 `TABLES_F2MACRO`. Xem `docs/tables_metric_probes.md`
trước khi nghĩ lại về nó.

---

## 3. Preprocessing BTC yêu cầu mà repo chưa làm

### 3.1 `header_flat` đang vỡ — chỗ duy nhất có đòn lớn

Toàn 146.246 dòng `tables_metadata_v2.jsonl`:

```
header_flat có unit dính liền số ("2023VND")   28.855   19.7%
header_flat CHÍNH LÀ dòng "Đơn vị tính: …"      7.867    5.4%
header_flat không có năm nào                   84.666   57.9%
header_flat chỉ 1 segment                      10.403    7.1%
header_flat rỗng                                    1    0.0%
```

Top giá trị `header_flat` — vết thương của việc `extract_tables.py` không bung `rowspan`/
`colspan`:

```
7.124  'Số cuối năm | Số đầu năm'
2.215  'Số cuối năm | VND Số đầu năm'                    ← ô unit chèn sai slot
1.976  'Năm nay | VNDNăm trước'                          ← hai tầng dính liền
1.709  'Số cuối nămTriệu đồng | Số đầu nămTriệu đồng'
1.669  'Số cuối nămVND | Số đầu nămVND'
1.421  'Số cuối năm | Đơn vị tính: VND'                  ← cột kỳ 2 bị dòng unit chiếm
1.067  'Đơn vị tính: VND'                                ← header mất trắng
```

Vì sao ăn vào retrieval chứ không chỉ answer:

- reranker chấm `doc_text`, `header_flat` là 1 trong 5 segment của nó;
- repo **đã đo** rằng bỏ `header_flat` khỏi index làm mất retrieval: intra-report top-5
  **72.2% → 63.9%** (`modules/data/preprocessing/document_text.py`, diag_repr.py). Field này
  *có* mang tín hiệu xếp hạng — và 19.7% giá trị của nó là token rác kiểu `2023VND` mà BM25
  không khớp được với bất kỳ query nào.

> **Đã kiểm chứng và BÁC BỎ cho retrieval — xem §7.** Các số dưới đây vẫn đúng như một mô tả
> chất lượng artifact, nhưng giả thuyết "header sạch hơn → xếp hạng tốt hơn" đã được đo và
> không đúng cho channel BM25. Đừng đọc §3.1 như một đề xuất còn mở.

**Đo before/after** trên mẫu 8.591 bảng / 120 report ngẫu nhiên (seed 7), dùng `expand_table`
của repo refactor + flattener tier-aware thô + bóc unit ra field riêng:

| lớp header | trước | sau |
|---|---:|---:|
| ok (có năm, không dính unit, không phải dòng unit) | 18.9% | **42.4%** |
| unit dính liền | 21.5% | **0%** |
| dòng "Đơn vị tính" bị lấy làm header | 4.2% | **0%** |
| không có năm | 55.4% | 56.9% |
| rỗng | 0% | 0.7% |

**Unit bóc được thành field riêng trên 67.4% bảng** — đúng field `Unit` mà BTC bắt buộc và
metadata hiện **không có**.

`no_year` gần như không đổi vì ~56% bảng thật sự dùng nhãn tương đối (`Số cuối năm`); giải nó
cần report year + statement type, là bước riêng (§4), không phải bung span.

**Hồi quy, phải nói ra:** 340 bảng đi từ `ok → no_year`, 52 bảng thành rỗng (~4.6% mẫu).
Flattener dùng để đo là stand-in ~20 dòng, không có phát hiện độ sâu tầng thật. Bản thật
**bắt buộc** có gate hồi quy; không được nhận số tổng rồi bỏ qua phần này.

### 3.2 Propagate section context vào row label — BTC nói rõ, repo không làm

Chỉ khả thi **sau khi** bung span: dòng section hiện ra dưới dạng mọi cột giống hệt nhau
(`['','Ngắn hạn','Ngắn hạn']`, `['','Cổ đông lớn','Cổ đông lớn']`, và
`"LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH"` trải cả 5 cột). Hiện tín hiệu này bị phá ngay ở
`extract_tables.py`.

Đánh trực tiếp vào đúng ca mà `docs/metadata_audit.md` tự nhận là bài toán còn lại: *"selecting
the correct table within an already-correct report, especially when notes and main statements
both contain related terms"* — vì "Ngắn hạn / Dài hạn / Cổ đông lớn" là thứ phân biệt các bảng
note gần trùng nhau.

### 3.3 20.290 bảng `note` không có `note_title`

`judge_text = statement_label | note_title | first_col_labels`, và `statement_label` **cố tình
rỗng** cho `statement_type == "note"` (85% corpus). Nên một bảng note không có `note_title`
thì judge chỉ còn row labels để nhìn.

```
tổng bảng thiếu note_title            42.257  (28.9%)
  trong đó statement_type == note     20.290  (13.9% corpus)   ← mất định danh trong judge_text
  các type khác (BS/IS/CF/entity/…)   21.967                   ← đúng, đã có statement_label
thiếu cả note_title và first_col_labels 1.474
```

**Sửa lại một sai sót trong bản đề xuất nói miệng trước đó:** tôi đã đề xuất kế thừa
`note_title` qua `note_id_inherited` như một món rẻ, độc lập. **Sai.** Đo lại:
**0/42.257** bảng thiếu `note_title` có `note_id` *hoặc* `note_id_inherited`. Hai field rỗng
đúng ở cùng chỗ. Muốn cứu 20.290 bảng này phải suy title từ OCR page text / bảng liền trước,
tức là cùng một section state machine với §3.2 — **không** phải việc rẻ đứng riêng.

### 3.4 `statement_type == "unknown"` trên 2.669 bảng (1.8%)

Những bảng này không có `statement_label` trong cả `doc_text` lẫn `judge_text`.

**Sửa sai sót thứ hai:** `DECISIONS.md` §9 mô tả ghi patch
`artifacts/audits/statement_type_reclassified.jsonl`. File đó **không tồn tại** — §9 là thiết
kế, không phải artifact đã có. Việc thật là *chạy* `statement_type_classifier.py`, review, rồi
merge. Vẫn rẻ, nhưng không phải "merge file có sẵn".

---

## 4. Ba món BTC prescribe mà **không** nên tính vào ngân sách retrieval

- **Resolve kỳ tương đối → ngày tuyệt đối.** Trong kiến trúc này **gần như vô giá trị cho
  retrieval**: `strip_entity` (`modules/rag/candidates.py`) **xoá mọi token năm khỏi query
  BM25** vì hard filter đã tiêu năm rồi; và mọi bảng trong cùng report chia sẻ cùng cột kỳ nên
  năm không phân biệt được bảng nào. Giá trị nằm ở **answer accuracy** (chọn đúng cột) — 30% bảng
  gold cần period resolution mới xác định được cột. Vẫn nên làm, chỉ là đừng tính vào retrieval.
- **Normalize số VN.** Zero giá trị retrieval.
- **Adaptive top-k.** Xem §1. Điểm duy nhất còn treo: `CHANNEL_K = 20` là hằng số trong khi
  shortlist p50 = 143, p90 = 461, max 9.360, trung bình **74.5 bảng/report**, và **31.1% câu
  trải ≥ 4 report** (69 câu ≥ 8 report) — với câu multi-company/multi-year, 20 slot BM25 có thể
  bị một report ăn hết. Gold set 60 câu lệch về single-report (425/1012 câu chỉ 1 report), nên
  96.7% ở §0 có thể lạc quan cho nhóm này. Đề xuất **một probe** cấp phát k theo report
  (BM25-only, local, rẻ), không phải một thay đổi.

---

## 5. Ràng buộc artifact

`data/indexes/tables_dense.npy` là `(146246, 1024) float16`, align **theo vị trí** với
`data/indexes/tables_doc_text.parquet` (146246 × 4, không có key column trong npy), và
**không rebuild được** (metadata v1 đã mất — `DECISIONS.md` §8).

- **BM25 tính lúc query** từ doc_text → hưởng lợi ngay khi sửa;
- **reranker chấm `doc_texts[key]` lúc query** → hưởng lợi ngay;
- **dense vector encode text CŨ** → sau khi sửa doc_text, vector không còn khớp text của chính
  dòng đó.

Hai channel fuse bằng RRF nên chấp nhận được, nhưng phải làm đúng: ghi
`tables_doc_text_v3.parquet` **giữ nguyên 146.246 dòng đúng thứ tự**, cho BM25 + reranker đọc
v3, dense tiếp tục đọc v1. Repo refactor đã đo dense thêm gần như 0 khi candidate đã bị
hard-filter về báo cáo một công ty (+0.004 blended) — nên rủi ro dense đứng ở text cũ là nhỏ.

**Không ghi đè** `tables_metadata_v2.jsonl`, `tables_doc_text.parquet`, `tables_dense.npy`.

---

## 6. Thứ tự đề xuất

| # | Việc | Đo được gì | Ghi chú |
|---|---|---|---|
| 1 | Chạy `statement_type_classifier.py`, review, merge patch | 2.669 bảng có `statement_label` | §3.4 — file patch chưa tồn tại, phải chạy |
| 2 | **Bung span + flatten tier + bóc `unit`** → `header_flat` v3 | ok 18.9%→42.4%, fused 21.5%→0, unitline 4.2%→0, unit có trên 67.4% | §3.1, đòn chính |
| 3 | Section state machine: propagate section vào row label **+** suy `note_title` cho 20.290 bảng note | chỉ đo được sau #2 | §3.2 + §3.3, cùng một máy |
| 4 | Probe cấp phát k theo report | pool recall trên nhóm ≥ 4 report | §4, BM25-only |

### Gate — đo trước khi sang bước sau

BM25-only, không cần GPU, không cần LLM, chạy vài phút:

- `gold trong head-20`: hiện **58/60**. **Không được giảm.**
- `gold trong top-3`: hiện **33/60 = 55.0%**. Đây là con số cần tăng, và là con số duy nhất
  nối trực tiếp với `codegen_max_tables = 3`.
- Chỉ khi hai số trên ổn mới bật reranker + judge để đo `table_ids` cuối cùng so với baseline
  83/97.

Cách lặp lại gate: dựng `CandidateRetriever(use_dense=False, reranker=None, judge_top_n=20)`,
duyệt `data/eval/unbiased60_gold.jsonl`, tách `evidence_table_id` bằng `re.split(r'[;&]', …)`
rồi lấy tiền tố khớp `^([A-Za-z0-9_]+\|\d+)` (22/60 dòng có 2–5 bảng; coi nó là atomic từng
làm đảo taxonomy miss — `CONTEXT.md`), so với `pool.keys` / `pool.ranked` / `pool.ranked[:20]` /
`pool.ranked[:3]`.

### Kỳ vọng — nói rõ để không tự lừa

`55.0% → ?` **không** suy ra được từ các số đã đo. "42.4% header đúng thay vì 18.9%" là cải
thiện *đầu vào* của reranker, không phải cải thiện rank đã đo. Bước #2 phải chạy như một thí
nghiệm có gate, không như một cải tiến đã biết trước kết quả.

---

## 7. Kết quả bước #2 — âm (2026-08-21, cùng ngày)

Bước #2 đã được cài và đo. **Gate không nhúc nhích.**

| metric | v2 baseline | v3 |
|---|---:|---:|
| gold trong shortlist | 59/60 | 59/60 |
| gold trong pool | 58/60 | 58/60 |
| gold trong head-20 | 58/60 | 58/60 |
| **gold trong top-3** | **33/60 = 55.0%** | **33/60 = 55.0%** |

Không phải no-op ẩn — đã kiểm: **110.200/146.246** doc_text khác nhau, thứ tự head-20 đổi trên
60/60 câu, rank gold đổi trên 22/60 câu (**9 tốt hơn, 13 tệ hơn**). Top-3 membership: #161, #845
vào; #753, #920 ra. Hoà đúng nghĩa.

Chất lượng artifact thì cải thiện thật (classifier riêng, viết lại, nên **không** so trực tiếp
được với số mẫu ở §3.1 — cùng classifier chỉ so được before/after với nhau):

| class | v2 | v3 |
|---|---:|---:|
| ok | 43.767 (29.9%) | 69.874 (47.8%) |
| fused | 29.828 (20.4%) | 71 (0.0%) |
| unitline | 1.617 (1.1%) | 0 (0.0%) |
| no_year | 71.033 (48.6%) | 75.906 (51.9%) |
| empty | 1 (0.0%) | 395 (0.3%) |

Hồi quy **thấp hơn nhiều** so với lo ngại ở §3.1: `ok → no_year` 6, `ok → fused` 2, `ok → empty`
0 — tổng **8/43.767 = 0.0%**, không phải ~4.6% như mẫu stand-in. 395 dòng mới `empty` đều đến từ
v2-`no_year` (201) và v2-`unitline` (194), tức header gốc vốn đã là boilerplate thuần
(`'Triệu VND'`, `'Đơn vị tính: VND'`) — không mất thông tin thực. Field `unit` mới có giá trị trên
**84.583/146.246 = 57.8%** (không phải 67.4% như mẫu): VND 58.537, Triệu VND 24.539, Nghìn VND 887,
USD 441, Tỷ VND 175, Triệu USD 4.

### Vì sao âm — và vì sao đây là bác bỏ thật, không phải lỗi gate

Token rác kiểu `2023VND` là **trơ**: nó không khớp query nào, nhưng cũng không gây khớp sai. Làm
sạch nó vì thế không thể dịch chuyển rank BM25. Điều này *nhất quán* với con số 72.2% → 63.9% ở
§3.1: bỏ **cả field** làm mất những token thật sự khớp (`Số cuối năm`…), còn dọn vệ sinh token thì
không thêm gì. Hai quan sát không mâu thuẫn.

**Hai channel chưa bị test, phải nói rõ:**

- **judge**: `judge_text` khác nhau trên **0/146.246 dòng** — vì `build_judge_text` cố tình không
  chứa `header_flat`. Judge nhìn thấy y nguyên như cũ. #2 chưa từng chạm vào nó.
- **reranker**: gate chạy `reranker=None` cho rẻ. Reranker là model semantic chấm **toàn bộ**
  `doc_text`, tức là tầng duy nhất có thể phản ứng với `Số cuối nămTriệu đồng` vs `Số cuối năm`.

Nên muốn đóng hẳn giả thuyết header_flat: chạy lại gate một lần với `reranker="qwen3-0.6b"`. Nếu
cũng âm → **đóng header_flat như một đòn retrieval, dứt điểm.**

### Không dùng lý lẽ sunk cost

Sub-agent khuyến nghị đi tiếp #3 một phần vì "nếu dừng thì khoản đầu tư port grid.py coi như lãng
phí". **Đó không phải lý do hợp lệ** và không được ghi vào quyết định. Chi phí đã bỏ ra không nói
gì về giá trị bước tiếp theo.

Lý do hợp lệ để giữ artifact v3 là lý do khác: nó là **tiền đề của phía answer**, đúng chỗ mà bằng
chứng gốc từ slide BTC đã chỉ tới ngay từ đầu — 54.7% lỗi e2e là numerical extraction, 12/35 miss
là đọc sai ô dù đã show đủ gold table, 30% bảng gold có header vỡ đến mức không suy ra được cột.
Field `unit` (57.8%) và header đã bung tầng phục vụ đúng việc đó, không phục vụ xếp hạng.

### Quyết định

- **Không** đi tiếp #3 như một nước đi retrieval. §0 vẫn đứng: recall đã kín, và #2 vừa cho thấy
  vệ sinh text không dịch được rank.
- Đổi gate của v3 sang **phía answer**: gold accuracy trên 73 câu, baseline **38/73**
  (`docs/HANDOFF.md`). Đây là nơi bằng chứng luôn chỉ tới.
- Một lần chạy gate với reranker bật để đóng sổ giả thuyết header_flat.
- #3 (section state machine + suy `note_title` cho 20.290 bảng note) là món **duy nhất** còn có
  đường tác động lên judge, vì nó sửa `judge_text` — thứ mà #2 chứng minh là chưa hề bị chạm. Nếu
  làm #3, gate phải là judge/`table_ids`, không phải BM25 top-3.

### Đóng sổ: gate với reranker bật

Chạy lại đúng gate, `reranker="qwen3-0.6b"`, `use_dense=False`, cùng script. `shortlist`/`pool`/
`head-20` giống bit-for-bit run BM25-only (reranker đổi **thứ tự** trong pool, không đổi
**membership**) nên chỉ `top-3` có nghĩa. Reranker là **API trả phí** (`DeepInfraReranker`,
`clients.py`) nên không deterministic — đã chạy 5 lần:

| run | v2 top-3 | v3 top-3 | v3−v2 |
|---|---:|---:|---:|
| 1 | 29/60 | 31/60 | +2 |
| 2 | 29/60 | 30/60 | +1 |
| 3 | 30/60 | 31/60 | +1 |
| 4 | 29/60 | 30/60 | +1 |
| 5 | 30/60 | 30/60 | 0 |

v3 ≥ v2 ở **5/5** lần, trung bình **+1.0/60 (+1.7pp)**. Đúng như dự đoán: tín hiệu của
`header_flat` nằm ở tầng **semantic**, không ở tầng lexical — token `2023VND` trơ với BM25 nhưng
cross-encoder có phản ứng nhẹ.

**Phán quyết: giả thuyết sống nhưng không đủ để đổi hướng.** +1/60 nằm ngay trong nhiễu một lần
chạy (v2 tự nó dao động 29–30). Tính nhất quán về dấu ở 5 lần chỉ nói rằng chênh lệch rank là ổn
định, không nói rằng hiệu ứng lớn. Không được ghi đây là "cải thiện retrieval".

### Phát hiện phụ, lớn hơn cả câu hỏi ban đầu: reranker đang làm top-3 TỆ hơn

Không phải câu được giao, nhưng số đã có:

```
BM25-only, không reranker :  33/60 = 55.0%   (cả v2 và v3)
+ reranker qwen3-0.6b     :  v2 29–30/60 (48.3–50.0%)   v3 30–31/60 (50.0–51.7%)
```

**Trên cả hai artifact, bật reranker làm top-3 giảm ~3–7pp.** Điều này **độc lập trùng khớp** với
số đo ở repo refactor: cross-encoder rerank *làm tệ đi* sau khi đã có hard filter
(F2 0.601 → 0.432 @top-10). Hai codebase khác nhau, hai metric khác nhau, cùng một chiều.

`reranker = "qwen3-0.6b"` đang là **default của graph** (`agents/finance/config.py`), tốn tiền API
mỗi câu, và có dấu hiệu đang phá đúng cửa sổ top-3 nuôi `codegen_max_tables = 3`.

**Giới hạn của kết luận này, phải nói rõ:** gate này **không có judge**. Pipeline thật là
reranker → judge chọn từ head-20 → codegen lấy 3. Judge có thể sửa lại phần reranker làm hỏng.
`DECISIONS.md` §3 ghi `judge_thinking=False` "beats thinking=True at every K once qwen3 reranks
first" — tức reranker được đo *kèm* judge, nhưng **không có chỗ nào trong docs ghi một so sánh
đối đầu `reranker=None` vs `reranker="qwen3-0.6b"` khi judge bật**. Câu hỏi đang mở thật.

~~Thí nghiệm tiếp theo: chạy gate có judge, so `reranker=None` vs `reranker="qwen3-0.6b"`.~~
**Rút lại — xem §9.** Đó là một nhị phân giả.

### Artifact do #2 tạo (chưa commit)

```
src/finance_qa/modules/data/preprocessing/grid.py           port expand_table (0 mismatch / 29.106 bảng)
src/finance_qa/modules/data/preprocessing/header_flatten.py flattener tier-aware + bóc unit
src/finance_qa/modules/data/preprocessing/metadata_v3.py    builder + assert 146.246 dòng, đúng thứ tự
scripts/build_metadata_v3.py · scripts/gate_header_v3.py · scripts/classify_header_quality.py
data/metadata/tables_metadata_v3.jsonl        298.2 MB
data/indexes/tables_doc_text_v3.parquet       35.4 MB, 146.246 dòng, thứ tự khớp v1 (đã verify)
```

Ba file protected không đổi: `tables_metadata_v2.jsonl` md5 `0d1362c04180730c06f1c4765a7e229f`,
`tables_doc_text.parquet` và `tables_dense.npy` nguyên trạng, `git status data/` sạch.

---

## 9. Ba đính chính (2026-08-21, sau khi user phản biện)

### 9.1 v3 **không thể** chạm tới codegen — sai sót scope nghiêm trọng nhất

Mọi solver đọc frame qua `table_store.load_frame(table_id)`: `codegen/codegen.py:233`,
`solvers/cell_locator.py:332`, `solvers/raw_table_linker.py` (5 chỗ),
`solvers/raw_selection_linker.py:805`, `facts/table_profile.py`,
`solvers/table_linking/{rows,columns}.py`. Hàm đó đọc `data/tables/{doc}/table_{pos}.csv` —
**CSV chưa bung span** — rồi đắp `repair_shifted_bank_header` / `repair_shifted_multilevel_header`.

Bước #2 chỉ build lại `tables_metadata_v3.jsonl` + `tables_doc_text_v3.parquet`, tức **tầng text
cho retrieval**. **Frame mà model nhìn thấy không đổi một dòng nào.**

Tổng kết giá trị v3 như đang có: retrieval ~0 (§7), codegen **đúng 0**. Đây là lỗi của brief
giao cho sub-agent: bằng chứng gốc chỉ vào phía answer (54.7% lỗi e2e là numerical extraction;
12/35 miss là đọc sai ô dù đã show đủ gold table) mà brief lại yêu cầu build nửa metadata rồi
gate bằng retrieval.

Muốn v3 có giá trị: emit **bảng đã bung span + normalize** (Parquet `cells_json` hoặc CSV v3), cho
`CsvTableStore.load_frame` đọc nó **sau một flag**. Gate: gold accuracy trên 73, baseline **38/73**.

### 9.2 Field `unit` phần lớn là dư — rút lại claim ở §3.1

`modules/solve/common/units.py` **đã** đọc banner rows trong grid + column names +
`context_page_text`, có precedence đo được và provenance string. Docstring của nó: detection đúng
**14/15** khi bảng khai báo gì đó; khi không khai báo gì thì cell là raw VND ở 9/12 ca. Module đó
tồn tại chính vì 24.2% bảng chỉ khai unit **trong grid**.

Thêm nữa: `_MONEY_PATTERNS` dùng `re.search`, nên `'Số cuối nămTriệu đồng'` **vẫn** match
`triệu đồng`. **Fusion không phá được unit detection.** Nên "field `unit` có giá trị lớn cho
answer" ở §3.1 là sai — nó chỉ thêm một nguồn thứ tư cho một tầng đã gần trần.

### 9.3 "reranker on/off" là nhị phân giả — rút lại đề xuất ở §8

`_ordered()` trong `retrievers/clients.py` trả về **chỉ thứ tự**; `scores` bị bỏ:

```python
return [keys[i] for i in sorted(range(len(keys)), key=lambda i: (-scores[i], i))]
```

Nên hôm nay reranker chỉ làm được **re-sorter**, không làm được **rejector** — threshold không
diễn đạt được. Judge cũng vậy: `rerank_with_picks` đặt picks lên đầu rồi **giữ nguyên đuôi**, tức
bảo toàn membership, không bao giờ loại ai.

Đó là lý do §8 ra âm: gate bắt reranker **thay thế** thứ tự BM25. Nhưng "sắp xếp tệ hơn" **không**
kéo theo "lọc tệ hơn" — một model có thể dở ở việc nói cái nào nhất mà vẫn giỏi ở việc nói cái nào
chắc chắn sai. Gate chỉ đo câu thứ nhất.

Thiết kế đúng: trả `scores` ra khỏi `rerank_order`, dùng ngưỡng để **loại** ứng viên rồi mới lấy
top-k — reranker/judge làm **bộ lọc precision nuôi 3 slot của codegen**, không phải bộ sắp xếp.
Số ở §8 (reranker kém BM25 khi làm sorter, ~3–7pp) vẫn đứng như một phép đo về *vai trò sorter*,
và vẫn trùng chiều với repo refactor (F2 0.601 → 0.432 @top-10) — nhưng nó không kết luận gì về
vai trò rejector.

## 10. Kết quả arm dense — hai kết luận, một dương (2026-08-21, cùng ngày)

§7 chỉ chạy `use_dense=False`, nên giả thuyết header mới chỉ bị bác trên channel mà nó
*không nên* có tác dụng. bge-m3 **rebuild được** (`BAAI/bge-m3` local qua transformers,
`scripts/build_dense_variant.py`, 1.2–1.6 min cho 146.246 doc trên H100 chia sẻ) — §5 và
`DECISIONS.md:207` nói "không tái tạo được index hiện có", đúng, nhưng tôi đã đọc thành
"không dựng lại được index", sai.

### 10.1 `tables_dense.npy` KHÔNG stale — đóng lại nỗi lo ở DECISIONS.md §8

`cos(tables_dense.npy, rebuild-từ-doc_text-v2)`: mean **1.0000**, p1 0.9994, **0%** dưới 0.99.
Tức text v1 đã sinh ra doc_text giống v2. Nghi vấn "19k primary statement trong index không
mang `statement_label`" là **sai**. Gate cũng khớp tuyệt đối: arm A ≡ arm B trên cả 4 cutoff.
Kèm theo: encoder + builder deterministic, nên artifact này giờ **có** đường tái tạo.

### 10.2 Header v3 làm dense **tệ hơn** — bác bỏ trên channel thứ hai

Arm B (doc_text v2) → arm C (doc_text v3), cùng encoder, cùng builder, n=60:

| cutoff | B | C | delta |
|---|---|---|---|
| top-1 | 24/60 | 14/60 | **−10** |
| top-3 | 34/60 | 32/60 | −2 |
| top-5 | 44/60 | 44/60 | 0 |
| top-20 | 57/60 | 56/60 | −1 |

`same 28 / better 10 / worse 22`. Không phải churn. Cơ chế tôi đoán đầu tiên — "dọn header làm
mất fingerprint giữa các bảng cùng report" — **đã đo và sai**: v3 distinct *hơn* (47.137 vs
30.192 header khác nhau; trùng nội-report 44,25% vs 52,61%), doc_text trùng gần như không đổi
(789 → 746). Giả thuyết còn sống, **chưa xác minh**: v3 làm header distinct hơn trên một trục
mà query không có tín hiệu (`strip_entity` đã xoá năm khỏi query), nên CLS vector bị đẩy đi mà
không thêm gì để khớp.

**Kết luận: hướng header_flat v3 chết trên cả hai channel.** Không đưa vào production.

### 10.3 Dương: BM25 và dense muốn text KHÁC nhau

Kiểm chứng trực tiếp giả thuyết ở 10.2 — bỏ `header_flat` **chỉ khỏi dense**, BM25 vẫn đọc
doc_text v2 ở cả hai arm (`scripts/gate_dense_text.py`, `tables_dense_noheader.npy`):

| | unbiased60 (n=60) | gold94 (n=94, disjoint) |
|---|---|---|
| in pool | 59 → 58 (**−1**) | 91 → 91 (0) |
| top-1 | 24 → 24 (0) | 50 → 51 (+1) |
| **top-3** | 34 → **37 (+3)** | 62 → **66 (+4)** |
| top-5 | 44 → 45 (+1) | 68 → 69 (+1) |
| top-10 | 49 → 51 (+2) | 77 → 79 (+2) |
| top-20 | 57 → 56 (−1) | 86 → 85 (−1) |
| ranks moved | 30: 17 tốt / 13 tệ | 31: 23 tốt / 8 tệ |

Replicate trên set độc lập, cùng signature: **top-3 +7/154 (62,3% → 66,9%)**, top-10 +4, đổi lại
pool −1 và top-20 −2. Deterministic, không API, chạy lại cho đúng số.

Đây là bằng chứng cho đề xuất "tách cột" của user: `header_flat` **load-bearing cho BM25**
(bỏ khỏi index → intra-report top5 72,2% → 63,9%) nhưng **là nhiễu cho dense**. Một cột
`doc_text` dùng chung là thoả hiệp, không phải thiết kế.

Đánh đổi phải nói rõ: top-3 là cutoff nuôi `codegen_max_tables=3` nên +7 vào thẳng chỗ cần;
nhưng pool −1 là **trần cứng** (judge production đọc cả pool, `judge_top_n` off by default),
mất là mất hẳn. Với F2 nghiêng recall thì −1 pool không miễn phí.

Chưa ship. Muốn ship thì cần: thêm cột `dense_text` vào parquet (để split là thiết kế hiện rõ,
không phải hai file rời), một index mới ở staging path, và không bao giờ ghi đè `tables_dense.npy`.

### Artifact do §10 tạo (chưa commit)

```
scripts/build_dense_variant.py                    builder, từ chối ghi DENSE_INDEX_PATH
scripts/gate_dense_text.py                        gate 2 arm × 2 eval set
scripts/gate_header_v3.py                         +cờ --dense (3 arm A/B/C)
data/indexes/tables_dense_v2rebuilt.npy   285.6M  rebuild từ doc_text v2  (≡ production)
data/indexes/tables_dense_v3.npy          285.6M  từ doc_text v3          (tệ hơn)
data/indexes/tables_dense_noheader.npy    285.6M  từ doc_text bỏ header_flat (tốt hơn)
data/indexes/tables_doc_text_noheader.parquet     row order đã assert khớp v2
```

### 10.4 Ablation `dense_text` — tiêu chí "ít trùng lặp" đúng một nửa

Tiêu chí user đề ra: BM25 giữ phần trùng lặp (nó có IDF để triệt), dense chỉ nên chứa
unique semantic. Độ unique từng segment trên 146.246 bảng:

| segment | non-empty | distinct | trùng nội-report | % chars |
|---|---|---|---|---|
| `statement_label` | 13,2% | **8** | 92,7% | 1,0% |
| `note_title` | 71,1% | 5.399 | 58,0% | 6,2% |
| `section_title` | 57,5% | 5.839 | **89,1%** | 10,9% |
| `first_col_labels` | 97,4% | **98.480** | **3,6%** | 67,4% |
| `header_flat` | 100% | 30.192 | 52,6% | 14,5% |

Năm biến thể, BM25 đọc doc_text v2 ở mọi arm, chỉ index dense đổi. Gộp hai eval set (n=154):

| dense_text | pool | top-1 | top-3 | top-5 | top-10 | top-20 |
|---|---|---|---|---|---|---|
| `doc_text` (baseline) | **150** | 74 | 96 | 112 | 126 | **143** |
| − `header_flat` | 149 | **75** | 103 | 114 | **130** | 141 |
| − header − section (= `judge_text`) | 149 | 73 | **104** | **115** | 129 | 139 |
| `note_title` + labels | 149 | 67 | 100 | 112 | 131 | 142 |
| labels only | 149 | 61 | 101 | 116 | 126 | 140 |

**Ngoại lệ quan trọng:** `statement_label` có độ trùng **cao nhất** (92,7%, đúng 8 giá trị trên
toàn corpus, 1,0% ký tự) — theo tiêu chí "ít trùng lặp" thì nó phải bị bỏ đầu tiên. Bỏ nó
(`note_title` + labels) làm **top-1 tụt 75 → 67**; bỏ cả `note_title` nữa thì **61**.

Nên tiêu chí đúng không phải "ít trùng lặp" mà là **"query có tín hiệu trên trục đó hay không"**.
Tên cột kỳ (`Số cuối năm`, `31/12/2023`) query không bao giờ hỏi → với dense là nhiễu thuần.
`statement_label` trùng gần như tuyệt đối nhưng query *có* nói "bảng cân đối kế toán" → 4 ký tự
trung bình mà đổi được 8 câu top-1. Độ entropy thấp ≠ vô dụng.

**Chốt: `dense_text = doc_text − header_flat`.** Không đi xa hơn: bỏ thêm `section_title` được
+1 top-3 nhưng −2 top-1 và −2 top-20, tức đổi ngang trong noise, mà thay đổi lại to hơn.
Bỏ `header_flat` là thay đổi nhỏ nhất cho gần hết phần lợi: **top-3 +7, top-10 +4, top-1 +1**,
trả giá **pool −1, top-20 −2**.

`pool −1` xuất hiện ở *mọi* biến thể strip trên unbiased60 (59→58) và không xuất hiện trên
gold94 (91→91) — tức là một câu cụ thể mà gold chỉ vào được pool nhờ dense khớp header, chứ
không phải xu hướng theo mức strip.

### Artifact do §10.4 tạo (chưa commit)

```
data/indexes/tables_dense_judgetext.npy    285.6M  index trên cột judge_text sẵn có
data/indexes/tables_dense_nt_labels.npy    285.6M  note_title + first_col_labels
data/indexes/tables_dense_labelsonly.npy   285.6M  chỉ first_col_labels
data/indexes/tables_doc_text_{labelsonly,nt_labels}.parquet
scripts/build_dense_variant.py                     +cờ --column
scripts/gate_dense_text.py                         5 biến thể × 2 eval set
```

### 10.5 Cái +7 đó **không tới được** production — reranker ghi đè thứ tự

§10.4 đo với `reranker=None`. Production mặc định `reranker="qwen3-0.6b"`, và
`CandidateRetriever._arerank` chấm lại **toàn bộ** pool rồi *thay* `pool.ranked`. Nghĩa là
thứ tự fused — chỗ duy nhất cái +7 top-3 nằm — bị bỏ đi. Với reranker bật, dense channel chỉ
còn tác dụng qua **thành phần** (membership) của pool.

Membership không phụ thuộc reranker (`_rerank_inputs`: *"pool membership is unchanged, only the
order moves"*), nên đo được miễn phí và **chính xác cho production**
(`scripts/probe_dense_membership.py`, n=154):

| | unbiased60 | gold94 |
|---|---|---|
| pool giống hệt | 1/60 | 3/94 |
| gold trong pool: `doc_text` → `dense_text` | 59 → **58** | 91 → 91 |
| trong số pool khác nhau: gold thêm / mất | 0 / **1** (q166) | 0 / 0 |
| symmetric difference | trung vị 5 bảng / pool ~36 | trung vị 5 bảng / pool ~37 |

Pool đổi thật (150/154 câu, ~5 bảng mỗi câu) nên đây không phải no-op — nhưng đổi theo hướng
**trần thấp hơn 1** và **không thêm câu nào**.

Còn hiệu ứng bậc hai — 5 bảng khác nhau làm reranker chấm trên tập khác, nên cửa sổ top-20 mà
`judge_top_n` cắt có thể đổi. Cái này cần gọi reranker trả phí; tôi đã ước sai nó thành rào cản.
Thực tế: 154 câu × 1 call, ~1,6M token trên model **0,6B** — cỡ vài cent. Đã chạy
(`--reranker`), 2×2 arm, cùng một code path nên so được:

| arm | pool | top-1 | top-3 | top-5 | top-10 | top-20 |
|---|---|---|---|---|---|---|
| fused, `doc_text` | 150 | 74 | 96 | 112 | 126 | 143 |
| fused, `dense_text` | 149 | 75 | **103** | 114 | 130 | 141 |
| reranked, `doc_text` | 150 | 53 | 89 | 104 | 126 | **148** |
| reranked, `dense_text` | 149 | 53 | 88 | 107 | 128 | **148** |

Hai dòng `fused` trùng **từng ô** với bảng §10.4 dù đi qua script khác và parquet production —
đó là kiểm chứng chéo cho cả hai script.

Đọc ra hai điều. Một: reranker **dời recall từ đầu xuống cuối cửa sổ** — top-1 74→53, top-3
96→89, nhưng top-20 143→148. Vì judge đọc cả 20 rồi tự chọn lại, top-20 mới là metric đúng cho
nó, nên reranker vẫn xứng chỗ; nhưng nó cũng chính là thứ xoá cái +7. Hai: dưới config
production, `dense_text` và `doc_text` **top-20 bằng nhau (148)**, pool 150 vs 149.

Plumbing đã nối để backend mới thực sự **với tới** pipeline (bài học §9.1 — v3 không chạm nổi
codegen): `FinanceAgentConfig.dense_backend` → `agents/finance/retrieve.py` →
`aretrieve_table_ids` → `aget_retriever`/`get_retriever`/`_build_retriever`. Xác nhận:
`bge-m3 → tables_dense.npy`, `bge-m3-dense-text → tables_dense_dense_text.npy`, default arg
trúng đúng object cache của `"bge-m3"`. 22/22 test script pass.

### 10.6 Test retrieval full: `dense_text` không quy đổi, và sàn nhiễu lớn hơn hiệu ứng

Mọi số ở trên đo trên `pool.ranked`, thứ không submission nào chứa. Cái được submit đến từ
`service._evidence` — judge picks trước, rồi mọi primary statement trong shortlist — nên hai
tầng cuối (judge, primary expansion) đúng là chỗ một thay đổi quy đổi hoặc bốc hơi.

`scripts/gate_retrieval_full.py` chạy thẳng `aretrieve_table_ids`, hai arm khác nhau đúng một
tham số `dense_backend`, `frozen_fallback=False` để lỗi hiện ra thành lỗi chứ không bị frozen
cache lấp (fallback sẽ làm hai arm hội tụ về cùng id cache và che mất chính cái đang đo).
`--control` chạy `doc_text` hai lần để lấy sàn nhiễu của judge — không có nó thì delta treatment
và nhiễu run-to-run là cùng một con số.

| run | arm | u60 T-F2 | u60 top-3 | g94 T-F2 | g94 top-3 | DOCS F2 |
|---|---|---|---|---|---|---|
| A | `doc_text` | 0,304 | 23 | 0,355 | 52 | 0,939 / 0,751 |
| A | `dense_text` | **0,284** | 26 | 0,357 | 53 | 0,939 / 0,751 |
| B | `doc_text` | 0,302 | 26 | 0,359 | 54 | 0,939 / 0,751 |
| B | `doc_text` lần 2 | 0,303 | 26 | 0,359 | 54 | 0,939 / 0,751 |

**DOCS F2 giống hệt đến 3 chữ số ở cả bốn arm** — đúng như proxy 0/1012 dự đoán, giờ là đo trực
tiếp. Lý do: `_evidence` lấy *mọi* primary statement trong shortlist, nên `relevant_docs` do
**hard filter** quyết định, không do ranking.

**TABLES thì nằm trong nhiễu.** Cùng một `doc_text` ra top-3 23 (run A) rồi 26 (run B); hai arm
giống hệt trong cùng run B lệch 5/60 và 7/94 câu. Cộng hai set: `doc_text` 75 và 80, `dense_text`
79. Baseline tự dao động rộng hơn cái +4 của treatment. Ô duy nhất ra ngoài dải là u60 T-F2
0,284 vs 0,302–0,304, kéo theo T-R 0,867→0,804 — tức `dense_text` **mất recall** ở đó.

**Chốt: `dense_text` không quy đổi. Giữ default `bge-m3`.** Cái +7 trên thứ tự fused là thật và
đo được ba lần, nhưng reranker thay thứ tự đó, rồi judge chọn lại lần nữa; không tầng nào giữ nó.

Về câu hỏi "submission nhanh, bỏ codegen": `build_submission.py` hỗ trợ sẵn (answer 0.0,
`relevant_docs`/`relevant_tables` vẫn tính điểm), nhưng bảng trên cho thấy nó **không có tín
hiệu** cho thay đổi tầng này — DOCS đã 0,9268 và bất động, TABLES trần ~0,11 F2 và nhiễu ±3 câu.
Submission chỉ-retrieval chỉ hữu ích khi sửa **hard filter / candidate ở tầng document**.

### 10.7 Điều đáng chú ý hơn: cả stack mất dần độ chính xác ở đầu danh sách

Cùng 154 câu, cùng gold, đo top-3 qua từng tầng:

| tầng | top-3 (n=154) |
|---|---|
| fused (BM25 + dense + RRF + primary) | 96 |
| sau reranker | 89 |
| sau judge, tức cái được submit | 75–80 |

Mỗi tầng đổi độ chính xác đầu danh sách lấy recall trong cửa sổ. Với `codegen_max_tables=3`,
đầu danh sách *là* thứ codegen đọc. Đây là cùng một câu chuyện với taxonomy BTC (Numerical
Extraction 54,7%, Insufficient Evidence 34,7%): đòn bẩy không nằm ở thứ tự retrieval nữa.

### 10.8 `judge_thinking=True` bất khả dụng trên checkpoint hiện tại, và cho judge suy luận thì **tệ hơn**

`enable_thinking=True` không phải "tệ hơn" — nó không trả về gì. Đo ở tầng token
(`/tokenize` + `/v1/completions`, bỏ qua reasoning parser):

| `enable_thinking` | template render cuối | model sinh ra | API trả về |
|---|---|---|---|
| `False` | `<think>` `\n\n` `</think>` `\n\n` — **tự đóng** | `{"picks": [1]}`, 12 token | content sạch |
| `True` | `<think>` `\n` — **để mở** | `Thinking Process:\n\n1. **Analyze the Request:**…` | `content=None`, `reasoning_content=None`, `finish_reason=length` |

Qwen3.5-9B reason bằng văn xuôi thuần và **không bao giờ phát `</think>`**, nên parser của vLLM
buffer hết rồi trả về rỗng — ở 256, 1024, 4096 và 16384 token đều vậy, stream cũng 0 ký tự ở
cả hai trường. Đây là đúng failure mode đã ghi cho `codegen_thinking`, và nó là vấn đề của
sentinel, không phải của budget. Kết luận: `judge_thinking=True` sẽ làm judge trả 0 pick cho
**mọi** câu; không phải một arm đo được.

Nhưng câu hỏi thật vẫn đo được: cho judge suy luận *trong content* thay vì trong think block.
Arm `--arms reasoning` giữ `enable_thinking=False`, đổi đúng một dòng cuối của prompt từ
"chỉ in ra JSON, không giải thích" thành "viết ngắn gọn tối đa 5 dòng rồi in JSON ở dòng cuối",
và nâng `max_tokens` 256 → 1536 (không nâng thì rationale bị cắt trước JSON).

| arm | u60 T-F2 | u60 top-3 | u60 picks | g94 T-F2 | g94 top-3 | DOCS F2 |
|---|---|---|---|---|---|---|
| bare json | **0,358** | **48** | 3 | 0,325 | **77** | 0,939 / 0,751 |
| reason then json | 0,343 | 41 | 2 | 0,324 | 73 | 0,939 / 0,751 |
| *control: bare json ×2* | 0,359 / 0,359 | 48 / 48 | 2 | 0,325 / 0,324 | 76 / 76 | không đổi |

Sàn nhiễu của model này gần như bằng 0 — hai arm giống hệt lệch **1/60 và 2/94 câu**, T-F2 giống
đến 3 chữ số. Nên −10 top-3 gộp (124 → 114) là thật, cùng chiều trên cả hai set, 17 better vs
30 worse.

Cơ chế: trung vị picks 3 → 2 và T-R 0,892 → 0,827. Suy luận làm judge **kén hơn** rồi tự nói
mình ra khỏi lựa chọn đúng ("chỉ cần chọn [6] và [11]"). Với F2 (β=2) recall nặng gấp bốn
precision, nên kén hơn là sai hướng. `judge_thinking` giữ `False`, và lý do giờ có hai lớp:
flag bị hỏng trên checkpoint này, *và* biến thể chạy được cũng tệ hơn.

**Ghi chú về đổi model.** Server 8990 bị đổi checkpoint giữa các run trong ngày:
`Qwen3.5-9B-Opus-Distilled-v2` (§10.6) → `Qwen3.5-9B` (§10.8). Cùng code, cùng eval set, u60
top-3 26 → 47-48, g94 54 → 75-76. Phần do tôi đổi cấu trúc gate đo được là ~1 câu
(`--arms equiv`: gate mới vs đường `rag.service`, top-3 47 vs 46 và 75 vs 75), nên gần như toàn
bộ khoảng cách là do checkpoint. Không tái đo được vì checkpoint cũ không còn được serve.
Hệ quả: **mọi số tuyệt đối trong §10.6 thuộc về model cũ**; các kết luận ở đó là kết luận về
delta trong cùng run nên vẫn đứng, nhưng đừng so chéo §10.6 với §10.8.

`LLM_MODEL` mặc định (`Qwen/Qwen3-8B-Instruct`) **404** trên server này — mọi script phải set
biến môi trường, và không script nào tự phát hiện được điều đó ngoài việc gọi rồi hỏng.

### Artifact do §10.5-10.8 tạo (chưa commit)

```
scripts/probe_dense_membership.py    membership (free) + 2x2 fused/reranked (--reranker)
scripts/gate_retrieval_full.py       production path end-to-end, DOCS/TABLES F2,
                                     --arms backend|control|reasoning|equiv
src/finance_qa/modules/rag/judge.py       +Judge(max_tokens=...), default không đổi
src/finance_qa/agents/finance/config.py   +dense_backend
src/finance_qa/modules/rag/service.py     dense_backend threaded to _build_retriever
```
