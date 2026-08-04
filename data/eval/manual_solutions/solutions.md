# Manual Solutions — 12 questions across L1–L6

Mục đích: mỗi câu trải qua 4 bước (locate report → locate table → locate cell → compute).
Từ đó rút ra metadata pattern cần cho storage/RAG.

Ký hiệu:
- `report_id`: tên file OCR bỏ `_extracted.txt`
- `table_pos`: theo `output/tables_index.jsonl`
- Giá trị gốc luôn là VND, đơn vị câu hỏi có thể là triệu / tỷ / trăm tỷ → cần **convert khi trả về**

---

## L1.1 — Câu #1 (single lookup, riêng lẻ)

### Câu hỏi
> Lãi tiền gửi năm 2018 của công ty mẹ CTCP Hàng không Vietjet (VJC) là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker: `VJC` → có sẵn ("Vietjet" / "VJC")
- Năm: `2018`
- Cụm "công ty mẹ" ⇒ **doc_type = separate** (bctc riêng)
- ⇒ `report_id = VJC_financial_statements_2018_separate`
- Path: `financial_statements/VJC/2018/VJC_financial_statements_2018_separate/*_extracted.txt`

**Metadata cần**: `(ticker, year, doc_type ∈ {consolidated, separate})`. Từ khoá kích hoạt `separate`: "công ty mẹ", "riêng", "bctc riêng".

### Step 2 — Locate table
- "Lãi tiền gửi" nằm ở **thuyết minh 29 — Doanh thu hoạt động tài chính** (KHÔNG phải KQKD chính, cũng KHÔNG phải BS).
- Table nằm ở page 44, header `2018VND | 2017VND`, 8 rows.
- Trong `tables_index.jsonl`: `table_pos = 50` (verified).

**Metadata cần**:
- `section_code`: `29` (thuyết minh 29) — chuẩn hoá theo Thông tư 200
- `section_title`: `"Doanh thu hoạt động tài chính"`
- `statement_type`: `notes` (không phải BS/PL/CF chính)
- Cấu trúc bảng: **item × year** (rows là các dòng chỉ tiêu, cols là các năm so sánh)

### Step 3 — Locate cell
- Row label: `"Lãi tiền gửi"` (exact match)
- Col: `2018 VND`
- Value = **208.253.201.298** (VND)

**Metadata cần**:
- Row indexing bằng **canonical metric name** + alias set (một chỉ tiêu có thể ghi khác nhau giữa các báo cáo).
- Col indexing bằng **period** = (year, period_type ∈ {annual, ytd, opening_balance...}). Ở đây period_type = `annual`, year = 2018.

### Step 4 — Extract + compute
- Giá trị: 208,253,201,298 VND
- Câu hỏi hỏi "triệu đồng" ⇒ chia 1e6 = **208,253.20 triệu đồng**
- `answer` (float) ≈ `208253.201298`

### Submission draft
```
report_id       = VJC_financial_statements_2018_separate
relevant_tables = ["VJC_financial_statements_2018_separate|50"]
csv_path        = data/VJC_financial_statements_2018_separate_table_50.csv
```

### Pattern quan sát
- **Single-cell lookup thuần** — không cần derive.
- Cần biết section/thuyết minh nào chứa chỉ tiêu ⇒ nhất định phải index **theo section chứ không chỉ theo table_pos**.
- OCR giữ dấu chấm thập phân kiểu VN (`208.253.201.298`) ⇒ khi chuẩn hoá cần parser `vi_number` (bỏ dấu `.`, giữ `,` là decimal; hoặc coi mọi `.` là separator vì số VND không có phần thập phân).
- Đơn vị câu hỏi ≠ đơn vị cell ⇒ **unit-conversion là bước bắt buộc, không phải optional**.

---

## L1.2 — Câu #100 (single lookup, thông tin doanh nghiệp)

