# Manual Solutions Batch 2 — 12 questions across L1–L6

Mục đích: mở rộng gold eval set từ 12 → 24 câu, mỗi câu trải qua 4 bước (locate report → locate table → locate cell → compute).

Ký hiệu:
- `report_id`: tên file OCR bỏ `_extracted.txt`
- `table_pos`: theo `output/tables_index.jsonl`
- Giá trị gốc luôn là VND, đơn vị câu hỏi có thể là triệu / tỷ / trăm tỷ / nghìn tỷ → cần **convert khi trả về**

Tickers mới trong batch 2 (không trùng batch 1): STB, SHB, VIB, FTS, NLG, MCH, MBB, ABB, HDB, SNZ, KBC, OCB

---

## L1.1 — Câu #44 (single lookup, bank BS)

### Câu hỏi
> Tổng tài sản hợp nhất của Ngân hàng TMCP Sài Gòn Thương Tín (STB) tại ngày 31/12/2016 là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker: `STB` (Sacombank — ngân hàng)
- Năm: `2016`
- Không có "công ty mẹ" ⇒ `doc_type = consolidated`
- ⇒ `report_id = STB_financial_statements_2016_consolidated`
- Industry: `bank` → schema BS khác non-financial (không có mã số chuẩn TT200)

**Metadata cần**: `(ticker, year, doc_type, industry=bank)`. Với bank, không có mã số TT200 → cần index bằng label text.

### Step 2 — Locate table
- "Tổng tài sản" nằm ở **Bảng cân đối kế toán (Balance Sheet) — phần tài sản**.
- Với ngân hàng, BS thường tách riêng phần Assets (bảng đầu) và phần Liabilities+Equity (bảng sau).
- Trong `tables_index.jsonl`: `table_pos = 4` (phần tài sản của STB 2016 consolidated).

**Metadata cần**:
- `statement_type = balance_sheet`
- `statement_subtype = bs_assets`
- `period_columns = ["31/12/2016_snapshot", "01/01/2016_snapshot"]`
- Ngân hàng: dùng label text làm anchor vì không có mã số

### Step 3 — Locate cell
- Row label: `"TỔNG TÀI SẢN"` (dòng cuối cùng của bảng tài sản)
- Col: `Số cuối năm` / `31/12/2016`
- Value = **332.023.043** (triệu VND — đơn vị bảng là "triệu đồng")

**Metadata cần**:
- `unit = trieu_vnd` (đơn vị bảng đã là triệu, khác non-financial là VND)
- `period_type = snapshot`
- `snapshot_date = 2016-12-31`

### Step 4 — Extract + compute
- Giá trị: 332,023,043 (triệu VND) — đơn vị bảng đã là triệu
- Câu hỏi hỏi "triệu đồng" ⇒ không cần convert
- **Đáp án = 332,023,043 triệu đồng**

### Submission draft
```
report_id       = STB_financial_statements_2016_consolidated
relevant_tables = ["STB_financial_statements_2016_consolidated|4"]
csv_path        = data/STB_financial_statements_2016_consolidated_table_4.csv
```

### Pattern quan sát
- **Bank BS có đơn vị bảng là "triệu đồng"** (không phải VND đơn lẻ như non-financial) → unit conversion khác.
- BS ngân hàng không có mã số → index bằng label text; cần fuzzy match cho OCR noise.
- "Tổng tài sản" ở bank = dòng cuối cùng của bảng assets, thường có chữ "TỔNG" viết hoa.

---

## L1.2 — Câu #17 (single lookup, bank income statement)

### Câu hỏi
> Lãi thuần từ hoạt động dịch vụ của Ngân hàng TMCP Sài Gòn-Hà Nội (SHB) trong năm 2018 là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker: `SHB` (Ngân hàng TMCP Sài Gòn-Hà Nội)
- Năm: `2018`
- Không có "công ty mẹ" ⇒ `doc_type = consolidated`
- ⇒ `report_id = SHB_financial_statements_2018_consolidated`
- Industry: `bank`

### Step 2 — Locate table
- "Lãi thuần từ hoạt động dịch vụ" nằm ở **Báo cáo kết quả hoạt động kinh doanh (bank schema)**.
- Với ngân hàng, KQKD bao gồm: Thu nhập lãi thuần / Lãi thuần dịch vụ / Lãi ngoại hối / Lãi chứng khoán...
- Trong `tables_index.jsonl`: `table_pos = 5` (KQKD của SHB 2018 consolidated).

