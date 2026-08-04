# Solve coverage on all questions

- Total questions: **1,012**
- Parquet rows: **274,899**

## Outcome distribution

| Category | Count | Pct |
|---|---:|---:|
| `ANSWERED` | 277 | 27.4% |
| `NO_METRIC` | 579 | 57.2% |
| `NO_CELL` | 29 | 2.9% |
| `OP_NA` | 34 | 3.4% |
| `ERROR` | 93 | 9.2% |

## Op × Category

| op | ANSWERED | NO_METRIC | NO_CELL | OP_NA | ERROR |
|---|---:|---:|---:|---:|---:|
| `lookup` | 160 | 423 | 0 | 0 | 59 |
| `ratio` | 62 | 12 | 12 | 0 | 28 |
| `growth` | 42 | 24 | 15 | 0 | 6 |
| `diff` | 0 | 66 | 0 | 18 | 0 |
| `avg` | 0 | 30 | 0 | 16 | 0 |
| `argmax` | 11 | 22 | 2 | 0 | 0 |
| `ratio_profit_margin` | 2 | 0 | 0 | 0 | 0 |
| `sum` | 0 | 2 | 0 | 0 | 0 |

## Sample questions per category

### ANSWERED (showing 5 of 277)

- **#10** op=`lookup` metrics=['Chi phí tài chính'] answer=112789887883.0
  - Q: Chi phí tài chính của công ty mẹ CTCP Phát triển Sunshine Homes năm 2021 là bao nhiêu triệu đồng?
- **#13** op=`lookup` metrics=['Tương đương tiền'] answer=1700000000000.0
  - Q: Tiền và các khoản tương đương tiền của công ty mẹ Tổng Công ty cổ phần Bia - Rượu - Nước giải khát Sài Gòn (SAB) vào cuối năm 2016 là bao nhiêu tỷ đồng?
- **#14** op=`lookup` metrics=['Chi phí QLDN'] answer=144071806197.0
  - Q: Chi phí quản lý doanh nghiệp năm 2025 của công ty mẹ ASM là bao nhiêu triệu đồng?
- **#18** op=`lookup` metrics=['VCSH'] answer=2077869596655.0
  - Q: Vốn chủ sở hữu của FIT là bao nhiêu tỷ đồng vào ngày 31/12/2015?
- **#24** op=`lookup` metrics=['Vay DH'] answer=5095823404.0
  - Q: Vay dài hạn với Công ty Cổ phần Hoàng Anh Gia Lai của công ty mẹ CTCP Nông nghiệp Quốc tế Hoàng Anh Gia Lai (HNG) cuối năm 2017 là bao nhiêu nghìn đồng?

### NO_METRIC (showing 5 of 579)

- **#1** op=`lookup` metrics=[] answer=None
  - Q: Lãi tiền gửi năm 2018 của công ty mẹ CTCP Hàng không Vietjet (VJC) là bao nhiêu triệu đồng?
  - err: `no metric matched`
- **#2** op=`lookup` metrics=[] answer=None
  - Q: Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?
  - err: `no metric matched`
- **#3** op=`lookup` metrics=[] answer=None
  - Q: Chi phí dự phòng của Ngân hàng TMCP Sài Gòn Tài Lộc trong năm 2020 là bao nhiêu triệu đồng?
  - err: `no metric matched`
- **#5** op=`lookup` metrics=[] answer=None
  - Q: Chi phí phạt của công ty mẹ SCR năm 2017 là bao nhiêu tỷ đồng?
  - err: `no metric matched`
- **#6** op=`lookup` metrics=[] answer=None
  - Q: Lưu chuyển tiền thuần từ hoạt động kinh doanh của công ty mẹ VSC trong năm 2017 là bao nhiêu tỷ đồng?
  - err: `no metric matched`

### NO_CELL (showing 5 of 29)

- **#362** op=`ratio` metrics=['Nợ NH', 'Hàng tồn kho'] answer=None
  - Q: Xét nhóm cổ phiếu CEO, HPX, KBC, SNZ, VIC, VPI và VRE trong năm 2022: Tỷ trọng tổng nợ ngắn hạn của các mã có hệ số hàng tồn kho/nợ ngắn hạn trên mức trung vị là bao nhiêu phần trăm?
  - err: `missing cells: num=None, den=1467663040362.0`
- **#364** op=`growth` metrics=['DTT'] answer=None
  - Q: Xét các doanh nghiệp hóa chất (GVR, DPM, DCM, PRT) có CFO dương trong cả hai năm 2020 và 2021, công ty đạt tăng trưởng doanh thu thuần cao nhất có tỷ số dồn tích năm 2021 là bao nhiêu phần trăm?
  - err: `missing cells: end=None, beg=None`