### Câu hỏi
> Tổng số lượng cổ phần của Tập đoàn Bảo Việt (BVH) vào cuối năm 2018 là bao nhiêu cổ phần?

### Step 1 — Locate report
- Ticker: `BVH` (Bảo Việt, insurance)
- Năm: `2018`
- Không có "công ty mẹ" ⇒ default `consolidated`
- ⇒ `report_id = BVH_financial_statements_2018_consolidated`

### Step 2 — Locate table
- "Số lượng cổ phần" **không thuộc BS/PL/CF** mà nằm ở phần **Thuyết minh 1 - Thông tin doanh nghiệp / Cơ cấu vốn cổ phần**.
- Có **2 bảng có thể chứa đáp án**:
  - `table_pos = 15` (info doanh nghiệp) chứa dòng `"Số cổ phần đã đăng ký: 700.886.434"`
  - `table_pos = 16` (cơ cấu sở hữu) có row `"Tổng cộng: 700.886.434"`
- Cả 2 đều đúng — nhưng bảng 16 mới có "Tổng cộng" đúng khớp câu hỏi. Đây là ambiguity thật.

### Step 3 — Locate cell
- Table 16, cột `"Số lượng cổ phần nắm giữ"`, row `"Tổng cộng"` = **700.886.434**

### Step 4 — Compute
- Đơn vị = "cổ phần" (unit = 1) ⇒ answer = **700,886,434**

### Submission draft
```
report_id       = BVH_financial_statements_2018_consolidated
relevant_tables = ["BVH_financial_statements_2018_consolidated|16"]   # hoặc |15
```

### Pattern quan sát
- **Non-financial data**: cổ phần, cổ đông, ngành nghề, ban lãnh đạo → nằm ở thuyết minh "Thông tin doanh nghiệp" chứ không ở BS/PL/CF.
- **Multi-table ambiguity**: cùng 1 con số xuất hiện ở nhiều bảng ⇒ **cần chuẩn hoá quy ước "chọn bảng nào"** khi metric có nhiều nguồn (ưu tiên bảng có nhãn "Tổng cộng" / "Total").
- **Metric loại "point-in-time doanh nghiệp"**: period_type = `snapshot` at year-end, không phải `annual`.
- Insurance ticker (BVH) không có gì khác biệt ở loại câu này — nhưng khi sang KQKD sẽ khác schema (xem L4.2 với ngân hàng).

---

## L2.1 — Câu #674 (single-entity ratio, cần 2 cell)

### Câu hỏi
> Tỷ suất lợi nhuận ròng của HBC năm 2016 là bao nhiêu %?

### Step 1 — Locate report
- `HBC` × `2016` × consolidated (không có "công ty mẹ") ⇒ `HBC_financial_statements_2016_consolidated`

### Step 2 — Locate table
- Công thức: `Tỷ suất LN ròng = LNST / Doanh thu thuần`
- Cả 2 chỉ tiêu đều ở **1 bảng KQKD (Income Statement)** — thuận lợi.
- `table_pos = 8` (page 10, BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT).

**Metadata cần**:
- `statement_type = income_statement (KQKD)` — với `mã số` chuẩn theo TT200/TT202.
- Chỉ tiêu KQKD có **mã số cố định** (01, 10, 11, 20, 50, 60, 61…) ⇒ có thể index theo mã số thay vì string label ⇒ **robust hơn OCR biến dạng**.

### Step 3 — Locate cell(s)
| Chỉ tiêu | Mã số | Value (VND) |
|---|---|---|
| Doanh thu thuần | 10 | 10.766.205.824.099 |
| Lợi nhuận sau thuế TNDN | 60 | 568.013.202.926 |
| _(alt)_ LNST của cty mẹ | 61 | 567.045.986.811 |

### Step 4 — Compute
- `568,013,202,926 / 10,766,205,824,099 = 0.05276 = **5.28 %**`
- Nếu lấy mã 61: `567,045,986,811 / 10,766,205,824,099 = 5.27%`