**Metadata cần**:
- `statement_type = income_statement`
- `period_columns = ["2018_annual", "2017_annual"]`
- Bank income: không có "Doanh thu thuần" (mã 10) — metric chính là "Thu nhập lãi thuần"

### Step 3 — Locate cell
- Row label: `"II. Lãi thuần từ hoạt động dịch vụ"` (có thể có thuyết minh 27)
- Col: năm nay / `2018`
- Value = **713.942** (triệu VND)

**Metadata cần**:
- `metric_canonical = fee_income_net`
- `period_type = annual`

### Step 4 — Extract + compute
- Giá trị: 713,942 (triệu VND) — đơn vị bảng là triệu
- Câu hỏi hỏi "triệu đồng" ⇒ không cần convert
- **Đáp án = 713,942 triệu đồng**

### Submission draft
```
report_id       = SHB_financial_statements_2018_consolidated
relevant_tables = ["SHB_financial_statements_2018_consolidated|5"]
csv_path        = data/SHB_financial_statements_2018_consolidated_table_5.csv
```

### Pattern quan sát
- **Bank income statement có schema hoàn toàn khác non-financial** — không có mã số TT200, không có "Doanh thu thuần".
- "Lãi thuần dịch vụ" = Net fee and commission income; cần canonical mapping riêng cho bank.
- Thuyết minh số (27) trong cột "Thuyết minh" là reference sang note — không cần truy vào note để lấy tổng, chỉ cần đọc cell này.

---

## L2.1 — Câu #40 (bank LNST lookup)

### Câu hỏi
> Lợi nhuận sau thuế của Ngân hàng TMCP Quốc Tế Việt Nam (VIB) trong năm 2020 là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker: `VIB` (VIB — ngân hàng)
- Năm: `2020`
- `doc_type = consolidated`
- ⇒ `report_id = VIB_financial_statements_2020_consolidated`
- Industry: `bank`

### Step 2 — Locate table
- "Lợi nhuận sau thuế" của bank nằm ở phần tiếp theo của KQKD (bảng 2 vì bank KQKD thường tách 2 bảng).
- VIB 2020: bảng 1 KQKD ở `table_pos = 9`, bảng 2 ở `table_pos = 10`.
- LNST nằm ở bảng 2 — `table_pos = 10`.

**Metadata cần**:
- `statement_type = income_statement`
- Bank KQKD VIB split thành 2 table; row "Lợi nhuận sau thuế" (XIII) ở table thứ 2.

### Step 3 — Locate cell
- Row label: `"XIII. Lợi nhuận sau thuế"` (row cuối bảng 2)
- Col: `Năm nay` / 2020
- Value = **4.642.334** (triệu VND)

### Step 4 — Extract + compute
- Giá trị: 4,642,334 (triệu VND)
- Câu hỏi hỏi "triệu đồng" ⇒ không cần convert
- **Đáp án = 4,642,334 triệu đồng**

### Submission draft
```
report_id       = VIB_financial_statements_2020_consolidated
relevant_tables = ["VIB_financial_statements_2020_consolidated|10"]
csv_path        = data/VIB_financial_statements_2020_consolidated_table_10.csv
```

### Pattern quan sát
- **Bank KQKD split thành nhiều bảng** — một số ngân hàng (VIB) tách KQKD thành 2 pages/tables. LNST ở cuối bảng cuối.
- Cần join hai bảng khi cần context đầy đủ; nhưng để lookup LNST chỉ cần bảng cuối.
- Label "XIII" là row identifier dạng La Mã — cần normalize.

---

## L2.2 — Câu #55 (securities company BS lookup)

### Câu hỏi
> Vốn cổ phần của FTS cuối năm 2020 là bao nhiêu nghìn tỷ đồng?

### Step 1 — Locate report
- Ticker: `FTS` (CTCP Chứng khoán FPT — securities)
- Năm: `2020`
- FTS là công ty chứng khoán → **report_id KHÔNG có suffix doc_type** (không phân consolidated/separate)
- ⇒ `report_id = FTS_financial_statements_2020`
- Industry: `securities`

**Metadata cần**: Securities companies dùng report_id không có `_consolidated` hay `_separate` suffix — khác bank và non-financial.

### Step 2 — Locate table
- "Vốn cổ phần" (charter capital) nằm ở **Bảng cân đối kế toán — phần VCSH (mã 411)**.
- FTS dùng mẫu báo cáo theo Thông tư 210/2014 (dành cho CTCK), có mã số khác TT200.
- Trong `tables_index.jsonl`: `table_pos = 11` (BS equity side của FTS 2020).
- Bảng 10 là phần tài sản (A+B), bảng 11 là phần nợ+VCSH (C+D).

