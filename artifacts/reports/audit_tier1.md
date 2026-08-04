# Audit Tier 1 (rule-based fields)

- Rows: **146,246**
- Groups (report_id × doc_type): **1,965**

## A. Invariant violations (automated)

### Duplicate main statements per report
- Total groups with ≥1 duplicate: **3,474**

| statement_kind | Groups affected |
|---|---:|
| `cash_flow` | 1,415 |
| `bs::?` | 747 |
| `bs::bs_assets` | 568 |
| `income_statement` | 534 |
| `bs::bs_liabilities_equity` | 210 |

Sample 5 offenders:
- **AAA_financial_statements_2016_separate** / `separate` / `cash_flow` (×2)
  - pos=5 page=10 mau=`B 03 - DN` sub=`` hdr=`CHỈ TIÊU | Mã số | Năm 2016 | Năm 2015`
  - pos=6 page=11 mau=`B 03 - DN` sub=`` hdr=`CHỈ TIÊU | Mã số | Năm 2016 | Năm 2015`
- **AAA_financial_statements_2017_consolidated** / `consolidated` / `cash_flow` (×2)
  - pos=8 page=10 mau=`B 03 - DN` sub=`` hdr=`CHỈ TIÊU | Mã số | Năm 2017 | Năm 2016`
  - pos=9 page=11 mau=`B 03 - DN` sub=`` hdr=`III. LƯU CHUYỀN TIỀN TỪ HOẠT ĐỘNG TÀI CHÍNH`
- **AAA_financial_statements_2017_separate** / `separate` / `cash_flow` (×2)
  - pos=5 page=10 mau=`B 03 - DN` sub=`` hdr=`CHỈ TIÊU | Mã số | Năm 2017 | Năm 2016`
  - pos=6 page=11 mau=`B 03 - DN` sub=`` hdr=`CHỈ TIÊU | Mã số | Năm 2017 | Năm 2016`
- **AAA_financial_statements_2019_consolidated** / `consolidated` / `bs::bs_assets` (×2)
  - pos=5 page=8 mau=`B 01 - DN` sub=`bs_assets` hdr=`Mã số | TÀI SẢN | Thuyết minh | Số cuối năm | Số đầu năm`
  - pos=6 page=9 mau=`B 01 - DN` sub=`bs_assets` hdr=`Mã số | TÀI SẢN | Thuyết minh | Số cuối năm | Số đầu năm`
- **AAA_financial_statements_2019_consolidated** / `consolidated` / `income_statement` (×2)
  - pos=8 page=11 mau=`B 02 - DN` sub=`` hdr=`Mã số | CHỈ TIÊU | Thuyết minh | Năm nay | Năm trước`
  - pos=9 page=12 mau=`B 02 - DN` sub=`` hdr=`Mã số | CHỈ TIÊU | Thuyết minh | Năm nay | Năm trước`

### Inheritance consistency
- Total inherited tables: **19,246**
- Consistent with prior anchor: **19,246** (100.00%)
- Inconsistent: **0**

### note_id monotonicity
- Suspicious drops (>5) within a note block: **497**
- `AAA_financial_statements_2015_consolidated` pos=14 page=21 note=`5` prev=`11` inh=False title=`THÔNG TIN BỔ SUNG CHO CÁC KHOẢN MỤC TRÌNH BÀY TRÊN BẢNG CÂN ĐỐI KẾ TOÁN (TIẾP TH`
- `ACV_financial_statements_2024_consolidated` pos=14 page=25 note=`1` prev=`8` inh=False title=`Tiền và các khoản tương đương tiền`
- `ACV_financial_statements_2024_consolidated` pos=45 page=46 note=`1` prev=`20` inh=False title=`Doanh thu bán hàng và cung cấp dịch vụ`
- `ACV_financial_statements_2024_separate` pos=15 page=25 note=`1` prev=`7` inh=False title=`Tiền và các khoản tương đương tiền`
- `ACV_financial_statements_2024_separate` pos=47 page=45 note=`1` prev=`20` inh=False title=`Doanh thu bán hàng và cung cấp dịch vụ`

## B. Coverage

- Have `mau_tag`: **119,418** (81.7%)
- Have `note_id`: **103,989** (71.1%)
- Inherited `note_id`: **19,246** (13.2%)
- Have `has_ma_so_column`=True: **9,283** (6.3%)
- Empty `first_col_labels`: **3,862** (2.6%)
- Empty `context_page_text`: **1,981** (1.4%)

### statement_type distribution

| Key | Count | Pct |
|---|---:|---:|
| `note` | 118,042 | 80.7% |
| `unknown` | 14,900 | 10.2% |
| `balance_sheet` | 5,631 | 3.9% |
| `cash_flow` | 4,078 | 2.8% |
| `income_statement` | 2,764 | 1.9% |
| `entity_info` | 780 | 0.5% |
| `equity_change` | 51 | 0.0% |

### doc_type distribution