### Pattern quan sát
- **KQKD có mã số chuẩn hoá** ⇒ metadata trong CSV nên giữ cột `mã số` (integer/string 2-3 ký tự). Đây là **primary key** ổn định nhất cho retrieval BS/PL/CF.
- **"Lợi nhuận ròng" là từ ambiguity**: có thể là mã 60 (LNST toàn công ty) hoặc mã 61 (của cty mẹ). Cần rule: default = mã 60 trừ khi câu hỏi nhấn mạnh "cổ đông công ty mẹ".
- **1 table, 2 cell, 1 phép chia** — pattern L2 đơn giản nhất. RAG chỉ cần retrieve **1 bảng KQKD**.

---

## L2.2 — Câu #656 (ratio cross-statement)

### Câu hỏi
> Tỷ trọng các khoản tương đương tiền trên tổng tài sản của CTCP Viễn thông FPT cuối năm 2024 là bao nhiêu %?

### Ticker resolution
- "CTCP Viễn thông FPT" = **FPT Telecom = FOX** (không phải FPT!). Đây là **name→ticker fallback** cần lookup từ `code_stock.csv`.
- ⇒ `report_id = FOX_financial_statements_2024_consolidated`

### Step 2 — Locate table
- **Tương đương tiền**: chi tiết ở thuyết minh "Tiền và các khoản tương đương tiền" (breakdown) HOẶC row `Mã số 112` trong BS.
- **Tổng tài sản**: `Mã số 270` trong BS.
- Cả 2 có thể chung 1 bảng BS (mã 112 và mã 270 đều nằm trong BS phần TÀI SẢN).

⇒ **1 BS table đủ**. Có thể fallback vào thuyết minh nếu BS chỉ có "Tiền và các khoản tương đương tiền" tổng gộp (mã 110), cần tách riêng "Các khoản tương đương tiền" (mã 112).

### Step 3 — Locate cell(s)
- BS row `112 - Các khoản tương đương tiền` (period = 31/12/2024)
- BS row `270 - TỔNG CỘNG TÀI SẢN` (period = 31/12/2024)

### Step 4 — Compute
- Ratio = `112 / 270 × 100%`
- Đơn vị output = %.

### Pattern quan sát
- **Name→ticker resolution CRITICAL**: "Viễn thông FPT" là FOX ≠ FPT. Nếu regex thấy chữ "FPT" là lấy sai. ⇒ Retrieval cần **entity linking đầy đủ** không chỉ pattern match.
- **BS có 2 phần** (TÀI SẢN / NGUỒN VỐN) → OCR thường tách thành **2 tables riêng** (như BVH ở trên có table 6/7 cho TÀI SẢN, table 8/9 cho NGUỒN VỐN). Câu hỏi cần cả 2 phần thì `relevant_tables` phải list cả 2.
- Ở đây may mắn 2 cell đều ở phần TÀI SẢN nên 1 bảng đủ.
- **Mã số BS**: 110 (Tiền và tương đương tiền), 111 (Tiền), 112 (Các khoản tương đương tiền), 270 (Tổng cộng tài sản). Đây là data điểm neo cho RAG.

---

## L3.1 — Câu #612 (temporal, growth %)

### Câu hỏi
> Tổng dư nợ vay ngắn hạn ngân hàng của công ty mẹ CTCP Thép Nam Kim (NKG) vào cuối năm 2021 tăng so với cuối năm 2020 là bao nhiêu phần trăm?

### Step 1 — Locate reports (2 reports)
- Ticker: `NKG`
- Doc type: `separate` ("công ty mẹ")
- Cần **2 báo cáo**: `NKG_financial_statements_2020_separate` và `NKG_financial_statements_2021_separate`
- **Hoặc**: 1 báo cáo 2021 có cột so sánh 31/12/2021 vs 1/1/2021 (đầu năm = 31/12/2020) ⇒ chỉ cần **1 report**.