### Step 3 — Locate cell
- Row label: `"1.1. Vốn góp của chủ sở hữu"` → `"a. Cổ phiếu phổ thông có quyền biểu quyết"` (mã 411.1a)
- Đây là **vốn cổ phần thực góp = mệnh giá × số cổ phiếu** (không gồm thặng dư vốn)
- Col: `Số cuối năm`
- Value = **1.322.673.490.000** (VND)

**Metadata cần**:
- `metric_canonical = share_capital` (vốn cổ phần = charter capital)
- Phân biệt: mã 411.1 (tổng vốn góp) = 1,322,673,490,000; mã 411 (vốn đầu tư chủ sở hữu) = 1,404,111,445,700 (gồm thặng dư)
- Câu hỏi "vốn cổ phần" → mã 411.1a (par value shares)

### Step 4 — Extract + compute
- Giá trị: 1,322,673,490,000 VND
- Câu hỏi hỏi "nghìn tỷ đồng" ⇒ chia 1e12 = 1,322,673,490,000 / 1,000,000,000,000 = **1.3227 nghìn tỷ đồng**

### Submission draft
```
report_id       = FTS_financial_statements_2020
relevant_tables = ["FTS_financial_statements_2020|11"]
csv_path        = data/FTS_financial_statements_2020_table_11.csv
```

### Pattern quan sát
- **Securities company report_id không có doc_type suffix** — cần handle đặc biệt trong ticker → report_id mapping.
- Mã 411.1a (cổ phiếu phổ thông) ≠ mã 411 (tổng vốn đầu tư chủ sở hữu gồm thặng dư) → "vốn cổ phần" thường hỏi về 411.1a.
- FTS theo Thông tư 210 — mã số khác TT200; cần schema riêng cho CTCK.

---

## L3.1 — Câu #605 (growth rate, 2 years, 1 report)

### Câu hỏi
> Tỷ lệ tăng trưởng khoản người mua trả tiền trước ngắn hạn của Công ty CP Đầu tư Nam Long (NLG) từ cuối năm 2023 đến cuối năm 2024 là bao nhiêu %?

### Step 1 — Locate report
- Ticker: `NLG` (Nam Long — bất động sản)
- Năm: `2024` (report 2024 chứa cả số cuối 2024 và đầu 2024 = cuối 2023)
- `doc_type = consolidated`
- ⇒ `report_id = NLG_financial_statements_2024_consolidated`

**Lưu ý**: 1 report duy nhất đủ vì BS 2024 có cột "Số đầu năm" = số cuối 2023.

### Step 2 — Locate table
- "Người mua trả tiền trước ngắn hạn" (mã 312) nằm ở **Bảng CĐKT phần Nguồn vốn — Nợ ngắn hạn**.
- Trong `tables_index.jsonl`: `table_pos = 7` (NLG 2024 BS equity+liabilities side).

**Metadata cần**:
- `ma_so = 312`
- `statement_type = balance_sheet`

### Step 3 — Locate cell
- Row: `"2. Người mua trả tiền trước ngắn hạn"` (mã 312)
- Col cuối năm 2024 = **3.023.679.812.978** VND
- Col đầu năm (= cuối 2023) = **3.814.598.243.120** VND

Cross-verify: NLG 2023 report (`table_pos = 8`) xác nhận cuối 2023 = 3.814.598.243.120 VND.

### Step 4 — Extract + compute
- V_2024 = 3,023,679,812,978 VND
- V_2023 = 3,814,598,243,120 VND
- Growth = (V_2024 - V_2023) / V_2023 × 100%
- = (3,023,679,812,978 - 3,814,598,243,120) / 3,814,598,243,120 × 100%
- = -790,918,430,142 / 3,814,598,243,120 × 100%
- = **-20.73%**

### Submission draft
```
report_id       = NLG_financial_statements_2024_consolidated
relevant_tables = ["NLG_financial_statements_2024_consolidated|7"]
csv_path        = data/NLG_financial_statements_2024_consolidated_table_7.csv
```

### Pattern quan sát
- **Growth 2 năm liền tiếp = 1 bảng** — BS năm T có cột "Số đầu năm" = cuối năm T-1, không cần mở report T-1.
- Nếu 2 năm không liền tiếp (ví dụ 2019 → 2023) thì phải load 2 report.
- `mã 312` là stable anchor cho "Người mua trả tiền trước ngắn hạn" (Thông tư 200).

