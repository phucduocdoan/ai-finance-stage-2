# DECISIONS — ViFinQA Stage 2

Sổ ghi quyết định (decision log). Ghi *đã quyết cái gì*, *vì sao*, và *hoãn cái gì cho tương lai*.
Cập nhật gần nhất: **2026-08-04**.

---

## 0. Bức tranh 1 dòng

Retrieval **không còn là bottleneck** (report-tier 100%, table all-hit@15 ~86.7%, recall@15 ~93.9%).
Điểm mất bây giờ nằm ở **bước answer/planner**. Vì vậy hướng đi là: lấy **baseline thật trên
leaderboard (n=1012)** trước, rồi mới tối ưu từng biến một, đo trên leaderboard chứ không đoán trên 15 câu.

---

## 1. Quyết định HIỆN TẠI — chạy "A" (đã chốt)

**A = chạy end-to-end cả 1,012 câu bằng pipeline hiện tại + planner đã vá, dựng ZIP nộp, lấy baseline.**

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

1. **Nhóm B — tách trường + re-embed dense** *(chưa duyệt, chưa bắt đầu)*
   - Tách `bm25_text` / `dense_text`; `dense_text` bỏ `section_title`, giữ `header_flat`.
   - Re-embed lại index dense.
   - Ràng buộc an toàn: backend dense thứ 2 **không được ghi đè** `tables_dense.npy`; coi
     `tables_metadata_v2.jsonl` + `data/indexes/*` là snapshot không dựng lại được.
   - Chỉ làm khi baseline cho thấy retrieval thực sự đáng đầu tư (hiện chưa thấy).

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