⇒ Quy tắc heuristic: **Nếu 2 năm cạnh nhau (Y và Y-1), báo cáo năm Y thường có cột so sánh** → chỉ dùng report Y. Nếu 2 năm cách xa (Y1, Y1+3), phải mở nhiều report.

### Step 2 — Locate table
- "Vay ngắn hạn ngân hàng" nằm ở **thuyết minh "Vay và nợ thuê tài chính ngắn hạn"**, không phải row tổng trong BS.
- BS row `mã 320 - Vay và nợ thuê tài chính ngắn hạn` cho tổng vay ngắn hạn (bao gồm cả trái phiếu, thuê TC). Nhưng câu hỏi hỏi cụ thể "vay ngân hàng" ⇒ phải vào **thuyết minh** để lấy sub-item.

⇒ 2 possible tables: (a) BS table với mã 320, (b) note table breakdown vay ngắn hạn với sub-rows "Vay ngân hàng thương mại".

### Step 3 — Locate cell(s)
- Note "Vay ngắn hạn" → sub-row "Vay ngân hàng" (hoặc "Vay các ngân hàng thương mại") × cột `31/12/2021` và `31/12/2020` (hoặc `1/1/2021`).

### Step 4 — Compute
- `growth% = (V2021 - V2020) / V2020 × 100`

### Pattern quan sát
- **Temporal comparison** có thể giải bằng **1 report năm cuối** (có cột đối chứng năm trước) HOẶC **nhiều report**. Cả 2 đều valid. Chọn cách 1 report → gọn.
- **Sub-metric ambiguity**: "vay ngắn hạn ngân hàng" là **subset của** BS mã 320. Không dùng cell tổng được. Cần **retrieval xuống note table**.
- ⇒ Cần cột metadata `metric_scope`: `total` vs `sub_item` (breakdown).
- **Sign convention của growth**: nếu V2021 < V2020 (giảm), câu hỏi có thể vẫn hỏi "tăng bao nhiêu %" ⇒ answer sẽ âm (dấu −).

---

## L3.2 — Câu #904 (temporal argmax over 3 years)

### Câu hỏi
> Năm nào trong các năm 2020, 2023 và 2024 có tổng doanh thu hoạt động tài chính lớn nhất đối với CTCP Tập đoàn Hà Đô?

### Ticker resolution
- "Tập đoàn Hà Đô" = `HDG` (name→ticker fallback)

### Step 1 — Locate reports (3 disjoint years)
- 3 năm không liên tiếp (2020, 2023, 2024) ⇒ phải mở **3 báo cáo**:
  - `HDG_financial_statements_2020_consolidated`
  - `HDG_financial_statements_2023_consolidated`
  - `HDG_financial_statements_2024_consolidated`
- (báo cáo 2024 có cột so sánh 2023 ⇒ có thể gộp → 2 report thay vì 3, nhưng an toàn thì lấy 3)

### Step 2 — Locate table
- "Doanh thu hoạt động tài chính" = mã KQKD `21`. **1 table KQKD / report**.

### Step 3 — Locate cell(s)
- 3 giá trị: KQKD mã 21 tại 3 năm.

### Step 4 — Compute
- `argmax(V2020, V2023, V2024)` → answer = năm (integer)

### Pattern quan sát
- **Answer là năm (int)** ⇒ không phải VND. Submission format vẫn dùng `answer: float` ⇒ answer = `2024.0` chẳng hạn.
- **Multi-report retrieval**: mỗi năm là 1 (ticker, year) key riêng ⇒ storage phải index theo (ticker, year, statement_type, metric).
- **argmax là logic phổ biến** ⇒ pandas query kiểu `df.loc[df['revenue'].idxmax(), 'year']`.

---

## L4.1 — Câu #793 (cross-company, cùng loại, snapshot)