---

## L3.2 — Câu #582 (growth rate, 2 non-consecutive years, 2 reports)

### Câu hỏi
> Tăng trưởng khoản vay ngắn hạn của MCH từ cuối năm 2021 đến cuối năm 2023 là bao nhiêu %?

### Step 1 — Locate report
- Ticker: `MCH` (CTCP Hàng tiêu dùng Masan / Masan Consumer Holdings)
- Năm: `2021` và `2023` (không liền tiếp → cần 2 report)
- `doc_type = consolidated`
- ⇒ `report_id_2021 = MCH_financial_statements_2021_consolidated`
- ⇒ `report_id_2023 = MCH_financial_statements_2023_consolidated`

### Step 2 — Locate table
- "Vay ngắn hạn" (mã 320) nằm ở **Bảng CĐKT — phần Nợ ngắn hạn (mã 310)**.
- MCH 2021 consolidated: `table_pos = 4`
- MCH 2023 consolidated: `table_pos = 4` (cùng vị trí)

### Step 3 — Locate cell
- Row: `"Vay ngắn hạn"` (mã 320)
- MCH 2021 (table_4): cuối 2021 = **7.445.112.961.981** VND
- MCH 2023 (table_4): cuối 2023 = **8.468.802.865.360** VND

### Step 4 — Extract + compute
- V_2021 = 7,445,112,961,981 VND
- V_2023 = 8,468,802,865,360 VND
- Growth = (V_2023 - V_2021) / V_2021 × 100%
- = (8,468,802,865,360 - 7,445,112,961,981) / 7,445,112,961,981 × 100%
- = 1,023,689,903,379 / 7,445,112,961,981 × 100%
- = **13.75%**

### Submission draft
```
report_id       = MCH_financial_statements_2021_consolidated, MCH_financial_statements_2023_consolidated
relevant_tables = ["MCH_financial_statements_2021_consolidated|4", "MCH_financial_statements_2023_consolidated|4"]
csv_path        = data/MCH_financial_statements_2021_consolidated_table_4.csv, data/MCH_financial_statements_2023_consolidated_table_4.csv
```

### Pattern quan sát
- **Growth 2 năm không liền = 2 reports** — cần fetch cả 2, không thể dùng "Số đầu năm" shortcut.
- `mã 320` (Vay ngắn hạn) là anchor stable trong TT200; MCH dùng format chuẩn.
- MCH 2023 BS header là `"31/12/2023 VND"` và `"1/1/2023 VND"` (= cuối 2022) — cột thứ 2 không phải cuối 2021.

---

## L4.1 — Câu #752 (cross-bank diff, service income)

### Câu hỏi
> Chênh lệch lãi thuần từ hoạt động dịch vụ giữa Ngân hàng TMCP An Bình và Ngân hàng TMCP Quân đội năm 2022 là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker 1: `ABB` (Ngân hàng TMCP An Bình — An Binh Bank)
- Ticker 2: `MBB` (Ngân hàng TMCP Quân đội — MB Bank)
- Năm: `2022`
- `doc_type = consolidated` (cả 2)
- ⇒ `report_id_ABB = ABB_financial_statements_2022_consolidated`
- ⇒ `report_id_MBB = MBB_financial_statements_2022_consolidated`

**Ticker resolution**: "An Bình" → ABB; "Quân đội" → MBB — hai tên gọi thường dùng trong đề bài.

### Step 2 — Locate table
- "Lãi thuần từ hoạt động dịch vụ" nằm ở **KQKD bank schema**.
- ABB 2022: `table_pos = 8`
- MBB 2022: `table_pos = 8`

### Step 3 — Locate cell
- Row: `"Lãi thuần từ hoạt động dịch vụ"` (cả 2 ngân hàng)
- ABB 2022 (table_8): col `Năm nay` = **232.042** triệu VND
- MBB 2022 (table_8): col `Năm 2022` = **4.135.568** triệu VND

**Lưu ý MBB**: OCR merge các dòng Thu nhập và Chi phí dịch vụ thành 1 cell (format phức tạp), nhưng dòng "Lãi thuần từ hoạt động dịch vụ" riêng biệt với giá trị 4,135,568.

### Step 4 — Extract + compute
- ABB = 232,042 triệu VND
- MBB = 4,135,568 triệu VND
- Chênh lệch (ABB - MBB) = 232,042 - 4,135,568 = **-3,903,526 triệu đồng**

(Dấu âm: ABB nhỏ hơn MBB)