| Key | Count | Pct |
|---|---:|---:|
| `consolidated` | 74,932 | 51.2% |
| `separate` | 65,909 | 45.1% |
| `` | 5,405 | 3.7% |

## C. Failure patterns

### Top `unknown` header/first-col patterns (top 20)

| Key | Count | Pct |
|---|---:|---:|
| `hdr='Trang' | fcl0='Thông tin chung'` | 449 | 3.0% |
| `hdr='Từ 1 nămtrở xuống | Trên 1 nămđến 5 năm ' | fcl0='VND'` | 103 | 0.7% |
| `hdr='Mã số | CHỈ TIÊU | Thuyết minh | Năm 202' | fcl0='VND'` | 97 | 0.7% |
| `hdr='31/12/2025 | 01/01/2025' | fcl0='VND'` | 88 | 0.6% |
| `hdr='Năm 2023 | Năm 2022' | fcl0='VND'` | 86 | 0.6% |
| `hdr='NÔI DUNG | TRANG' | fcl0='BÁO CÁO CỦA BAN TỔNG GIÁM ĐỐC'` | 75 | 0.5% |
| `hdr='Trang' | fcl0='Báo cáo của Ban Tổng Giám đốc'` | 67 | 0.4% |
| `hdr='Năm 2025 | Năm 2024' | fcl0='VND'` | 65 | 0.4% |
| `hdr='31/12/2023 | 01/01/2023' | fcl0='VND'` | 61 | 0.4% |
| `hdr='31/12/2024 | 01/01/2024' | fcl0='VND'` | 60 | 0.4% |
| `hdr='Mã số | CHỈ TIÊU | Thuyết minh | Năm 201' | fcl0='VND'` | 59 | 0.4% |
| `hdr='Công ty kiểm toán | Công ty TNHH KPMG Vi' | fcl0=''` | 58 | 0.4% |
| `hdr='NỘI DUNG | TRANG' | fcl0='BÁO CÁO CỦA BAN TỔNG GIÁM ĐỐC'` | 55 | 0.4% |
| `hdr='Công ty TNHH KPMG' | fcl0='Việt Nam'` | 52 | 0.3% |
| `hdr='Năm 2024 | Năm 2023' | fcl0='VND'` | 52 | 0.3% |
| `hdr='31/12/2020 | 01/01/2020' | fcl0='VND'` | 51 | 0.3% |
| `hdr='31/12/2015 | 01/01/2015' | fcl0='VND'` | 49 | 0.3% |
| `hdr='Số cuối năm | Số đầu năm' | fcl0='Giá trị'` | 48 | 0.3% |
| `hdr='31/12/2016 | 01/01/2016' | fcl0='VND'` | 47 | 0.3% |
| `hdr='Năm 2020 | Năm 2019' | fcl0='VND'` | 46 | 0.3% |

### Empty `first_col_labels` — 3,862 tables

By statement_type:

| Key | Count | Pct |
|---|---:|---:|
| `note` | 2,904 | 75.2% |
| `unknown` | 831 | 21.5% |
| `cash_flow` | 65 | 1.7% |
| `balance_sheet` | 27 | 0.7% |
| `entity_info` | 27 | 0.7% |
| `income_statement` | 8 | 0.2% |

By doc_type:

| Key | Count | Pct |
|---|---:|---:|
| `consolidated` | 2,118 | 54.8% |
| `separate` | 1,617 | 41.9% |
| `` | 127 | 3.3% |

## D. Manual-verify sample

- Stratified (per doc_type × statement_type × 3): **63** tables → `audit_tier1_sample.jsonl`
- Inheritance spot-check: **30** tables (also in sample file, stratum=`INHERIT_SPOTCHECK`)

Open each `csv_path` and verify that:
- `statement_type` matches what the CSV actually is
- `note_id`/`note_title` matches the section heading on that page
- `label_col` picks the column containing text labels (not numbers)

Violations file: `audit_tier1_violations.jsonl`

---

## E. Findings sau audit (verified bằng raw data)

### E.1  "Duplicate main statement" — KHÔNG PHẢI BUG
- 3,474 (report_id, doc_type) groups có ≥2 bảng cùng main-statement type.
- **Nguyên nhân**: extractor cắt BS/IS/CF ra 2 bảng theo page break của PDF gốc.
  Ví dụ AAA_2016_sep: CF chia thành `table_5` (Section I - HĐKD, page 10) và
  `table_6` (Section II - HĐĐT + III - HĐTC, page 11).
- **Đã xác nhận**: `long_format.parquet` giữ đủ rows từ cả 2 phần (53 rows, 27 ở pos=5, 26 ở pos=6),
  metric "Lưu chuyển tiền thuần từ hoạt động đầu tư" tra được ở pos=6, `Mã số=30`, value=-792.7 tỷ.
- **Kết luận**: invariant "≤1 CF/BS/IS per report" bị **sai**. Long-format là source of truth cho lookup main-statement.
- **Action**: không cần fix — chỉ cần update mental model + docs.