### Câu hỏi
> Cuối năm 2025, số lượng cổ phiếu phổ thông đang lưu hành của GEE chênh lệch bao nhiêu so với GEX (đơn vị triệu cổ phiếu)?

### Step 1 — Locate reports (2 companies × 1 year)
- 2 tickers: `GEE`, `GEX`
- Năm: 2025
- ⇒ `GEE_financial_statements_2025_consolidated` + `GEX_financial_statements_2025_consolidated`

### Step 2 — Locate table
- "Số lượng cổ phiếu phổ thông đang lưu hành" thường nằm ở **thuyết minh "Vốn chủ sở hữu / Vốn cổ phần"** — không phải BS/PL/CF chính. Row label: `"Cổ phiếu phổ thông đang lưu hành"` hoặc `"Số cổ phần lưu hành"`.

### Step 3 — Locate cell(s)
- 2 giá trị: GEE.số_CP_phổ_thông_lưu_hành, GEX.số_CP_phổ_thông_lưu_hành (cùng thời điểm 31/12/2025).

### Step 4 — Compute
- `answer = |GEE - GEX|` hoặc `GEE - GEX` (câu hỏi mở, thường không dấu)
- Convert sang triệu cổ phiếu (÷ 1e6)

### Pattern quan sát
- **Cross-company** = 2 reports độc lập, cùng câu hỏi lặp lại → **join theo metric**.
- ⇒ Storage lý tưởng: **long format** `(ticker, year, doc_type, statement_type, metric_code, metric_name, period, value)` ⇒ 1 query filter thay vì 2 subselect.
- **Đơn vị output triệu cổ phiếu** ≠ đơn vị source (số cổ phần tuyệt đối) ⇒ chia 1e6.

---

## L4.2 — Câu #751 (cross-company, ngân hàng, sub-item)

### Câu hỏi
> Dư nợ cho vay cá nhân cuối năm 2023 của Ngân hàng TMCP Phương Đông chênh lệch bao nhiêu triệu đồng so với Ngân hàng TMCP Nam Á?

### Ticker resolution
- Phương Đông = `OCB`, Nam Á = `NAB` (name → ticker; **KHÔNG** có mã trong câu hỏi ⇒ bắt buộc fallback tên).

### Step 1 — Locate reports (2 banks × 2023)
- `OCB_financial_statements_2023_consolidated` + `NAB_financial_statements_2023_consolidated`
- Cả 2 là **ngân hàng** ⇒ schema hoàn toàn khác doanh nghiệp phi tài chính.

### Step 2 — Locate table (bank-specific)
- **Bank BS**: có "Cho vay khách hàng" (mã hoặc row-name), thuyết minh chi tiết chia theo:
  - Phân loại theo đối tượng: **cá nhân**, doanh nghiệp, hộ kinh doanh...
  - Phân loại theo kỳ hạn / theo ngành / theo TSBĐ...
- Câu hỏi hỏi "cho vay cá nhân" ⇒ retrieve **thuyết minh "Cho vay khách hàng - Phân tích theo đối tượng khách hàng"**.

### Step 3 — Locate cell(s)
- OCB.note_CVKH.row["Cho vay cá nhân"].col["31/12/2023"]
- NAB.note_CVKH.row["Cho vay cá nhân"].col["31/12/2023"]

### Step 4 — Compute
- `diff = OCB - NAB` (triệu đồng — convert từ VND)

### Pattern quan sát
- **Bank schema HOÀN TOÀN KHÁC**: không có "Doanh thu thuần", "Giá vốn". Thay vào là "Thu nhập lãi thuần", "Cho vay khách hàng", "Tiền gửi khách hàng"...
- ⇒ **`statement_type` phải phân theo industry**: `non_financial_bs / pl / cf` vs `bank_bs / pl / cf` vs `securities_bs / pl` vs `insurance_bs / pl`.
- **Note table của ngân hàng** có nhiều pivot (theo đối tượng / kỳ hạn / chất lượng nợ). RAG phải xác định **pivot dimension** trước khi tìm cell.
- ⇒ Metadata bổ sung: `pivot_dim` = `["by_customer_type", "by_tenor", "by_quality"...]`.