### Submission draft
```
report_id       = ABB_financial_statements_2022_consolidated, MBB_financial_statements_2022_consolidated
relevant_tables = ["ABB_financial_statements_2022_consolidated|8", "MBB_financial_statements_2022_consolidated|8"]
csv_path        = data/ABB_..._table_8.csv, data/MBB_..._table_8.csv
```

### Pattern quan sát
- **Cross-company = 2 reports, cùng table_type** — cần dispatch 2 retrieval requests song song.
- Bank income statement row label "Lãi thuần từ hoạt động dịch vụ" uniform giữa các ngân hàng Việt Nam.
- Kết quả có thể âm (ABB << MBB); cần giữ dấu trong answer.
- MBB OCR merge lines → parser cần handle merged cells.

---

## L4.2 — Câu #754 (cross-bank diff, domestic loans)

### Câu hỏi
> Tính chênh lệch quy mô dư nợ cho vay khách hàng nội địa của công ty mẹ Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh so với công ty mẹ Ngân hàng TMCP An Bình vào năm 2021 theo đơn vị triệu đồng.

### Step 1 — Locate report
- Ticker 1: `HDB` (HD Bank — "Phát triển Thành phố HCM")
- Ticker 2: `ABB` (An Binh Bank)
- Năm: `2021`
- "Công ty mẹ" ⇒ `doc_type = separate` cho cả 2
- ⇒ `report_id_HDB = HDB_financial_statements_2021_separate`
- ⇒ `report_id_ABB = ABB_financial_statements_2021_separate`

**Ticker resolution**: "Phát triển Thành phố Hồ Chí Minh" → HDB (không phải HDG hay HDC).

### Step 2 — Locate table
- "Cho vay khách hàng nội địa" = "Cho vay các tổ chức kinh tế, cá nhân trong nước" trong **thuyết minh cho vay khách hàng**.
- Không nằm trực tiếp trên BS (BS chỉ có tổng "Cho vay khách hàng") mà ở **note phân tích dư nợ theo loại**.
- HDB 2021 separate: `table_pos = 33`
- ABB 2021 separate: `table_pos = 32`

**Metadata cần**:
- `statement_type = notes`
- `note_title = "Phân tích cho vay theo loại"` hoặc tương đương
- `metric_canonical = loans_domestic_customers`

### Step 3 — Locate cell
- Row: `"Cho vay các tổ chức kinh tế, cá nhân trong nước"`
- Col: `Số cuối năm` / `31/12/2021`
- HDB 2021 separate (table_33): **185.373.610** triệu VND
- ABB 2021 separate (table_32): **68.729.213** triệu VND

**Lưu ý đơn vị**: cả 2 bảng đơn vị là "Triệu đồng".

### Step 4 — Extract + compute
- HDB = 185,373,610 triệu VND
- ABB = 68,729,213 triệu VND
- Chênh lệch (HDB - ABB) = 185,373,610 - 68,729,213 = **116,644,397 triệu đồng**

### Submission draft
```
report_id       = HDB_financial_statements_2021_separate, ABB_financial_statements_2021_separate
relevant_tables = ["HDB_financial_statements_2021_separate|33", "ABB_financial_statements_2021_separate|32"]
csv_path        = data/HDB_..._table_33.csv, data/ABB_..._table_32.csv
```

### Pattern quan sát
- **"Nội địa" = sub-metric của "Cho vay khách hàng"** — cần truy vào note, không dùng BS tổng.
- Pitfall: "công ty mẹ ngân hàng" → `separate`, không phải `consolidated` — dù câu không nói rõ ngân hàng thường dùng separate để báo cáo công ty mẹ.
- "Cho vay các tổ chức kinh tế, cá nhân trong nước" vs "Cho vay các tổ chức kinh tế, cá nhân nước ngoài" — phải chọn đúng row.

---

## L5.1 — Câu #818 (5-year average, note lookup)

### Câu hỏi
> Giá trị trung bình của tổng số dư dự phòng phải thu khó đòi cuối kỳ của FTS tại các mốc cuối năm 2018, 2020, 2021, 2023 và 2024 là bao nhiêu triệu đồng?

### Step 1 — Locate report
- Ticker: `FTS` (securities company)
- Năm: `2018`, `2020`, `2021`, `2023`, `2024`
- FTS không có doc_type suffix
- ⇒ 5 report_ids: `FTS_financial_statements_{year}` cho mỗi năm