### E.2  `statement_type = unknown` (14,900 tables, 10.2%) — CÓ THỂ CỨU

Phân loại thủ công top-20 patterns từ audit + regex-scan toàn bộ unknowns:

| Category | Count | Nhận xét |
|---|---:|---|
| TOC / cover / audit-report pages | ~1,007 | Đúng là unknown, giữ nguyên |
| Recoverable → BS (chứa TÀI SẢN/NGUỒN VỐN/31-12-YYYY) | **5,769** | mau_tag miss, nhưng header đủ tín hiệu |
| Recoverable → CF | 244 | LƯU CHUYỂN TIỀN trong header |
| Recoverable → IS | 691 | CHỈ TIÊU + Năm 20XX |
| Truly unknown (sub-tables trong note, không có tín hiệu) | ~7,189 | Cần Tầng 3 LLM |

**Impact**: ~6,700 tables (46% của unknowns) có thể phục hồi bằng header-content classifier fallback khi mau_tag empty.

**Fix**: thêm bước 2 trong `classify_statement`: nếu mau_tag=="" và header match TÀI SẢN/NGUỒN VỐN/LƯU CHUYỂN → tag ngay.

### E.3  `note_id` regex — có FALSE POSITIVE nghiêm trọng

Ví dụ AAA_2015_cons pos=13, page 21: `note_id=11`, `note_title="20. 10. 30. 25."` — regex ăn nhầm số Mã Số trong prose.

Ví dụ AAA_2015_cons pos=11..20: tất cả gán `note_id=5` với title = section header `"THÔNG TIN BỔ SUNG CHO CÁC KHOẢN MỤC..."`. Đây là **section-level heading**, không phải table-level thuyết minh. Các thuyết minh thực (5.1 Tiền, 5.2 Phải thu, ...) đang bị mất.

**Root cause**: regex `^\d+\.\s+TITLE` không phân biệt được:
- Section header (mức 1: `5. THÔNG TIN BỔ SUNG...` — quy mô chương)
- Note item (mức 2: `5.1 Tiền và tương đương tiền` — thuyết minh cụ thể)

497 "note_id drops" trong audit chủ yếu là:
- ACV bank-style: 2 section notes (I: chính sách, II: thuyết minh BCTT) restart numbering 1..N mỗi section → **hợp lệ, không phải bug**
- AAA-style: prose "1." "20." bị ăn nhầm → **là bug**

**Impact**: BM25/retrieval khi user hỏi "Tiền và các khoản tương đương tiền" sẽ match `context_page_text` được, nhưng `note_id` không dùng làm hard filter được reliable.

**Fix option A** (dễ): loại note_id nếu title chỉ toàn số / < 3 chữ / là ALL-CAPS section header.
**Fix option B** (đúng hơn): dùng regex 2 mức, ưu tiên `\d+\.\d+` (mức 2) trước `\d+\.` (mức 1).

### E.4  `has_ma_so_column` = 6.3% — QUÁ THẤP, đáng nghi
BS/IS/CF theo TT200 ĐỀU có cột "Mã số". Con số 6.3% phải xấp xỉ 8-10% (tương đương tổng main-statement 8.6%). Chênh 2.3% nghi ngờ OCR misspell.

Verify sau: `grep -i "^m[aã] s[oố0]"` header của các bảng BS/IS/CF không match hiện tại.

### E.5  `note_id_inherited` — HOÀN HẢO
19,246 tables kế thừa, **100% consistent** với anchor không kế thừa trước đó. State machine chạy đúng.

---

## F. Đề xuất hướng đi tiếp theo

**Trước khi làm Tầng 3 / bench retrieval — fix 2 issue đáng kể:**

1. **[Ưu tiên cao] Header-content fallback classifier** — giảm unknown từ 10.2% → ~5.5%.
   - Thêm hàm `classify_by_header(header_flat, first_col_labels)` chạy khi mau_tag empty.
   - Effort: ~30 phút, +6,700 bảng vào đúng type.

2. **[Ưu tiên trung] `note_id` sanitizer** — loại false positives.
   - Nếu title là ALL-CAPS section header (>=4 từ) → note_id = "".
   - Nếu title chỉ chứa số/dấu chấm → note_id = "".
   - Effort: ~15 phút.

**Không đáng làm ngay:**
- Sub-note numbering (5.1/5.2): dữ liệu OCR không nhất quán, ROI thấp. Để BM25 gánh.
- has_ma_so_column: bit này chỉ đóng vai trò debug, không dùng làm filter chính.
- Tầng 3 LLM enrich: dừng lại, chỉ chạy sau khi retrieval baseline có bench.

**Sau khi fix xong 2 issue trên** → regen v2 → bench retrieval trên 50 questions (stratified). Nếu recall > 80% → sang Tầng 3. Ngược lại, phân tích failure mode trước.