---

## L5.1 — Câu #937 (multi-year average, bank)

### Câu hỏi
> Tính trung bình cộng giá trị chứng khoán nợ vào ngày 31 tháng 12 của các năm 2017, 2018, 2019 và 2020 của Ngân hàng TMCP Công thương Việt Nam (CTG) là bao nhiêu triệu đồng?

### Step 1 — Locate reports (4 years)
- `CTG` × 4 năm (2017–2020) — thường lấy report 2018 (có 2017,2018), 2020 (có 2019, 2020) ⇒ **2 reports**.
- Hoặc 4 reports riêng.

### Step 2 — Locate table
- "Chứng khoán nợ" = một dạng chứng khoán đầu tư của ngân hàng, thuộc thuyết minh "Chứng khoán đầu tư" hoặc "Chứng khoán kinh doanh". Row `"Chứng khoán nợ"` (đối lập với "Chứng khoán vốn").

### Step 3 — Locate cell(s)
- 4 giá trị tại 4 mốc 31/12.

### Step 4 — Compute
- `avg = (V17 + V18 + V19 + V20) / 4`, convert → triệu đồng.

### Pattern quan sát
- **Multi-year average** thường là **snapshot** (giá trị điểm cuối kỳ) ⇒ period_type = `year_end`.
- **Chuỗi thời gian dài** ⇒ RAG phải retrieve N cells cùng metric qua N năm. Storage long format là **must-have**.
- Cần **matching năm–report smart**: report 2018 gộp được (2017, 2018), report 2020 gộp được (2019, 2020) ⇒ chỉ 2 report thay vì 4.

---

## L5.2 — Câu #924 (multi-year sum, separate)

### Câu hỏi
> Tổng chi phí khấu hao bất động sản đầu tư của DXG ở mức công ty mẹ trong giai đoạn từ 2021 đến 2025 là bao nhiêu tỷ đồng?

### Step 1 — Locate reports
- `DXG` × 5 năm (2021–2025) × `separate` ("công ty mẹ").
- 5 báo cáo (report 2022 gộp 2021+2022, report 2024 gộp 2023+2024, report 2025 gộp 2024+2025) ⇒ có thể chỉ cần **3 reports** (2022, 2024, 2025).

### Step 2 — Locate table
- "Chi phí khấu hao BĐSĐT": nằm ở thuyết minh "Bất động sản đầu tư" với các cột `Nguyên giá / Khấu hao lũy kế / Giá trị còn lại` × biến động trong năm.
- **Chi phí khấu hao trong năm** = phần "Khấu hao trong năm" của bảng biến động BĐSĐT (không phải khấu hao lũy kế cuối kỳ!).

### Step 3 — Locate cell(s)
- 5 giá trị "Khấu hao trong năm" × 5 năm.

### Step 4 — Compute
- `sum = V21 + V22 + V23 + V24 + V25`, convert → tỷ đồng (÷ 1e9).

### Pattern quan sát
- **Flow vs stock**: "Khấu hao trong năm" = flow (period), khác với "Khấu hao lũy kế" = stock (snapshot). RAG phải phân biệt.
- **BĐSĐT (investment property) note** có schema kép: matrix `(item: đất, nhà cửa, …) × (movement: opening/addition/disposal/depreciation/closing)`. Extract cell = 2D address.
- ⇒ Metadata cell: `(row_label, movement_type)` cho note dạng ma trận roll-forward.

---

## L6.1 — Câu #440 (nested: argmax → dependent metric)