### Step 2 — Locate table
- "Dự phòng phải thu khó đòi" (bad debt provision for receivables) ở **thuyết minh phân tích dự phòng phải thu**.
- FTS dùng bảng roll-forward: cột Số đầu kỳ / Trích lập / Hoàn nhập / Số cuối kỳ.
- Table positions (verified):
  - FTS 2018: `table_pos = 22`
  - FTS 2020: `table_pos = 28`
  - FTS 2021: `table_pos = 27`
  - FTS 2023: `table_pos = 26`
  - FTS 2024: `table_pos = 22`

### Step 3 — Locate cell
- Row: `"Cộng"` (tổng dự phòng)
- Col: `Số cuối kỳ` (cột 7 trong bảng 9-cột)
- Values (VND):
  - 2018: **190,150,000**
  - 2020: **78,650,000**
  - 2021: **125,070,000**
  - 2023: **158,325,000**
  - 2024: **173,475,000**

**Metadata cần**:
- `statement_type = notes`
- `note_title = "Dự phòng nợ phải thu khác khó đòi"`
- `column_semantics = ending_balance` (Số cuối kỳ)

### Step 4 — Extract + compute
- Tổng = 190,150,000 + 78,650,000 + 125,070,000 + 158,325,000 + 173,475,000 = 725,670,000 VND
- Trung bình = 725,670,000 / 5 = 145,134,000 VND
- Đổi ra triệu đồng: 145,134,000 / 1,000,000 = **145.134 triệu đồng**

### Submission draft
```
report_id       = FTS_financial_statements_{2018,2020,2021,2023,2024}
relevant_tables = ["FTS_financial_statements_2018|22", "FTS_financial_statements_2020|28", "FTS_financial_statements_2021|27", "FTS_financial_statements_2023|26", "FTS_financial_statements_2024|22"]
```

### Pattern quan sát
- **5-year lookup = 5 reports, cùng note type** — table_pos khác nhau mỗi năm, cần retrieve từng cái.
- Bảng roll-forward dự phòng: cấu trúc cố định nhưng số cột có thể thay đổi → cần parse bằng header name, không phải column index.
- "Cộng" row là tổng của tất cả khoản → cần exact match "Cộng" không phải dùng dòng cuối.
- FTS report không có đơn vị triệu — các số là VND nguyên → phải chia 1e6 trước khi trả lời.

---

## L5.2 — Câu #820 (5-year average, income statement)

### Câu hỏi
> Tổng doanh thu hoạt động tài chính trung bình của Tổng Công ty cổ phần Phát triển Khu Công nghiệp công ty mẹ trong các năm 2018, 2019, 2020, 2021 và 2022 là mấy trăm tỷ đồng?

### Step 1 — Locate report
- Ticker: `SNZ` (Tổng Công ty cổ phần Phát triển Khu Công nghiệp — Sonadezi)
- "Công ty mẹ" ⇒ `doc_type = separate`
- Năm: `2018`, `2019`, `2020`, `2021`, `2022`
- ⇒ `report_id = SNZ_financial_statements_{year}_separate` cho mỗi năm

### Step 2 — Locate table
- "Doanh thu hoạt động tài chính" (mã 21) nằm ở **KQKD chính**.
- Table positions (verified qua header `"Doanh thu hoạt động tài chính"`):
  - SNZ 2018 separate: `table_pos = 7`
  - SNZ 2019 separate: `table_pos = 10`
  - SNZ 2020 separate: `table_pos = 9`
  - SNZ 2021 separate: `table_pos = 7`
  - SNZ 2022 separate: `table_pos = 8`

### Step 3 — Locate cell
- Row: `"Doanh thu hoạt động tài chính"` (mã 21)
- Col: năm hiện tại (cột 1 trong KQKD, không phải cột "năm trước")
- Values (VND):
  - 2018: **332,725,166,810**
  - 2019: **404,835,614,882**
  - 2020: **398,906,844,211**
  - 2021: **380,622,060,146**
  - 2022: **517,428,863,638**

**Cross-check**: Giá trị năm nay của báo cáo T khớp với giá trị "năm trước" của báo cáo T+1 (ví dụ 2019 report cột "năm trước" = 332,725,166,810 = giá trị 2018).

### Step 4 — Extract + compute
- Tổng = 332,725,166,810 + 404,835,614,882 + 398,906,844,211 + 380,622,060,146 + 517,428,863,638
- = 2,034,518,549,687 VND
- Trung bình = 2,034,518,549,687 / 5 = 406,903,709,937.4 VND
- Đổi ra trăm tỷ: 406,903,709,937.4 / 100,000,000,000 = **4.069 trăm tỷ đồng**

