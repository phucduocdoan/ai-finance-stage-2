# LESSONS — Rút gọn pattern để design storage & RAG

Trích xuất từ 12 câu đã giải (L1–L6). Đây là input trực tiếp cho bước design pipeline.

---

## 1. Metadata cần trên **report**

| Trường | Kiểu | Ví dụ | Ghi chú |
|---|---|---|---|
| `report_id` | str (PK) | `VJC_financial_statements_2018_separate` | file OCR bỏ đuôi |
| `ticker` | str | `VJC` | join với `code_stock.csv` |
| `year` | int | `2018` | năm báo cáo |
| `doc_type` | enum | `consolidated` / `separate` | trigger: "công ty mẹ" / "hợp nhất" / "riêng" |
| `industry` | enum | `non_financial` / `bank` / `securities` / `insurance` | quyết định schema BS/PL |
| `company_name` | str | `Công ty Cổ phần Hàng không Vietjet` | dùng cho name→ticker fallback |
| `n_pages`, `n_tables` | int | 48, 58 | sanity/statistics |

**Ticker resolution** là bước riêng — cần trước cả retrieval report:
- Case 1: có mã trong ngoặc `(VJC)` → trực tiếp.
- Case 2: chỉ có tên `"Ngân hàng TMCP Phương Đông"` → tra alias table (name/short_name → ticker).
- Case 3: tên gây nhầm `"Viễn thông FPT" → FOX ≠ FPT`. Cần **stopword-aware entity linking**, không phải substring.

---

## 2. Metadata cần trên **table**

Không đủ nếu chỉ có `(report_id, table_pos)`. Cần thêm:

| Trường | Kiểu | Ví dụ | Note |
|---|---|---|---|
| `statement_type` | enum | `balance_sheet` / `income_statement` / `cash_flow` / `note` / `equity_change` / `entity_info` | dựa vào tiêu đề + header + mã số |
| `statement_subtype` | enum | `bs_assets` / `bs_liabilities` / — | BS thường tách 2 bảng |
| `note_id` | str? | `29` (thuyết minh 29) | nếu là note, mã thuyết minh |
| `note_title` | str? | `"Doanh thu hoạt động tài chính"` | |
| `pivot_dim` | list[enum]? | `["by_customer_type"]` | note dạng ma trận |
| `period_columns` | list[period] | `["2018_annual", "2017_annual"]` hoặc `["31/12/2018_snapshot", "01/01/2018_snapshot"]` | tường minh từng cột |
| `has_ma_so_column` | bool | true cho BS/PL/CF | mã số = anchor stable |
| `has_thuyet_minh_column` | bool | true nếu có cột `Thuyết minh` | tham chiếu chéo note |

⇒ **Table type detection** là bước tiền xử lý bắt buộc, không chỉ save raw CSV.

---

## 3. Metadata cần trên **cell (row)**

Chuẩn hoá 1 row = 1 chỉ tiêu:

| Trường | Kiểu | Note |
|---|---|---|
| `ma_so` | str/null | `"10"`, `"270"`, `"01"` … chỉ tồn tại ở BS/PL/CF chính |
| `label_raw` | str | text OCR trực tiếp |
| `label_normalized` | str | lowercase, bỏ số thứ tự, bỏ dấu |
| `metric_canonical` | str | `revenue_net`, `net_income`, `total_assets`, `cash_equivalents`… — từ vựng chung |
| `metric_aliases` | list[str] | các cách viết khác của cùng metric |
| `level` | int | 0/1/2… cho row có indent (subitem) |
| `parent_ma_so` | str? | để build cây phân cấp |
| `sign` | enum | `positive` / `negative` (dấu ngoặc = âm) |
| `unit` | enum | `vnd` / `share` / `pct` / `time` | phần lớn `vnd` |

**Row indexing dual mode**:
- BS/PL/CF: index theo **`ma_so`** (stable, không phụ thuộc OCR).
- Note: index theo **`(note_id, label_normalized)` + `metric_canonical`**.

---

## 4. Metadata cần trên **cell (value)**

1 giá trị đơn:

| Trường | Kiểu | Note |
|---|---|---|
| `value` | float | đã parse số (bỏ `.` separator VN) |
| `period_type` | enum | `annual` (KQKD/CF) / `snapshot` (BS) / `year_end` / `movement_in_period` |
| `period_start` / `period_end` | date | `2018-01-01` – `2018-12-31` cho annual |
| `snapshot_date` | date? | `2018-12-31` cho BS |
| `currency` | str | `VND` mặc định |
| `column_semantics` | enum? | `cost` / `carrying` / `fair_value` / `recoverable` — cho note nhiều cột |
| `raw_text` | str | giữ text gốc để trace ("208.253.201.298") |

⇒ **Long format** `(report_id, table_pos, ma_so_or_note_row, metric_canonical, period_key, column_semantics, value)` là **shape lý tưởng cho RAG + pandas**.

---

## 5. Derived-metric dictionary (cần build)

Các "chỉ tiêu phái sinh" xuất hiện lặp lại — không có trong OCR nhưng LLM planner cần biết công thức:

| Tên | Công thức | Ghi chú |
|---|---|---|
| `net_profit_margin` | `LNST / DTT` | mã 60 / mã 10 (KQKD) |
| `de_ratio` | `NPT / VCSH` | mã 300 / mã 400 (BS) |
| `roa` | `LNST / TTS bình quân` | tổng tài sản đầu kỳ + cuối kỳ / 2 |
| `roe` | `LNST / VCSH bình quân` | |
| `interest_coverage` | `EBIT / Lãi vay` | EBIT = LN trước thuế + Lãi vay (KQKD VN) |
| `ebit` | `LN trước thuế + CP lãi vay` | mã 50 + mã 23 |
| `current_ratio` | `TSNH / Nợ NH` | mã 100 / mã 310 |
| `cash_equiv_over_assets` | `mã 112 / mã 270` | |
| `growth_pct` | `(V_t - V_{t-1}) / V_{t-1} × 100` | có thể âm |

⇒ Dictionary này **nhồi vào prompt** LLM planner khi câu hỏi có từ khoá phái sinh.

---

## 6. Question → pipeline mapping

| Category | # cell | # table | # report | LLM planner? | Ghi chú |
|---|---|---|---|---|---|
| L1 | 1 | 1 | 1 | No | Retrieve + read cell |
| L2 | 2 | 1–2 | 1 | Optional | Retrieve + formula |
| L3 | 2 | 1–2 | 1–2 | No | Formula = growth |
| L4 | 2 | 2 | 2 | No | Retrieve × 2 + diff |
| L5 | N | N | ≤N | No | Sum/avg over years |
| L6 | ≥3 | ≥2 | ≥2 | **Yes (bắt buộc)** | Multi-step planning |

⇒ **L1–L5 (~95% dataset) có thể giải bằng deterministic retrieval + formula**. Chỉ **L6 (~5%) cần LLM planner thực sự**. Đây là chỗ để tối ưu chi phí.

---

## 7. Unit conversion registry

| Từ khoá cuối câu | Đơn vị đích | Multiplier từ VND |
|---|---|---|
| `triệu đồng` | 1e6 | ÷ 1e6 |
| `tỷ đồng` / `tỷ` | 1e9 | ÷ 1e9 |
| `trăm tỷ` | 1e11 | ÷ 1e11 |
| `nghìn tỷ` | 1e12 | ÷ 1e12 |
| `đồng` | 1 | × 1 |
| `%` / `phần trăm` | pct | × 100 nếu ratio 0–1 |
| `điểm phần trăm` | pp | diff của 2 % |
| `lần` | ratio | × 1 (số lần) |
| `cổ phần` / `cổ phiếu` | shares | tuỳ context |
| `triệu cổ phiếu` | 1e6 shares | ÷ 1e6 |

⇒ Detection unit ở cuối câu là **rule đơn giản**, không cần LLM. Đưa vào post-processing.

---

## 8. Pitfalls đã quan sát (revised từ taxonomy doc)

1. **Ticker giả (FPT vs FOX)** — name resolution phải chính xác, không match substring.
2. **`công ty mẹ` = separate** — quy tắc rõ.
3. **Metric ambiguity**: "LN ròng" = mã 60 vs mã 61.
4. **Sub-metric trong note vs total trong BS**: "vay ngân hàng" ≠ "vay và nợ ngắn hạn" (BS mã 320).
5. **Flow vs stock**: "khấu hao trong năm" vs "khấu hao lũy kế".
6. **Bank/securities/insurance có schema riêng** — không dùng "Doanh thu thuần".
7. **Note dạng ma trận** (roll-forward TSCĐ/BĐSĐT): cell = (row_item, movement_type).
8. **Column semantics trong note**: giá gốc vs giá trị có thể thu hồi vs giá trị hợp lý.
9. **1 giá trị có thể xuất hiện ở nhiều bảng** (ví dụ tổng cổ phần ở table 15 & 16) ⇒ có rule ưu tiên.
10. **Answer type**: hầu hết `float VND-ish`; nhưng L3.2 argmax → `float year`, số lượng cổ phần → `float đếm`.

---

## 9. Next design decisions cần chốt (checkpoint tiếp theo)

1. **Storage layer**: giữ raw CSV nguyên trạng + xây **long-table parquet** phái sinh? Hay chỉ 1 lớp?
2. **Table type classifier**: dùng rule (dựa vào header + tiêu đề trên table) hay LLM?
3. **Metric canonicalization**: dictionary tay hay embedding-based?
4. **Note ID extraction**: parse từ context trước `<table>` block trong OCR.
5. **RAG retriever**: BM25 trên (statement_type + note_title + row_labels) hay dense embedding?
6. **LLM planner cho L6**: có nên hard-code 2 sub-patterns nested phổ biến hay để tự do?
7. **Submission csv_path**: đóng gói raw CSV (đơn giản) hay normalized long CSV (đúng semantics pandas_query)?
   - Ràng buộc từ đề: pandas_query phải chạy được → **normalized CSV** là bắt buộc.