### Câu hỏi
> Trong giai đoạn 2021–2024 của DIG, năm mà có tỷ lệ nợ phải trả trên vốn chủ sở hữu cao nhất, lợi nhuận trước lãi vay và thuế trong năm đó gấp bao nhiêu lần chi phí lãi vay?

### Bước phân tích (nested logic)
1. **Bước 1 (dependency)**: với mỗi năm y ∈ {2021,22,23,24}, tính `D/E(y) = Nợ phải trả(y) / VCSH(y)` (BS mã 300 / mã 400)
2. **Bước 2**: `y* = argmax D/E`
3. **Bước 3**: tính `EBIT(y*) = LN trước thuế + Chi phí lãi vay` (KQKD mã 50 + mã 23), `Interest(y*) = mã 23` (chi phí lãi vay)
4. **Bước 4**: `ratio = EBIT(y*) / Interest(y*)` (Interest Coverage)

### Reports cần
- DIG × 4 năm × consolidated ⇒ 2 reports (2022 và 2024).

### Tables cần
- BS × 4 năm (mã 300, 400) — 4 cell
- KQKD × 1 năm (y*) — 2 cell (mã 50, mã 23)

### Pattern quan sát
- **L6 = pipeline 2 tầng**: kết quả bước 1 quyết định bước 2. **Không thể query 1 lần**.
- ⇒ LLM planner phải **chia câu thành sub-questions**, retrieve từng bước, cache kết quả trung gian.
- **Định nghĩa "EBIT"** = LN trước thuế + Chi phí lãi vay (do KQKD VN không có dòng EBIT riêng). Cần **derived-metric dictionary**.

---

## L6.2 — Câu #501 (nested 3-tier)

### Câu hỏi
> Trong các năm 2015, 2020, 2021 và 2023, năm nào có tổng giá gốc nợ phải thu quá hạn của công ty mẹ CTCP Đường Quảng Ngãi (QNS) lớn nhất trong số các năm mà giá gốc khoản đầu tư của QNS vào Công ty TNHH MTV Thương mại Thành Phát đạt mức cao nhất?

### Phân tích (parse cẩn thận)
- Set A = {2015, 2020, 2021, 2023}
- Với mỗi y ∈ A: lấy giá gốc khoản đầu tư QNS → Thành Phát → giá trị M_investment(y).
- max_investment = max(M_investment(y) for y in A) (có thể có nhiều năm đạt max cùng lúc)
- Set B = { y ∈ A | M_investment(y) == max_investment }
- Với mỗi y ∈ B, lấy tổng giá gốc "nợ phải thu quá hạn" M_overdue(y).
- Answer = argmax(M_overdue over B).

### Reports (QNS × 4 năm × separate)
- 3-4 reports.

### Tables (per report)
- **Note "Đầu tư vào công ty con"** (giá gốc khoản đầu tư từng công ty con) — row = "Công ty TNHH MTV Thương mại Thành Phát".
- **Note "Phải thu ngắn hạn của khách hàng" hoặc "Nợ phải thu khó đòi / quá hạn"** — bảng phân tích tuổi nợ, cột "Giá gốc" (Cost) vs "Giá trị có thể thu hồi".

### Pattern quan sát
- **3-tier nesting**: filter → filter within filter → argmax → answer.
- **Named entity ở note level**: "Công ty TNHH MTV Thương mại Thành Phát" là 1 row cụ thể trong bảng danh sách công ty con. ⇒ RAG cần retrieve **subsidiary/related-party name** — không chỉ chỉ tiêu tài chính.
- **"Giá gốc"** (Cost/Historical value) là chuyên biệt vs "Giá trị có thể thu hồi" (Recoverable) — 2 cột riêng trong bảng age-of-receivables.
- ⇒ Metadata: **column semantics** phải rõ (cost / carrying_value / fair_value / recoverable_amount).
- Câu này siêu khó → nếu LLM planner sai 1 bước thì answer sai. Đây là **tail case**, chỉ chiếm <5% dataset.