### Submission draft
```
report_id       = SNZ_financial_statements_{2018..2022}_separate
relevant_tables = ["SNZ_financial_statements_2018_separate|7", "SNZ_financial_statements_2019_separate|10", "SNZ_financial_statements_2020_separate|9", "SNZ_financial_statements_2021_separate|7", "SNZ_financial_statements_2022_separate|8"]
```

### Pattern quan sát
- **mã 21 = Doanh thu hoạt động tài chính** — stable anchor trong TT200, đúng cho non-financial.
- KQKD separate có cột `năm hiện tại` và `năm trước (so sánh)` — phải lấy đúng cột năm hiện tại.
- Table_pos thay đổi mỗi năm (7, 10, 9, 7, 8) → phải dùng `tables_index.jsonl` tra cứu, không hardcode.
- Đơn vị VND (không phải triệu VND như bank) → cần chia 1e11 để ra trăm tỷ.

---

## L6.1 — Câu #363 (2-tier: argmax D/E → interest coverage)

### Câu hỏi
> Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, hệ số khả năng thanh toán lãi vay là bao nhiêu lần?

### Step 1 — Locate report
- Ticker: `KBC` (CTCP Khu Công nghiệp Kinh Bắc — non-financial)
- Năm: `2016`, `2017`, `2018`, `2019`, `2020`
- `doc_type = consolidated`
- ⇒ 5 năm, nhưng dùng technique: mỗi report có cả số năm hiện tại và năm trước → chỉ cần 3 report
  - KBC 2016: lấy NPT/VCSH 2016
  - KBC 2018: lấy NPT/VCSH 2018 và 2017 (cột đầu năm)
  - KBC 2020: lấy NPT/VCSH 2020 và 2019 (cột đầu năm)
- ⇒ `report_ids = KBC_financial_statements_{2016,2018,2020}_consolidated`

**L6 planning**: Bước 1 = tính D/E cho 5 năm → tìm argmax. Bước 2 = tính interest coverage ở năm đó.

### Step 2 — Locate table (Bước 1: D/E)
- NPT (mã 300) và VCSH (mã 400) ở **BĐKT phần Nguồn vốn** — tách 2 bảng (BS_liabilities và BS_equity).
- KBC 2016 consolidated:
  - `table_pos = 6`: NPT (mã 300)
  - `table_pos = 7`: VCSH (mã 400)
- KBC 2018 consolidated:
  - `table_pos = 6`: NPT (mã 300)
  - `table_pos = 7`: VCSH (mã 400)
- KBC 2020 consolidated:
  - `table_pos = 7`: NPT (mã 300)
  - `table_pos = 8`: VCSH (mã 400)

### Step 3 — Locate cell (D/E cho 5 năm)
Giá trị từ cột "Cuối năm" và "Đầu năm" (verified):
- 2016: NPT = 6,036,457,811,415; VCSH = 8,621,089,984,484 → D/E = 0.700
- 2017 (from KBC 2018, cột đầu năm): NPT = 6,741,660,188,971; VCSH = 9,038,107,349,299 → D/E = 0.746
- 2018: NPT = 7,072,374,423,221; VCSH = 9,837,357,794,557 → D/E = 0.719
- 2019 (from KBC 2020, cột đầu năm): NPT = 6,051,858,701,629; VCSH = 10,381,131,101,072 → D/E = 0.583
- 2020: NPT = 13,132,883,122,220; VCSH = 10,652,995,127,729 → D/E = **1.233** ← MAX

**Năm có D/E cao nhất = 2020**

### Step 2' — Locate table (Bước 2: Interest Coverage 2020)
- "LN trước thuế" (mã 50) và "CP lãi vay" (mã 23) ở **KQKD** của KBC 2020 consolidated.
- `table_pos = 9` (KBC 2020 consolidated KQKD)

### Step 3' — Locate cell (EBIT components 2020)
- mã 50 (LN trước thuế): 453,172,376,342 VND
- mã 23 (CP lãi vay): 195,387,067,311 VND
- EBIT = 453,172,376,342 + 195,387,067,311 = 648,559,443,653 VND

### Step 4 — Extract + compute
- Interest Coverage = EBIT / Chi phí lãi vay
- = 648,559,443,653 / 195,387,067,311
- = **3.319 lần**

### Submission draft
```
report_id       = KBC_financial_statements_2016_consolidated, KBC_financial_statements_2018_consolidated, KBC_financial_statements_2020_consolidated
relevant_tables = ["KBC_2016|6", "KBC_2016|7", "KBC_2018|6", "KBC_2018|7", "KBC_2020|7", "KBC_2020|8", "KBC_2020|9"]
```