- **#395** op=`growth` metrics=['DTT'] answer=None
  - Q: Trong giai đoạn từ năm 2022 đến năm 2025, vào năm mà doanh thu thuần của Đô thị Kinh Bắc bị sụt giảm sâu nhất so với năm trước đó, tỷ suất dòng tiền thuần từ hoạt động kinh doanh trên doanh thu thuần của năm đó là bao nhiêu phần trăm?
  - err: `missing cells: end=None, beg=None`
- **#402** op=`ratio` metrics=['Hàng tồn kho', 'Tổng tài sản', 'Lợi nhuận gộp'] answer=None
  - Q: Từ 2023 sang 2024, trong các doanh nghiệp ngành quản lý và phát triển bất động sản (bao gồm các công ty HPX, KBC, NVL, VIC, VPI, VRE), có bao nhiêu doanh nghiệp đồng thời tăng tỷ trọng hàng tồn kho trên tổng tài sản và giảm biên lợi nhuận gộp?
  - err: `missing cells: num=None, den=None`
- **#411** op=`growth` metrics=['DTT'] answer=None
  - Q: Căn cứ vào báo cáo tài chính hợp nhất năm 2025 của các doanh nghiệp bất động sản thuộc nhóm HPX, KBC, NVL, PDR và SCR, có bao nhiêu doanh nghiệp đồng thời ghi nhận tăng trưởng doanh thu thuần so với năm 2024 và có hệ số biên dòng tiền từ hoạt động kinh doanh (CFO Margin) âm trong năm 2025?
  - err: `missing cells: end=None, beg=None`

### OP_NA (showing 5 of 34)

- **#487** op=`diff` metrics=['LNST', 'Tổng tài sản'] answer=None
  - Q: Trong các công ty DLG, HHV và VSC có lợi nhuận sau thuế dương năm 2020, bình quân tỷ lệ giữa chênh lệch lợi nhuận sau thuế và lưu chuyển tiền thuần từ hoạt động kinh doanh với trung bình tổng tài sản cuối năm 2019 và 2020 là bao nhiêu %?
  - err: `op diff not implemented in prototype`
- **#581** op=`diff` metrics=['TSCĐ'] answer=None
  - Q: Chênh lệch giá trị còn lại của tài sản cố định hữu hình tại CTCP Tập đoàn Dabaco Việt Nam (DBC) giữa thời điểm cuối năm 2019 và thời điểm cuối năm 2015 là bao nhiêu tỷ đồng?
  - err: `op diff not implemented in prototype`
- **#584** op=`diff` metrics=['VCSH'] answer=None
  - Q: Chênh lệch vốn chủ sở hữu giữa cuối năm 2025 và cuối năm 2024 của Công ty CP Nhựa An Phát Xanh (AAA) là bao nhiêu tỷ đồng?
  - err: `op diff not implemented in prototype`
- **#590** op=`diff` metrics=['Vay NH'] answer=None
  - Q: Chênh lệch tổng hạn mức vay ngắn hạn của CTCP Đầu tư Hạ tầng Giao thông Đèo Cả (HHV) giữa năm 2025 và 2021 là bao nhiêu tỷ đồng?
  - err: `op diff not implemented in prototype`
- **#616** op=`diff` metrics=['TSCĐ'] answer=None
  - Q: Chênh lệch giá trị còn lại Tài sản cố định hữu hình của VJC giữa cuối năm 2018 và cuối năm 2015 là bao nhiêu nghìn tỷ đồng?
  - err: `op diff not implemented in prototype`

### ERROR (showing 5 of 93)

- **#4** op=`lookup` metrics=['LNST'] answer=None
  - Q: Lợi nhuận sau thuế của CTCP Chứng khoán FPT năm 2023 là bao nhiêu tỷ đồng?
- **#16** op=`lookup` metrics=['Vay NH'] answer=None
  - Q: Số dư vay ngắn hạn của công ty mẹ CEO cuối năm 2025 là bao nhiêu tỷ đồng?
- **#40** op=`lookup` metrics=['LNST'] answer=None
  - Q: Lợi nhuận sau thuế của VIB năm 2020 là bao nhiêu triệu đồng?
- **#44** op=`lookup` metrics=['Tổng tài sản'] answer=None
  - Q: Tổng tài sản của STB là bao nhiêu triệu đồng vào cuối năm 2016?
- **#45** op=`lookup` metrics=['Nợ phải trả'] answer=None
  - Q: Tổng nợ phải trả của công ty mẹ BAB đến ngày 31/12/2020 là bao nhiêu triệu đồng?