### Pattern quan sát
- **L6 = 2 LLM subqueries**: (1) argmax(D/E) trả về năm; (2) compute(interest_coverage) tại năm đó.
- Kỹ thuật "prior year column": mỗi BS report có 2 cột → chỉ cần 3 report thay vì 5 để lấy đủ 5 năm.
- EBIT = mã 50 + mã 23 (VN formula) — không phải lấy EBIT trực tiếp từ KQKD.
- KBC có NPT tăng vọt 2020 do dự án phát triển KCN → D/E > 1, bất thường so với các năm trước.

---

## L6.2 — Câu #524 (2-tier: argmax loans → fund balance at that year)

### Câu hỏi
> Trong các năm 2017, 2018, 2021 và 2022, số dư cuối năm quỹ khen thưởng và phúc lợi của Ngân hàng TMCP Phương Đông tại năm có giá trị cho vay các tổ chức kinh tế và cá nhân trong nước lớn nhất là bao nhiêu tỷ đồng?

### Step 1 — Locate report
- Ticker: `OCB` (Ngân hàng TMCP Phương Đông — Orient Commercial Bank)
- Năm: `2017`, `2018`, `2021`, `2022`
- `doc_type = consolidated` (bank)
- ⇒ `report_ids = OCB_financial_statements_{2017,2018,2021,2022}_consolidated`
- Lưu ý: OCB 2022 có 2 file → `OCB_financial_statements_2022_consolidated_1`

**L6 planning**: Bước 1 = tìm năm có loans nội địa lớn nhất. Bước 2 = đọc quỹ khen thưởng phúc lợi của năm đó.

### Step 2 — Locate table (Bước 1: Loans breakdown)
- "Cho vay các tổ chức kinh tế và cá nhân trong nước" nằm ở **thuyết minh cho vay khách hàng**.
- Table positions (verified):
  - OCB 2017 consolidated: `table_pos = 25`
  - OCB 2018 consolidated: `table_pos = 21`
  - OCB 2021 consolidated: `table_pos = 31`
  - OCB 2022 consolidated_1: `table_pos = 30`

### Step 3 — Locate cell (Loans cho 4 năm)
- Row: `"Cho vay các tổ chức kinh tế và cá nhân trong nước"`
- Col: `Số dư cuối năm`
- Values (VND):
  - 2017: 47,893,069,902,809
  - 2018: 55,962,872,280,567
  - 2021: 101,578,366,954,676
  - 2022: **119,510,721,884,604** ← MAX

**Năm có cho vay nội địa lớn nhất = 2022**

### Step 2' — Locate table (Bước 2: Reward fund 2022)
- "Quỹ khen thưởng phúc lợi" nằm ở **thuyết minh về các khoản phải trả khác** hoặc **bảng VCSH**.
- OCB 2022 consolidated_1: `table_pos = 68`

### Step 3' — Locate cell (Fund balance 2022)
- Row: `"Quỹ khen thưởng phúc lợi (*)"` trong bảng phân tích các khoản nợ khác
- Col: `Số dư cuối năm`
- Value = **102,424,213,974** VND

### Step 4 — Extract + compute
- Giá trị: 102,424,213,974 VND
- Câu hỏi hỏi "tỷ đồng" ⇒ chia 1e9 = 102,424,213,974 / 1,000,000,000 = **102.424 tỷ đồng**

### Submission draft
```
report_id       = OCB_financial_statements_{2017,2018,2021}_consolidated, OCB_financial_statements_2022_consolidated_1
relevant_tables = ["OCB_2017|25", "OCB_2018|21", "OCB_2021|31", "OCB_2022_1|30", "OCB_2022_1|68"]
```

### Pattern quan sát
- **L6 bank nested**: (1) argmax(loans) → (2) read fund at argmax year — cả 2 bước đều dùng bank-specific tables.
- OCB 2022 có 2 file (`_1` và `_2`) — cần biết file nào chứa bảng cần. Thuyết minh nợ khác thường ở file đầu.
- "Quỹ khen thưởng phúc lợi" ở bank nằm trong bảng phân tích "Các khoản nợ khác" (không phải VCSH trực tiếp).
- Pitfall: OCB 2022 loans value tại "Số dư đầu năm" của report 2022 = cuối 2021 = 101,578,366,954,676 — đây là cross-check cho loans 2021 từ report 2021.
