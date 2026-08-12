# 35 câu sai — data raw

run: `artifacts/runs/solve_gold75_verifyfull_fix_run2.jsonl`  |  gold: 73 câu, đúng 38


---

## qid 115

**Câu hỏi:** Tổng chi phí hoạt động của công ty mẹ Ngân hàng TMCP Công Thương Việt Nam năm 2019 là bao nhiêu triệu đồng?

- gold = `14733282.0` triệu đồng
- pred = `-14733282.0`
- query = `df2.iloc[13]["2019 triệu đồng"]`
- ô gold (gold ghi tay) = `(14.733.282)`
- cách tính gold = `Already triệu đồng per column header; source shows (14.733.282) i.e. -14,733,282 as a deduction in the income statement; reported here as positive expense magnitude 14,733,282`
- **bảng gold CẦN (1):** ['CTG_financial_statements_2019_separate|7']
- **bảng đã CHO XEM (3):** ['CTG_financial_statements_2019_separate|4', 'CTG_financial_statements_2019_separate|7', 'CTG_financial_statements_2019_separate|9']
- bảng đã retrieve (6): ['CTG_financial_statements_2019_separate|7', 'CTG_financial_statements_2019_separate|4', 'CTG_financial_statements_2019_separate|9', 'CTG_financial_statements_2019_separate|8', 'CTG_financial_statements_2019_separate|6', 'CTG_financial_statements_2019_separate|5']

---

## qid 120

**Câu hỏi:** Chi phí hoạt động của Ngân hàng TMCP Kiên Long (KLB) năm 2019 là bao nhiêu triệu đồng?

- gold = `1041601.0` triệu đồng
- pred = `928436.0`
- query = `df1.iloc[13]["Năm nay"]`
- ô gold (gold ghi tay) = `1.041.601`
- cách tính gold = `Statement header states 'Đơn vị tính: triệu VND'; 1.041.601 parses as 1,041,601 triệu đồng`
- **bảng gold CẦN (1):** ['KLB_financial_statements_2019_consolidated|8']
- **bảng đã CHO XEM (3):** ['KLB_financial_statements_2019_consolidated|8', 'KLB_financial_statements_2019_consolidated|48', 'KLB_financial_statements_2019_consolidated|75']
- bảng đã retrieve (14): ['KLB_financial_statements_2019_consolidated|75', 'KLB_financial_statements_2019_consolidated|48', 'KLB_financial_statements_2019_consolidated|8', 'KLB_financial_statements_2019_consolidated|64', 'KLB_financial_statements_2019_consolidated|63', 'KLB_financial_statements_2019_consolidated|62', 'KLB_financial_statements_2019_consolidated|61', 'KLB_financial_statements_2019_consolidated|70', 'KLB_financial_statements_2019_consolidated|60', 'KLB_financial_statements_2019_consolidated|6', 'KLB_financial_statements_2019_consolidated|66', 'KLB_financial_statements_2019_consolidated|57', 'KLB_financial_statements_2019_consolidated|19', 'KLB_financial_statements_2019_consolidated|10']
- verify nói: *Hàng 13 trong df1 trả về giá trị cho "Năm trước" (2018) là 928436.0, trong khi câu hỏi yêu cầu số liệu cho năm 2019 ("Năm nay") là 1041601.0.*
- query trước khi verify sửa: `df1.iloc[13]["Năm nay"]`

### Bảng model thực sự nhìn thấy

**df1 = `KLB_financial_statements_2019_consolidated|8`**  (23x5)

```
                                             STT                                      Chỉ tiêu  Thuyết minh    Năm nay  Năm trước
0                                                 1. Thu nhập lãi và các khoản thu nhập tươ...          NaN  3897868.0  3171636.0
1   2. Chi phí lãi và các khoản chi phí tương tự                                          VI.2    2889998.0  2196765.0        NaN
2                          I. Thu nhập lãi thuần                                                  1007870.0   974871.0        NaN
3               3. Thu nhập từ hoạt động dịch vụ                                          VI.3      93310.0    73869.0        NaN
4                4. Chi phí từ hoạt động dịch vụ                                          VI.3      16854.0    17910.0        NaN
5          II. Lãi/lỗ thuần từ hoạt động dịch vụ                                          VI.3      76456.0    55959.0        NaN
6      III. Lãi/lỗ thuần từ kinh doanh ngoại hối                                          VI.4      28631.0    11626.0        NaN
7   IV. Lãi/lỗ thuần từ mua bán chứng khoán k...                                                        0.0        0.0        NaN
8   V. Lãi/lỗ thuần từ mua bán chứng khoán đầ...                                          VI.5      61938.0   116790.0        NaN
9                  5. Thu nhập từ hoạt động khác                                          VI.6      35287.0   105024.0        NaN
10                  6. Chi phí từ hoạt động khác                                          VI.6       8208.0     8832.0        NaN
11            VI. Lãi/lỗ thuần từ hoạt động khác                                          VI.6      27079.0    96192.0        NaN
12         VII. Thu nhập từ góp vốn, mua cổ phần                                          VI.7        835.0      724.0        NaN
13                       VIII. Chi phí hoạt động                                          VI.8    1041601.0   928436.0        NaN
14  IX. Lợi nhuận thuần từ hoạt động kinh doa...                                                   161208.0   327726.0        NaN
15           X. Chi phí dự phòng rủi ro tín dụng                                        V.6, 7      75287.0    37644.0        NaN
16                 XI. Tổng lợi nhuận trước thuế                                                    85921.0   290082.0        NaN
17  7. Chi phí thuế thu nhập doanh nghiệp hiệ...                                        VIII.2      18247.0    58193.0        NaN
18  8. Chi phí thuế thu nhập doanh nghiệp hoã...                                                        0.0        0.0        NaN
19       XII. Chi phí thuế thu nhập doanh nghiệp                                                    18247.0    58193.0        NaN
20                      XIII. Lợi nhuận sau thuế                                                    67674.0   231889.0        NaN
21             XIV. Lợi ích của cổ đông thiểu số                                                        0.0        0.0        NaN
22            XV. Lãi cơ bản trên cổ phiếu (VND)                                      VI.9a, b        212.0      644.0        NaN
```

**df2 = `KLB_financial_statements_2019_consolidated|48`**  (25x3)

```
                                      Unnamed: 0    Năm nay  Năm nay.1
0          Chi nộp thuế và các khoản phí, lệ phí    21395.0    22983.0
1                          Chi phí cho nhân viên   577443.0   502088.0
2                                      Trong đó:        NaN        NaN
3                           Chi lương và phụ cấp   502488.0   436437.0
4              Các khoản chi đóng góp theo lương    41872.0    34704.0
5                     Chi phí khác cho nhân viên    33083.0    30947.0
6                                 Chi về tài sản   221296.0   198470.0
7                                      Trong đó:        NaN        NaN
8               Chi phí khấu hao tài sản cố định    70770.0    69854.0
9                           Chi phí thuê tài sản    63942.0    60479.0
10                         Chi sửa chữa, bảo trì    65382.0    48141.0
11                  Chi mua sắm công cụ lao động    20413.0    19560.0
12                                  Chi phí khác      789.0      436.0
13          Chi phí hoạt động quản lý và công vụ   180875.0   164905.0
14                                     Trong đó:        NaN        NaN
15  Chi phí quảng cáo tiếp thị, khuyến mại và...    44376.0    45560.0
16                                  Công tác phí     3701.0     3772.0
17  Chi phí điện nước, vệ sinh cơ quan, xăng dầu    37969.0    33735.0
18  Chi phí thông tin liên lạc, nghiên cứu ứn...    28743.0    24442.0
19                               Chi phí đào tạo     2032.0     1132.0
20          Chi phí hội nghị, lễ tân, khách tiết    54545.0    49406.0
21                                  Chi phí khác     9509.0     6858.0
22  Chi nộp phí bảo hiểm, bảo toàn tiền gửi c...    40592.0    37928.0
23  Chi phí dự phòng rủi ro các tài sản Có nộ...        0.0     2062.0
24                                          Cộng  1041601.0   928436.0
```

**df3 = `KLB_financial_statements_2019_consolidated|75`**  (7x6)

```
     STT                          Chỉ tiêu  Năm 2018   Năm 2019  Tăng/giảm (+/-) năm 2019 so với năm 2018  Unnamed: 5
0  Số dư                         Tỷ lệ (%)       NaN        NaN                                       NaN         NaN
1     II                      Tổng chi phí  966080.0  1116888.0                                  150808.0       15.61
2      1                 Chi phí hoạt động  928436.0  1041601.0                                  113165.0       12.19
3      2  Chi phí dự phòng rủi ro tín dụng   37644.0    75287.0                                   37643.0      100.00
4    III         Tổng lợi nhuận trước thuế  290082.0    85921.0                                 -204161.0      -70.38
5     IV                 Chi phí thuế TNDN   58193.0    18247.0                                  -39946.0      -68.64
6      V                Lợi nhuận sau thuế  231889.0    67674.0                                 -164215.0      -70.82
```


---

## qid 166

**Câu hỏi:** Số dư cho vay Công ty Cổ phần Nhà Hòa Bình đến ngày 31/12/2016 của công ty mẹ HBC là bao nhiêu trăm tỷ đồng?

- gold = `2.21951021299` trăm tỷ đồng
- pred = `5.0487666752199996`
- query = `(df2.iloc[2]["Số cuối năm"]) * 1e-11`
- ô gold (gold ghi tay) = `221.951.021.299`
- cách tính gold = `221.951.021.299 VND / 1e11 = 2.21951021299 trăm tỷ đồng`
- **bảng gold CẦN (1):** ['HBC_financial_statements_2016_separate|71']
- **bảng đã CHO XEM (3):** ['HBC_financial_statements_2016_separate|5', 'HBC_financial_statements_2016_separate|22', 'HBC_financial_statements_2016_separate|23']
- bảng đã retrieve (7): ['HBC_financial_statements_2016_separate|23', 'HBC_financial_statements_2016_separate|22', 'HBC_financial_statements_2016_separate|5', 'HBC_financial_statements_2016_separate|6', 'HBC_financial_statements_2016_separate|4', 'HBC_financial_statements_2016_separate|8', 'HBC_financial_statements_2016_separate|7']
- ⛔ **thiếu trong prompt:** ['HBC_financial_statements_2016_separate|71']
- verify nói: *Câu hỏi yêu cầu số dư "cho vay" (phải thu), nhưng truy vấn lại lấy số liệu từ dòng "Vay dài hạn" (nợ phải trả) trong bảng cân đối kế toán.*
- query trước khi verify sửa: `(df1.iloc[12]["Số cuối năm"]) * 1e-11`

### Bảng model thực sự nhìn thấy

**df1 = `HBC_financial_statements_2016_separate|5`**  (24x5)

```
    Mã số                                     NGUỒN VỐN  Thuyết minh   Số cuối năm    Số đầu năm
0   300.0                                C. NỘ PHẢI TRẢ          NaN  8.693448e+12  5.585124e+12
1   310.0                                I. Nợ ngắn hạn          NaN  8.162481e+12  5.234760e+12
2   311.0                1. Phải trả người bán ngắn hạn         17.0  2.018766e+12  1.261459e+12
3   312.0          2. Người mua trả tiền trước ngắn hạn         18.0  2.271902e+12  1.417789e+12
4   313.0        3. Thuế và các khoản phải nộp Nhà nước         19.0  7.331678e+10  2.719896e+10
5   314.0                    4. Phải trả người lao động          NaN  3.164371e+11  1.734863e+11
6   315.0                  5. Chi phí phải trả ngắn hạn         20.0  1.018461e+12  6.093759e+11
7   319.0                     6. Phải trả ngắn hạn khác         21.0  3.753209e+09  3.505014e+09
8   320.0                               7. Vay ngắn hạn         22.0  2.457783e+12  1.741945e+12
9   322.0                  8. Quỹ khen thưởng, phúc lợi         23.0  2.062509e+09  0.000000e+00
10  330.0                                II. Nợ dài hạn          NaN  5.309664e+11  3.503636e+11
11  332.0           1. Người mua trả tiền trước dài hạn         18.0  9.884855e+10  1.933306e+11
12  338.0                                2. Vay dài hạn         22.0  3.253919e+11  8.850219e+10
13  342.0                  3. Dự phòng phải trả dài hạn         24.0  1.067259e+11  6.853080e+10
14  400.0                             D. VỐN CHỦ SỞ HỮU          NaN  1.627842e+12  1.139464e+12
15  410.0                             I. Vốn chủ sở hữu         25.0  1.627842e+12  1.139464e+12
16  411.0                                1. Vốn cổ phần          NaN  9.544646e+11  7.555984e+11
17    NaN      - Cổ phiếu phổ thông có quyền biểu quyết          NaN  9.544646e+11  7.555984e+11
18  412.0                       2. Thặng dư vốn cổ phần          NaN  3.049411e+10  1.060433e+11
19  418.0                      3. Quỹ đầu tư phát triển          NaN  9.454844e+10  9.454844e+10
20  421.0          4. Lợi nhuận sau thuế chưa phân phối          NaN  5.483345e+11  1.832737e+11
21    NaN  - Lợi nhuận sau thuế chưa phân phối lũy k...          NaN  6.878258e+10  2.759338e+10
22    NaN   - Lợi nhuận sau thuế chưa phân phối năm nay          NaN  4.795519e+11  1.556803e+11
23  440.0                           TỔNG CỘNG NGUỒN VỐN          NaN  1.032129e+13  6.724587e+12
```

**df2 = `HBC_financial_statements_2016_separate|22`**  (5x3)

```
                                  Unnamed: 0   Số cuối năm  VND Số đầu năm
0  Cho bên liên quan vay (Thuyết minh số 32)  4.719710e+11    2.838803e+11
1                           Cho bên khác vay  3.290563e+10    2.679797e+10
2                                  TỔNG CỘNG  5.048767e+11    3.106783e+11
3         Dự phòng phải thu ngắn hạn khó đòi -3.000000e+08   -1.876341e+09
4                              GIÁ TRỊ THUÀN  5.045767e+11    3.088019e+11
```

**df3 = `HBC_financial_statements_2016_separate|23`**  (4x3)

```
                     Unnamed: 0       Năm nay  VNDNăm trước
0                    Số đầu năm -1.876341e+09 -8.880731e+09
1  Dự phòng trích lập trong năm -1.014934e+08 -1.135427e+10
2    Sử dụng dự phòng trong năm  1.677834e+09  1.835866e+10
3                   Số cuối năm -3.000000e+08 -1.876341e+09
```


---

## qid 262

**Câu hỏi:** Cuối năm 2019, tổng số tiền khách hàng trả trước ngắn hạn của Tổng Công ty Sông Đà - CTCP (SJG) là bao nhiêu nghìn tỷ đồng?

- gold = `1.27187346118` nghìn tỷ đồng
- pred = `0.0`
- query = `df3.iloc[3]["Số cuối năm"]`
- ô gold (gold ghi tay) = `1.271.873.461.180`
- cách tính gold = `1.271.873.461.180 VND / 1e12 = 1.27187346118 nghìn tỷ đồng`
- **bảng gold CẦN (1):** ['SJG_financial_statements_2019_consolidated|8']
- **bảng đã CHO XEM (3):** ['SJG_financial_statements_2019_consolidated|6', 'SJG_financial_statements_2019_consolidated|7', 'SJG_financial_statements_2019_consolidated|8']
- bảng đã retrieve (9): ['SJG_financial_statements_2019_consolidated|8', 'SJG_financial_statements_2019_consolidated|6', 'SJG_financial_statements_2019_consolidated|7', 'SJG_financial_statements_2019_consolidated|10', 'SJG_financial_statements_2019_consolidated|77', 'SJG_financial_statements_2019_consolidated|76', 'SJG_financial_statements_2019_consolidated|9', 'SJG_financial_statements_2019_consolidated|13', 'SJG_financial_statements_2019_consolidated|11']

---

## qid 280

**Câu hỏi:** Số dư cho vay tái tài trợ nghiệp vụ UPAS L/C bằng VND của HDB đến ngày 31/12/2022 là bao nhiêu triệu đồng?

- gold = `8634940.0` triệu đồng
- pred = `0.0`
- query = `df3.iloc[3]["31.12.2022%"]`
- ô gold (gold ghi tay) = `8.634.940`
- cách tính gold = `already in triệu đồng, no conversion needed`
- **bảng gold CẦN (1):** ['HDB_financial_statements_2022_consolidated|19']
- **bảng đã CHO XEM (3):** ['HDB_financial_statements_2022_consolidated|4', 'HDB_financial_statements_2022_consolidated|6', 'HDB_financial_statements_2022_consolidated|21']
- bảng đã retrieve (7): ['HDB_financial_statements_2022_consolidated|21', 'HDB_financial_statements_2022_consolidated|4', 'HDB_financial_statements_2022_consolidated|6', 'HDB_financial_statements_2022_consolidated|7', 'HDB_financial_statements_2022_consolidated|2', 'HDB_financial_statements_2022_consolidated|5', 'HDB_financial_statements_2022_consolidated|3']
- ⛔ **thiếu trong prompt:** ['HDB_financial_statements_2022_consolidated|19']

---

## qid 327

**Câu hỏi:** Số tiền phải thu từ khách hàng khác của công ty mẹ CTCP Tập Đoàn PC1 (PC1) đến ngày 31/12/2021 là bao nhiêu trăm tỷ đồng?

- gold = `11.08219411035` trăm tỷ đồng
- pred = `0.74982686249`
- query = `(df3.iloc[16]["31/12/2021VND"]) * 1e-11`
- ô gold (gold ghi tay) = `1.108.219.411.035`
- cách tính gold = `1.108.219.411.035 VND / 1e11 = 11.08219411035 trăm tỷ đồng`
- **bảng gold CẦN (1):** ['PC1_financial_statements_2021_separate|14']
- **bảng đã CHO XEM (3):** ['PC1_financial_statements_2021_separate|5', 'PC1_financial_statements_2021_separate|7', 'PC1_financial_statements_2021_separate|15']
- bảng đã retrieve (7): ['PC1_financial_statements_2021_separate|15', 'PC1_financial_statements_2021_separate|5', 'PC1_financial_statements_2021_separate|7', 'PC1_financial_statements_2021_separate|2', 'PC1_financial_statements_2021_separate|3', 'PC1_financial_statements_2021_separate|6', 'PC1_financial_statements_2021_separate|4']
- ⛔ **thiếu trong prompt:** ['PC1_financial_statements_2021_separate|14']
- verify nói: *Hàng 17 là tổng cộng của các khoản phải thu ngắn hạn từ khách hàng (bao gồm cả công ty con), trong khi câu hỏi yêu cầu số tiền phải thu từ khách hàng "khác" (không phải công ty con), nên cần dùng hàng 16 hoặc tính tổng các hàng từ 1 đến 14 và 16.*
- query trước khi verify sửa: `(df3.iloc[17]["31/12/2021VND"]) * 1e-11`

---

## qid 353

**Câu hỏi:** MPC 2019 consolidated: Số dư tạm ứng cho nông dân cuối năm 2019 (triệu đồng)

- gold = `7306.508578` triệu đồng
- pred = `3500.0`
- query = `(df2.iloc[3]["31/12/2019VND"]) * 1e-6`
- ô gold (gold ghi tay) = `7.306.508.578`
- cách tính gold = `7.306.508.578 / 1e6 = 7306.508578`
- **bảng gold CẦN (1):** ['MPC_financial_statements_2019_consolidated|29']
- **bảng đã CHO XEM (3):** ['MPC_financial_statements_2019_consolidated|7', 'MPC_financial_statements_2019_consolidated|28', 'MPC_financial_statements_2019_consolidated|29']
- bảng đã retrieve (11): ['MPC_financial_statements_2019_consolidated|28', 'MPC_financial_statements_2019_consolidated|29', 'MPC_financial_statements_2019_consolidated|7', 'MPC_financial_statements_2019_consolidated|5', 'MPC_financial_statements_2019_consolidated|10', 'MPC_financial_statements_2019_consolidated|6', 'MPC_financial_statements_2019_consolidated|9', 'MPC_financial_statements_2019_consolidated|8', 'MPC_financial_statements_2019_consolidated|4', 'MPC_financial_statements_2019_consolidated|2', 'MPC_financial_statements_2019_consolidated|3']

---

## qid 355

**Câu hỏi:** MSN 2022 consolidated: Tỷ lệ lợi ích kinh tế tại Công ty TNHH Thực phẩm 3F Việt cuối năm 2022 (%)

- gold = `48.4` %
- pred = `256000000000.0`
- query = `df3.iloc[8]["Unnamed: 4"]`
- ô gold (gold ghi tay) = `48,4%`
- cách tính gold = `none, value already in percent`
- **bảng gold CẦN (1):** ['MSN_financial_statements_2022_consolidated|23']
- **bảng đã CHO XEM (3):** ['MSN_financial_statements_2022_separate|3', 'MSN_financial_statements_2022_separate|36', 'MSN_financial_statements_2022_separate|37']
- bảng đã retrieve (7): ['MSN_financial_statements_2022_separate|3', 'MSN_financial_statements_2022_separate|36', 'MSN_financial_statements_2022_separate|37', 'MSN_financial_statements_2022_separate|4', 'MSN_financial_statements_2022_separate|5', 'MSN_financial_statements_2022_separate|2', 'MSN_financial_statements_2022_separate|1']
- ⛔ **thiếu trong prompt:** ['MSN_financial_statements_2022_consolidated|23']
- verify nói: *Câu hỏi yêu cầu tỷ lệ lợi ích kinh tế, nhưng truy vấn trả về con số tiền (256000000000.0) từ cột '2021 VND' của dòng tổng hợp thuế, không phải tỷ lệ phần trăm và không phải chỉ số lợi ích kinh tế.*
- query trước khi verify sửa: `df3.iloc[8]["Unnamed: 4"]`

---

## qid 363

**Câu hỏi:** Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, hệ số khả năng thanh toán lãi vay là bao nhiêu lần?

- gold = `3.319` 
- pred = `-1.2147926433413134`
- query = `(df1.iloc[6]["Năm nay"] / abs(df1.iloc[7]["Năm nay"]))`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['KBC_financial_statements_2016_consolidated|8', 'KBC_financial_statements_2018_consolidated|8', 'KBC_financial_statements_2020_consolidated|9']
- bảng đã retrieve (35): ['KBC_financial_statements_2016_consolidated|8', 'KBC_financial_statements_2020_consolidated|9', 'KBC_financial_statements_2018_consolidated|8', 'KBC_financial_statements_2019_consolidated|8', 'KBC_financial_statements_2017_consolidated|7', 'KBC_financial_statements_2018_consolidated|10', 'KBC_financial_statements_2017_consolidated|8', 'KBC_financial_statements_2019_consolidated|10', 'KBC_financial_statements_2017_consolidated|9', 'KBC_financial_statements_2020_consolidated|11', 'KBC_financial_statements_2018_consolidated|7', 'KBC_financial_statements_2020_consolidated|5', 'KBC_financial_statements_2016_consolidated|10', 'KBC_financial_statements_2018_consolidated|9', 'KBC_financial_statements_2018_consolidated|4', 'KBC_financial_statements_2020_consolidated|8', 'KBC_financial_statements_2016_consolidated|4', 'KBC_financial_statements_2016_consolidated|9', 'KBC_financial_statements_2019_consolidated|4', 'KBC_financial_statements_2017_consolidated|3', 'KBC_financial_statements_2019_consolidated|7', 'KBC_financial_statements_2016_consolidated|7', 'KBC_financial_statements_2017_consolidated|6', 'KBC_financial_statements_2019_consolidated|5', 'KBC_financial_statements_2020_consolidated|6', 'KBC_financial_statements_2019_consolidated|9', 'KBC_financial_statements_2018_consolidated|6', 'KBC_financial_statements_2019_consolidated|6', 'KBC_financial_statements_2020_consolidated|10', 'KBC_financial_statements_2016_consolidated|6', 'KBC_financial_statements_2017_consolidated|5', 'KBC_financial_statements_2016_consolidated|5', 'KBC_financial_statements_2017_consolidated|4', 'KBC_financial_statements_2018_consolidated|5', 'KBC_financial_statements_2020_consolidated|7']
- verify nói: *Câu hỏi yêu cầu hệ số khả năng thanh toán lãi vay (Interest Coverage Ratio) của năm có tỷ số D/E cao nhất trong giai đoạn 2016-2020, nhưng truy vấn chỉ trả về con số "Chi phí lãi vay" của năm 2015 (dữ liệu trong df1 là báo cáo 2016, cột "Năm trước" tương ứng 2015), không phải là tỷ số thanh toán lãi vay.*
- query trước khi verify sửa: `df1.iloc[7]["Năm trước"]`

---

## qid 488

**Câu hỏi:** Năm 2016, trong số các công ty AAA, DCM, DPM và GVR có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần lớn hơn 10%, tổng doanh thu thuần của các công ty đó là bao nhiêu nghìn tỷ đồng?

- gold = `28.379904075338` nghìn tỷ đồng
- pred = `7.053940492179`
- query = `(pd.to_numeric(df1.iloc[2]["Năm 2016"], errors="coerce") + pd.to_numeric(df2.iloc[2]["Năm nay"], errors="coerce") + pd.to_numeric(df3.iloc[2]["Năm nay"], errors="coerce")) * 1e-12`
- ô gold (gold ghi tay) = `AAA: DTT=2.143.769.808.850, LNST=142.925.017.617 (ratio 6.667%, excluded); DCM: DTT=4.910.170.683.302, LNST=624.339.822.048 (ratio 12.715%, included); DPM: DTT=7.924.787.123.725, LNST=1.164.774.744.823 (ratio 14.698%, included); GVR: DTT=15.544.946.268.311, LNST=2.796.603.372.200 (ratio 17.990%, included)`
- cách tính gold = `sum of qualifying (>10%) companies' Doanh thu thuần: 4.910.170.683.302 + 7.924.787.123.725 + 15.544.946.268.311 = 28.379.904.075.338 VND / 1e12 = 28.379904075338 nghìn tỷ đồng`
- **bảng gold CẦN (3):** ['DCM_financial_statements_2016_consolidated|7', 'DPM_financial_statements_2016_consolidated|6', 'GVR_financial_statements_2016_consolidated|9']
- **bảng đã CHO XEM (3):** ['AAA_financial_statements_2016_consolidated|4', 'DPM_financial_statements_2016_consolidated|6', 'DCM_financial_statements_2016_consolidated|7']
- bảng đã retrieve (25): ['AAA_financial_statements_2016_consolidated|4', 'DPM_financial_statements_2016_consolidated|6', 'DCM_financial_statements_2016_consolidated|7', 'GVR_financial_statements_2016_consolidated|9', 'AAA_financial_statements_2016_consolidated|30', 'DPM_financial_statements_2016_consolidated|41', 'AAA_financial_statements_2016_consolidated|5', 'DPM_financial_statements_2016_consolidated|7', 'GVR_financial_statements_2016_consolidated|8', 'DCM_financial_statements_2016_consolidated|9', 'DCM_financial_statements_2016_consolidated|8', 'DCM_financial_statements_2016_consolidated|6', 'GVR_financial_statements_2016_consolidated|60', 'GVR_financial_statements_2016_consolidated|29', 'AAA_financial_statements_2016_consolidated|2', 'GVR_financial_statements_2016_consolidated|10', 'DPM_financial_statements_2016_consolidated|5', 'GVR_financial_statements_2016_consolidated|5', 'AAA_financial_statements_2016_consolidated|3', 'GVR_financial_statements_2016_consolidated|7', 'GVR_financial_statements_2016_consolidated|11', 'DCM_financial_statements_2016_consolidated|5', 'DPM_financial_statements_2016_consolidated|8', 'DPM_financial_statements_2016_consolidated|4', 'GVR_financial_statements_2016_consolidated|6']
- ⛔ **thiếu trong prompt:** ['GVR_financial_statements_2016_consolidated|9']
- verify nói: *Câu hỏi yêu cầu tổng doanh thu thuần của các công ty có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần lớn hơn 10%, nhưng truy vấn chỉ kiểm tra điều kiện này cho công ty AAA và không tính tổng doanh thu của các công ty thỏa mãn (DCM, DPM, GVR).*
- query trước khi verify sửa: `((df1.iloc[2]["Năm 2016"] / df1.iloc[18]["Năm 2016"]) > 0.1) * 1e-12`

---

## qid 502

**Câu hỏi:** Trong các năm 2015, 2016, 2018, 2019, 2020, 2021, số dư Quỹ bình ổn giá xăng dầu gửi tại ngân hàng của PLX (báo cáo riêng) lớn nhất vào năm nào? Lãi dự thu của năm đó là bao nhiêu tỷ đồng?

- gold = `87.618442331` tỷ đồng
- pred = `1529.1990643660001`
- query = `(df1.iloc[6]["2016VND"]) * 1e-09`
- ô gold (gold ghi tay) = `Fund balances: 2015=2.185.442.448.068; 2016=1.529.199.064.366; 2018=1.372.574.859.359; 2019=1.288.147.098.093; 2020=3.944.927.175.227 (MAX); 2021=16.633.673 (VND). 2020's Lãi dự thu = 87.618.442.331 VND`
- cách tính gold = `87.618.442.331 VND / 1e9 = 87.618442331 tỷ đồng`
- **bảng gold CẦN (2):** ['PLX_financial_statements_2020_separate|35', 'PLX_financial_statements_2020_separate|12']
- **bảng đã CHO XEM (3):** ['PLX_financial_statements_2016_separate|32', 'PLX_financial_statements_2015_separate|33', 'PLX_financial_statements_2018_separate|34']
- bảng đã retrieve (45): ['PLX_financial_statements_2015_separate|33', 'PLX_financial_statements_2016_separate|32', 'PLX_financial_statements_2018_separate|34', 'PLX_financial_statements_2020_separate|35', 'PLX_financial_statements_2019_separate|11', 'PLX_financial_statements_2021_separate|11', 'PLX_financial_statements_2021_separate|8', 'PLX_financial_statements_2019_separate|8', 'PLX_financial_statements_2020_separate|6', 'PLX_financial_statements_2016_separate|4', 'PLX_financial_statements_2015_separate|5', 'PLX_financial_statements_2019_separate|6', 'PLX_financial_statements_2018_separate|3', 'PLX_financial_statements_2020_separate|4', 'PLX_financial_statements_2021_separate|10', 'PLX_financial_statements_2021_separate|6', 'PLX_financial_statements_2021_separate|9', 'PLX_financial_statements_2019_separate|9', 'PLX_financial_statements_2021_separate|7', 'PLX_financial_statements_2016_separate|7', 'PLX_financial_statements_2019_separate|10', 'PLX_financial_statements_2018_separate|5', 'PLX_financial_statements_2018_separate|6', 'PLX_financial_statements_2020_separate|5', 'PLX_financial_statements_2018_separate|4', 'PLX_financial_statements_2019_separate|7', 'PLX_financial_statements_2015_separate|9', 'PLX_financial_statements_2015_separate|8', 'PLX_financial_statements_2016_separate|6', 'PLX_financial_statements_2015_separate|7', 'PLX_financial_statements_2016_separate|8', 'PLX_financial_statements_2020_separate|7', 'PLX_financial_statements_2015_separate|6', 'PLX_financial_statements_2015_separate|4', 'PLX_financial_statements_2016_separate|5', 'PLX_financial_statements_2019_separate|5', 'PLX_financial_statements_2018_separate|2', 'PLX_financial_statements_2015_separate|3', 'PLX_financial_statements_2018_separate|1', 'PLX_financial_statements_2020_separate|2', 'PLX_financial_statements_2020_separate|3', 'PLX_financial_statements_2021_separate|4', 'PLX_financial_statements_2021_separate|5', 'PLX_financial_statements_2016_separate|3', 'PLX_financial_statements_2019_separate|4']
- ⛔ **thiếu trong prompt:** ['PLX_financial_statements_2020_separate|35', 'PLX_financial_statements_2020_separate|12']
- verify nói: *Câu hỏi yêu cầu số dư lãi dự thu cuối năm, nhưng truy vấn lại lấy số dư cuối năm của quỹ bình ổn giá xăng dầu (hàng 4) thay vì số dư lãi dự thu (thường nằm ở dòng khác hoặc cần xác định đúng dòng tương ứng).*
- query trước khi verify sửa: `(df1.iloc[4]["2016VND"]) * 1e-09`

---

## qid 521

**Câu hỏi:** Trong các năm 2021, 2023, 2025, tiền và các khoản tương đương tiền cuối năm của HDG (báo cáo hợp nhất) lớn nhất vào năm nào? Chi phí lãi vay của năm đó là bao nhiêu tỷ đồng?

- gold = `299.780784516` tỷ đồng
- pred = `500.688616629`
- query = `(df2.iloc[1]["Năm nay"]) * 1e-09`
- ô gold (gold ghi tay) = `FY2021=230.395.142.669; FY2023(derived)=245.549.342.427; FY2025=265.730.670.677 (MAX) (VND). FY2025 Chi phí lãi vay=299.780.784.516 VND`
- cách tính gold = `299.780.784.516 VND / 1e9 = 299.780784516 tỷ đồng`
- **bảng gold CẦN (4):** ['HDG_financial_statements_2021_consolidated|12', 'HDG_financial_statements_2024_consolidated|10', 'HDG_financial_statements_2025_consolidated|11', 'HDG_financial_statements_2025_consolidated|51']
- **bảng đã CHO XEM (3):** ['HDG_financial_statements_2023_consolidated|5', 'HDG_financial_statements_2023_consolidated|49', 'HDG_financial_statements_2025_consolidated|51']
- bảng đã retrieve (27): ['HDG_financial_statements_2023_consolidated|49', 'HDG_financial_statements_2025_consolidated|51', 'HDG_financial_statements_2023_consolidated|5', 'HDG_financial_statements_2025_consolidated|4', 'HDG_financial_statements_2023_consolidated|17', 'HDG_financial_statements_2021_consolidated|5', 'HDG_financial_statements_2021_consolidated|12', 'HDG_financial_statements_2023_consolidated|12', 'HDG_financial_statements_2025_consolidated|11', 'HDG_financial_statements_2021_consolidated|9', 'HDG_financial_statements_2021_consolidated|8', 'HDG_financial_statements_2023_consolidated|8', 'HDG_financial_statements_2025_consolidated|7', 'HDG_financial_statements_2025_consolidated|8', 'HDG_financial_statements_2025_consolidated|6', 'HDG_financial_statements_2021_consolidated|6', 'HDG_financial_statements_2025_consolidated|10', 'HDG_financial_statements_2023_consolidated|9', 'HDG_financial_statements_2023_consolidated|6', 'HDG_financial_statements_2021_consolidated|7', 'HDG_financial_statements_2025_consolidated|5', 'HDG_financial_statements_2023_consolidated|7', 'HDG_financial_statements_2021_consolidated|10', 'HDG_financial_statements_2023_consolidated|11', 'HDG_financial_statements_2021_consolidated|11', 'HDG_financial_statements_2023_consolidated|10', 'HDG_financial_statements_2025_consolidated|9']
- ⛔ **thiếu trong prompt:** ['HDG_financial_statements_2021_consolidated|12', 'HDG_financial_statements_2024_consolidated|10', 'HDG_financial_statements_2025_consolidated|11']
- verify nói: *The query used row 1 from df1 (Tiền và các khoản tương đương tiền) but the question asks for Chi phí lãi vay (interest expense), which is found in df2 or df3.*
- query trước khi verify sửa: `(df1.iloc[1]["Số cuối năm"]) * 1e-09`

---

## qid 524

**Câu hỏi:** Trong các năm 2017, 2018, 2021 và 2022, số dư cuối năm quỹ khen thưởng và phúc lợi của Ngân hàng TMCP Phương Đông tại năm có giá trị cho vay các tổ chức kinh tế và cá nhân trong nước lớn nhất là bao nhiêu tỷ đồng?

- gold = `102.424` 
- pred = `1501.035778617`
- query = `(df3.iloc[15]["Unnamed: 5"]) * 1e-09`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['OCB_financial_statements_2022_consolidated_1|30', 'OCB_financial_statements_2021_consolidated|31', 'OCB_financial_statements_2018_consolidated|54']
- bảng đã retrieve (37): ['OCB_financial_statements_2022_consolidated_1|30', 'OCB_financial_statements_2021_consolidated|31', 'OCB_financial_statements_2018_consolidated|54', 'OCB_financial_statements_2017_consolidated|25', 'OCB_financial_statements_2021_consolidated|70', 'OCB_financial_statements_2017_consolidated|8', 'OCB_financial_statements_2021_consolidated|7', 'OCB_financial_statements_2021_consolidated|5', 'OCB_financial_statements_2022_consolidated_1|5', 'OCB_financial_statements_2022_consolidated_2|5', 'OCB_financial_statements_2018_consolidated|7', 'OCB_financial_statements_2022_consolidated_2|6', 'OCB_financial_statements_2022_consolidated_1|6', 'OCB_financial_statements_2021_consolidated|6', 'OCB_financial_statements_2022_consolidated_1|7', 'OCB_financial_statements_2022_consolidated_2|7', 'OCB_financial_statements_2018_consolidated|2', 'OCB_financial_statements_2018_consolidated|3', 'OCB_financial_statements_2017_consolidated|2', 'OCB_financial_statements_2017_consolidated|3', 'OCB_financial_statements_2018_consolidated|6', 'OCB_financial_statements_2017_consolidated|9', 'OCB_financial_statements_2017_consolidated|7', 'OCB_financial_statements_2018_consolidated|4', 'OCB_financial_statements_2018_consolidated|8', 'OCB_financial_statements_2018_consolidated|5', 'OCB_financial_statements_2022_consolidated_1|9', 'OCB_financial_statements_2022_consolidated_2|9', 'OCB_financial_statements_2017_consolidated|6', 'OCB_financial_statements_2021_consolidated|9', 'OCB_financial_statements_2021_consolidated|8', 'OCB_financial_statements_2017_consolidated|5', 'OCB_financial_statements_2022_consolidated_1|8', 'OCB_financial_statements_2022_consolidated_2|8', 'OCB_financial_statements_2022_consolidated_1|10', 'OCB_financial_statements_2022_consolidated_2|10', 'OCB_financial_statements_2021_consolidated|10']
- verify nói: *Câu hỏi yêu cầu số dư cuối năm quỹ khen thưởng và phúc lợi, nhưng truy vấn lại lấy giá trị dòng "Trích lập quỹ khen thưởng và phúc lợi" (dòng 7) thay vì dòng "Số dư tại ngày 31 tháng 12 năm 2018" (dòng 15) trong cùng bảng df3.*
- query trước khi verify sửa: `(df3.iloc[7]["Unnamed: 5"]) * 1e-09`

---

## qid 525

**Câu hỏi:** Trong các năm 2017, 2019 và 2022, tổng số dư dự phòng rủi ro cho vay khách hàng cuối năm của Ngân hàng TMCP Phương Đông, công ty mẹ, tại năm có số thuế thu nhập doanh nghiệp phải nộp trong năm cao nhất là bao nhiêu nghìn tỷ đồng?

- gold = `1.582259850422` nghìn tỷ đồng
- pred = `0.512532145711`
- query = `(df2.iloc[2]["2019VND"]) * 1e-12`
- ô gold (gold ghi tay) = `(1.582.259.850.422)`
- cách tính gold = `So sánh thuế TNDN phải nộp phát sinh trong năm (từ thuyết minh Thuế và các khoản phải nộp NSNN) qua 3 năm: 2017=204.381.067.054 VND (table_61), 2019=648.727.468.950 VND (table_59), 2022=879.589.703.439 VND (table_76, giống nhau ở cả _1 và _2) - năm 2022 CAO NHẤT. Dư nợ dự phòng rủi ro cho vay khách hàng cuối năm 2022 (BCTC riêng công ty mẹ, bảng cân đối kế toán table_5) = 1.582.259.850.422 VND (giá trị âm trên bảng vì là khoản giảm trừ tài sản, lấy giá trị tuyệt đối) / 1e12 = 1.582259850422 nghìn tỷ đồng`
- **bảng gold CẦN (1):** ['OCB_financial_statements_2022_separate_1|5']
- **bảng đã CHO XEM (3):** ['OCB_financial_statements_2017_separate|9', 'OCB_financial_statements_2019_separate|33', 'OCB_financial_statements_2019_separate|74']
- bảng đã retrieve (31): ['OCB_financial_statements_2019_separate|33', 'OCB_financial_statements_2017_separate|9', 'OCB_financial_statements_2019_separate|74', 'OCB_financial_statements_2017_separate|10', 'OCB_financial_statements_2022_separate_2|5', 'OCB_financial_statements_2022_separate_1|5', 'OCB_financial_statements_2017_separate|6', 'OCB_financial_statements_2019_separate|2', 'OCB_financial_statements_2019_separate|8', 'OCB_financial_statements_2017_separate|2', 'OCB_financial_statements_2019_separate|6', 'OCB_financial_statements_2022_separate_1|6', 'OCB_financial_statements_2022_separate_2|6', 'OCB_financial_statements_2022_separate_1|9', 'OCB_financial_statements_2022_separate_1|8', 'OCB_financial_statements_2022_separate_2|8', 'OCB_financial_statements_2019_separate|10', 'OCB_financial_statements_2017_separate|7', 'OCB_financial_statements_2019_separate|7', 'OCB_financial_statements_2022_separate_1|7', 'OCB_financial_statements_2022_separate_2|7', 'OCB_financial_statements_2019_separate|11', 'OCB_financial_statements_2019_separate|3', 'OCB_financial_statements_2017_separate|3', 'OCB_financial_statements_2017_separate|12', 'OCB_financial_statements_2019_separate|13', 'OCB_financial_statements_2022_separate_1|10', 'OCB_financial_statements_2022_separate_2|10', 'OCB_financial_statements_2022_separate_2|9', 'OCB_financial_statements_2019_separate|5', 'OCB_financial_statements_2017_separate|5']
- ⛔ **thiếu trong prompt:** ['OCB_financial_statements_2022_separate_1|5']
- verify nói: *Câu hỏi yêu cầu số dư dự phòng rủi ro cho vay khách hàng cuối năm của năm có thuế TNDN phải nộp cao nhất trong các năm 2017, 2019 và 2022, nhưng truy vấn chỉ lấy số dư cuối năm của năm 2019 mà không so sánh thuế TNDN của 3 năm để tìm năm có thuế cao nhất.*
- query trước khi verify sửa: `(df2.iloc[2]["2019VND"]) * 1e-12`

---

## qid 526

**Câu hỏi:** Trong các năm 2023, 2024 và 2025, chi phí khác của CTCP Đầu tư Thế giới Di động trong năm có Lãi cơ bản và suy giảm trên mỗi cổ phiếu lớn nhất là bao nhiêu tỷ đồng?

- gold = `83.790676915` tỷ đồng
- pred = `-83.790676915`
- query = `(df1.iloc[13]["Năm nay"]) * 1e-09`
- ô gold (gold ghi tay) = `(83.790.676.915)`
- cách tính gold = `83.790.676.915 VND / 1e9 = 83.790676915 tỷ đồng`
- **bảng gold CẦN (1):** ['MWG_financial_statements_2025_consolidated|7']
- **bảng đã CHO XEM (3):** ['MWG_financial_statements_2025_consolidated|7', 'MWG_financial_statements_2024_consolidated|7', 'MWG_financial_statements_2023_consolidated|7']
- bảng đã retrieve (15): ['MWG_financial_statements_2025_consolidated|7', 'MWG_financial_statements_2024_consolidated|7', 'MWG_financial_statements_2023_consolidated|7', 'MWG_financial_statements_2025_consolidated|9', 'MWG_financial_statements_2024_consolidated|9', 'MWG_financial_statements_2023_consolidated|9', 'MWG_financial_statements_2023_consolidated|8', 'MWG_financial_statements_2023_consolidated|6', 'MWG_financial_statements_2023_consolidated|5', 'MWG_financial_statements_2025_consolidated|6', 'MWG_financial_statements_2024_consolidated|5', 'MWG_financial_statements_2024_consolidated|6', 'MWG_financial_statements_2025_consolidated|8', 'MWG_financial_statements_2024_consolidated|8', 'MWG_financial_statements_2025_consolidated|5']
- verify nói: *Câu hỏi yêu cầu tìm chi phí khác trong năm có Lãi cơ bản trên cổ phiếu lớn nhất, nhưng truy vấn chỉ lấy giá trị chi phí khác của năm 2025 mà không kiểm tra điều kiện về EPS.*
- query trước khi verify sửa: `(df1.iloc[13]["Năm nay"]) * 1e-09`

---

## qid 530

**Câu hỏi:** Số dư nợ đủ tiêu chuẩn của Ngân hàng TMCP Nam Á tại cuối năm có số dư cuối kỳ chi phí xây dựng cơ bản dở dang cao nhất trong các năm 2021, 2022, 2023, 2024 và 2025 là bao nhiêu nghìn tỷ đồng?

- gold = `190.759675` nghìn tỷ đồng
- pred = `1.3323485e-05`
- query = `(df1.iloc[0]["Số cuối nămTriệu đồng"]) * 1e-12`
- ô gold (gold ghi tay) = `190.759.675`
- cách tính gold = `190.759.675 triệu VND / 1000 = 190.759675 nghìn tỷ đồng`
- **bảng gold CẦN (1):** ['NAB_financial_statements_2025_consolidated|30']
- **bảng đã CHO XEM (3):** ['NAB_financial_statements_2023_consolidated_1|25', 'NAB_financial_statements_2023_consolidated_2|25', 'NAB_financial_statements_2024_consolidated|28']
- bảng đã retrieve (52): ['NAB_financial_statements_2023_consolidated_1|25', 'NAB_financial_statements_2023_consolidated_2|25', 'NAB_financial_statements_2024_consolidated|28', 'NAB_financial_statements_2025_consolidated|26', 'NAB_financial_statements_2022_consolidated_1|35', 'NAB_financial_statements_2022_consolidated_2|35', 'NAB_financial_statements_2023_consolidated_1|29', 'NAB_financial_statements_2023_consolidated_2|29', 'NAB_financial_statements_2025_consolidated|30', 'NAB_financial_statements_2024_consolidated|32', 'NAB_financial_statements_2021_consolidated|9', 'NAB_financial_statements_2023_consolidated_1|6', 'NAB_financial_statements_2023_consolidated_2|6', 'NAB_financial_statements_2022_consolidated_1|6', 'NAB_financial_statements_2022_consolidated_2|6', 'NAB_financial_statements_2024_consolidated|6', 'NAB_financial_statements_2025_consolidated|4', 'NAB_financial_statements_2023_consolidated_1|8', 'NAB_financial_statements_2023_consolidated_2|8', 'NAB_financial_statements_2022_consolidated_1|8', 'NAB_financial_statements_2022_consolidated_2|8', 'NAB_financial_statements_2021_consolidated|5', 'NAB_financial_statements_2025_consolidated|6', 'NAB_financial_statements_2021_consolidated|7', 'NAB_financial_statements_2024_consolidated|8', 'NAB_financial_statements_2025_consolidated|8', 'NAB_financial_statements_2025_consolidated|5', 'NAB_financial_statements_2025_consolidated|7', 'NAB_financial_statements_2024_consolidated|7', 'NAB_financial_statements_2022_consolidated_1|7', 'NAB_financial_statements_2022_consolidated_2|7', 'NAB_financial_statements_2021_consolidated|8', 'NAB_financial_statements_2022_consolidated_1|10', 'NAB_financial_statements_2024_consolidated|5', 'NAB_financial_statements_2022_consolidated_1|5', 'NAB_financial_statements_2022_consolidated_2|5', 'NAB_financial_statements_2023_consolidated_1|7', 'NAB_financial_statements_2023_consolidated_2|7', 'NAB_financial_statements_2023_consolidated_1|5', 'NAB_financial_statements_2023_consolidated_2|5', 'NAB_financial_statements_2022_consolidated_2|10', 'NAB_financial_statements_2023_consolidated_1|10', 'NAB_financial_statements_2023_consolidated_2|10', 'NAB_financial_statements_2021_consolidated|4', 'NAB_financial_statements_2022_consolidated_1|9', 'NAB_financial_statements_2022_consolidated_2|9', 'NAB_financial_statements_2025_consolidated|3', 'NAB_financial_statements_2021_consolidated|6', 'NAB_financial_statements_2024_consolidated|9', 'NAB_financial_statements_2023_consolidated_1|9', 'NAB_financial_statements_2023_consolidated_2|9', 'NAB_financial_statements_2024_consolidated|10']
- ⛔ **thiếu trong prompt:** ['NAB_financial_statements_2025_consolidated|30']
- verify nói: *Câu hỏi yêu cầu tìm số dư nợ đủ tiêu chuẩn vào cuối năm có chi phí xây dựng cơ bản dở dang cao nhất trong giai đoạn 2021-2025, nhưng truy vấn chỉ lấy giá trị năm 2023 từ bảng báo cáo 2023 mà không so sánh với các năm khác.*
- query trước khi verify sửa: `(df1.iloc[0]["Số cuối nămTriệu đồng"]) * 1e-6`

---

## qid 542

**Câu hỏi:** Trong số CTCP Phân bón Dầu khí Cà Mau, Tổng CTCP Phân bón và Hóa chất Dầu khí, Tập đoàn Công nghiệp Cao su Việt Nam và CTCP Sản xuất Kinh doanh Xuất nhập khẩu Dịch vụ và Đầu tư Tân Bình, mức thay đổi trung bình từ năm 2021 đến năm 2022 của tỷ lệ lợi nhuận gộp trên doanh thu thuần tại các công ty có doanh thu thuần năm 2022 tăng so với năm 2021 là bao nhiêu điểm phần trăm?

- gold = `6.145490424149973` điểm phần trăm
- pred = `0.2217911773530602`
- query = `((df1.iloc[2]["Năm nay"] - df1.iloc[2]["Năm trước"]) / df1.iloc[2]["Năm nay"] + (df1.iloc[4]["Năm nay"] - df1.iloc[4]["Năm trước"]) / df1.iloc[4]["Năm nay"] + (df1.iloc[6]["Năm nay"] - df1.iloc[6]["Năm trước"]) / df1.iloc[6]["Năm nay"] + (df1.iloc[8]["Năm nay"] - df1.iloc[8]["Năm trước"]) / df1.iloc[8]["Năm nay"]) / 4`
- ô gold (gold ghi tay) = `DCM 2021: DTT=9.869.762.904.637, LNG=2.780.936.924.312; DCM 2022: DTT=15.924.526.874.399, LNG=5.703.429.442.168; DPM 2021: DTT=12.786.141.193.352, LNG=4.785.538.755.035; DPM 2022: DTT=18.627.179.544.265, LNG=7.838.219.881.452`
- cách tính gold = `Biên LNG = LNG/DTT*100. DCM: 2021=28.176329575307868%, 2022=35.81537766963171%, thay đổi=+7.63904809432384pp. DPM: 2021=37.427545047939745%, 2022=42.07947780191585%, thay đổi=+4.651932753976105pp. GVR bị loại vì doanh thu 2022 (25.425.943.612.070) giảm so với 2021 (26.189.593.001.148), không thỏa điều kiện tăng trưởng doanh thu. Trung bình DCM+DPM = (7.63904809432384+4.651932753976105)/2 = 6.145490424149973 điểm phần trăm`
- **bảng gold CẦN (4):** ['DCM_financial_statements_2021_consolidated|4', 'DCM_financial_statements_2022_consolidated|6', 'DPM_financial_statements_2021_consolidated|8', 'DPM_financial_statements_2022_consolidated|9']
- **bảng đã CHO XEM (3):** ['DPM_financial_statements_2022_consolidated|9', 'DPM_financial_statements_2021_consolidated|43', 'DPM_financial_statements_2022_consolidated|48']
- bảng đã retrieve (42): ['DPM_financial_statements_2022_consolidated|48', 'DPM_financial_statements_2021_consolidated|43', 'DPM_financial_statements_2022_consolidated|9', 'GVR_financial_statements_2021_consolidated|9', 'DCM_financial_statements_2022_consolidated|6', 'DCM_financial_statements_2021_consolidated|4', 'DCM_financial_statements_2022_consolidated|1', 'GVR_financial_statements_2022_consolidated|10', 'DPM_financial_statements_2021_consolidated|8', 'DCM_financial_statements_2021_consolidated|1', 'GVR_financial_statements_2021_consolidated|26', 'DPM_financial_statements_2022_consolidated|8', 'GVR_financial_statements_2021_consolidated|8', 'GVR_financial_statements_2022_consolidated|9', 'GVR_financial_statements_2021_consolidated|11', 'GVR_financial_statements_2022_consolidated|11', 'DPM_financial_statements_2021_consolidated|7', 'GVR_financial_statements_2022_consolidated|6', 'GVR_financial_statements_2021_consolidated|10', 'GVR_financial_statements_2021_consolidated|5', 'DPM_financial_statements_2021_consolidated|10', 'GVR_financial_statements_2022_consolidated|12', 'DCM_financial_statements_2022_consolidated|7', 'DCM_financial_statements_2021_consolidated|3', 'DCM_financial_statements_2022_consolidated|8', 'DPM_financial_statements_2022_consolidated|11', 'GVR_financial_statements_2022_consolidated|7', 'DPM_financial_statements_2021_consolidated|9', 'DCM_financial_statements_2021_consolidated|5', 'GVR_financial_statements_2021_consolidated|7', 'DCM_financial_statements_2022_consolidated|5', 'GVR_financial_statements_2022_consolidated|8', 'DPM_financial_statements_2021_consolidated|4', 'DPM_financial_statements_2022_consolidated|5', 'GVR_financial_statements_2021_consolidated|6', 'DCM_financial_statements_2021_consolidated|2', 'DPM_financial_statements_2022_consolidated|10', 'DCM_financial_statements_2022_consolidated|4', 'DPM_financial_statements_2021_consolidated|5', 'DPM_financial_statements_2022_consolidated|6', 'DPM_financial_statements_2021_consolidated|6', 'DPM_financial_statements_2022_consolidated|7']
- ⛔ **thiếu trong prompt:** ['DCM_financial_statements_2021_consolidated|4', 'DCM_financial_statements_2022_consolidated|6', 'DPM_financial_statements_2021_consolidated|8']
- verify nói: *Câu hỏi yêu cầu tính mức thay đổi trung bình của tỷ lệ lợi nhuận gộp trên doanh thu thuần cho 4 công ty có doanh thu tăng, nhưng truy vấn chỉ tính tỷ lệ này cho một công ty (DPM) và không tính tỷ lệ lợi nhuận gộp/doanh thu thuần.*
- query trước khi verify sửa: `(df1.iloc[2]["Năm nay"] - df1.iloc[4]["Năm nay"]) / df1.iloc[2]["Năm nay"] * 100`

---

## qid 553

**Câu hỏi:** Trong nhóm BSR, PLX và PVT năm 2019, công ty có tỷ lệ nợ phải trả trên vốn chủ sở hữu cao nhất có tỷ lệ tổng của lợi nhuận trước thuế và chi phí lãi vay trên chi phí lãi vay là bao nhiêu lần?

- gold = `8.138020523057806` lần
- pred = `0.0`
- query = `(df1.iloc[0]["Số cuối năm"] / df1.iloc[15]["Số cuối năm"] > df3.iloc[0]["Số cuối năm"] / df3.iloc[18]["Số cuối năm"]) and (df1.iloc[0]["Số cuối năm"] / df1.iloc[15]["Số cuối năm"] > df3.iloc[0]["Số cuối năm"] / df3.iloc[18]["Số cuối năm"])`
- ô gold (gold ghi tay) = `LNTT=5.647.771.555.645; Chi phí lãi vay=791.223.776.592`
- cách tính gold = `So sánh tỉ lệ Nợ/Vốn chủ sở hữu (D/E) năm 2019 của BSR, PLX, PVT (hợp nhất): BSR: Nợ=19.530.395.992.348/VCSH=34.053.597.003.711=0.5735193257328931; PLX: Nợ=35.839.092.885.841/VCSH=25.923.320.952.118=1.382503921933384 (CAO NHẤT); PVT: Nợ=5.306.332.886.400/VCSH=5.690.965.790.904=0.932413421792349. Hệ số khả năng trả lãi vay của PLX = (LNTT + Chi phí lãi vay)/Chi phí lãi vay = (5.647.771.555.645 + 791.223.776.592)/791.223.776.592 = 8.138020523057806 lần`
- **bảng gold CẦN (2):** ['PLX_financial_statements_2019_consolidated|10', 'PLX_financial_statements_2019_consolidated|8']
- **bảng đã CHO XEM (3):** ['BSR_financial_statements_2019_consolidated|4', 'BSR_financial_statements_2019_consolidated|5', 'PVT_financial_statements_2019_consolidated|6']
- bảng đã retrieve (21): ['BSR_financial_statements_2019_consolidated|5', 'BSR_financial_statements_2019_consolidated|4', 'PVT_financial_statements_2019_consolidated|6', 'PLX_financial_statements_2019_consolidated|8', 'PLX_financial_statements_2019_consolidated|10', 'PVT_financial_statements_2019_consolidated|7', 'PLX_financial_statements_2019_consolidated|12', 'PLX_financial_statements_2019_consolidated|9', 'PVT_financial_statements_2019_consolidated|8', 'PLX_financial_statements_2019_consolidated|11', 'PLX_financial_statements_2019_consolidated|7', 'BSR_financial_statements_2019_consolidated|6', 'PLX_financial_statements_2019_consolidated|13', 'PVT_financial_statements_2019_consolidated|9', 'PLX_financial_statements_2019_consolidated|6', 'PLX_financial_statements_2019_consolidated|4', 'BSR_financial_statements_2019_consolidated|3', 'PVT_financial_statements_2019_consolidated|5', 'PVT_financial_statements_2019_consolidated|4', 'BSR_financial_statements_2019_consolidated|7', 'PLX_financial_statements_2019_consolidated|5']
- ⛔ **thiếu trong prompt:** ['PLX_financial_statements_2019_consolidated|10', 'PLX_financial_statements_2019_consolidated|8']
- verify nói: *The question asks for a financial ratio (EBITDA/Interest Expense) for the company with the highest Debt/Equity ratio, but the query returned the total liabilities (Nợ phải trả) from the balance sheet instead of calculating the required ratio.*
- query trước khi verify sửa: `df1.iloc[0]["Số cuối năm"]`

---

## qid 555

**Câu hỏi:** Trong giai đoạn 2022–2024 của CTCP Tập đoàn C.E.O (CEO), xét các năm có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần lớn hơn 10%, doanh thu thuần thấp nhất là bao nhiêu nghìn tỷ đồng?

- gold = `1.307936213643` nghìn tỷ đồng
- pred = `0.0`
- query = `pd.to_numeric(df1.iloc[18]["Năm 2022"], errors="coerce") / 1e9`
- ô gold (gold ghi tay) = `1.307.936.213.643`
- cách tính gold = `1.307.936.213.643 VND / 1e12 = 1.307936213643 nghìn tỷ đồng`
- **bảng gold CẦN (1):** ['CEO_financial_statements_2024_consolidated|6']
- **bảng đã CHO XEM (3):** ['CEO_financial_statements_2022_consolidated|5', 'CEO_financial_statements_2023_consolidated|5', 'CEO_financial_statements_2024_consolidated|6']
- bảng đã retrieve (15): ['CEO_financial_statements_2022_consolidated|5', 'CEO_financial_statements_2023_consolidated|5', 'CEO_financial_statements_2024_consolidated|6', 'CEO_financial_statements_2024_consolidated|8', 'CEO_financial_statements_2024_consolidated|5', 'CEO_financial_statements_2022_consolidated|6', 'CEO_financial_statements_2022_consolidated|7', 'CEO_financial_statements_2023_consolidated|7', 'CEO_financial_statements_2023_consolidated|4', 'CEO_financial_statements_2024_consolidated|7', 'CEO_financial_statements_2022_consolidated|4', 'CEO_financial_statements_2024_consolidated|4', 'CEO_financial_statements_2022_consolidated|3', 'CEO_financial_statements_2023_consolidated|6', 'CEO_financial_statements_2023_consolidated|3']

---

## qid 582

**Câu hỏi:** Tăng trưởng khoản vay ngắn hạn của MCH từ cuối năm 2021 đến cuối năm 2023 là bao nhiêu %?

- gold = `13.75` 
- pred = `-381.8421980335904`
- query = `(df2.iloc[1]["31/12/2023Giá trị ghi sổ/Số có khả năngtrả nợVND"] - df1.iloc[15]["31/12/2021VND"]) / df1.iloc[15]["31/12/2021VND"] * 100`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['MCH_financial_statements_2021_consolidated|18', 'MCH_financial_statements_2023_consolidated|42', 'MCH_financial_statements_2021_consolidated|45']
- bảng đã retrieve (29): ['MCH_financial_statements_2021_consolidated|45', 'MCH_financial_statements_2023_consolidated|42', 'MCH_financial_statements_2021_consolidated|18', 'MCH_financial_statements_2022_consolidated|42', 'MCH_financial_statements_2023_consolidated|10', 'MCH_financial_statements_2023_consolidated|8', 'MCH_financial_statements_2022_consolidated|9', 'MCH_financial_statements_2022_consolidated|7', 'MCH_financial_statements_2023_consolidated|6', 'MCH_financial_statements_2023_consolidated|9', 'MCH_financial_statements_2021_consolidated|8', 'MCH_financial_statements_2022_consolidated|3', 'MCH_financial_statements_2022_consolidated|1', 'MCH_financial_statements_2021_consolidated|4', 'MCH_financial_statements_2022_consolidated|5', 'MCH_financial_statements_2021_consolidated|6', 'MCH_financial_statements_2023_consolidated|4', 'MCH_financial_statements_2023_consolidated|2', 'MCH_financial_statements_2023_consolidated|7', 'MCH_financial_statements_2021_consolidated|7', 'MCH_financial_statements_2021_consolidated|5', 'MCH_financial_statements_2021_consolidated|2', 'MCH_financial_statements_2022_consolidated|8', 'MCH_financial_statements_2023_consolidated|5', 'MCH_financial_statements_2022_consolidated|6', 'MCH_financial_statements_2022_consolidated|4', 'MCH_financial_statements_2021_consolidated|3', 'MCH_financial_statements_2022_consolidated|2', 'MCH_financial_statements_2023_consolidated|3']
- verify nói: *Câu hỏi yêu cầu số liệu từ cuối năm 2021 và cuối năm 2023, nhưng truy vấn đã sử dụng cột "31/12/2021" từ df3 (có giá trị âm do cách trình bày của bảng biến động) thay vì cột "31/12/2021" từ bảng tài sản (df1) hoặc cột "31/12/2023" từ bảng biến động (df2) để tính toán đúng.*
- query trước khi verify sửa: `(df2.iloc[1]["31/12/2023Giá trị ghi sổ/Số có khả năngtrả nợVND"] - df3.iloc[1]["31/12/2021Giá trị ghi sổ/Số có khả năngtrả nợVND"]) / df3.iloc[1]["31/12/2021Giá trị ghi sổ/Số có khả năngtrả nợVND"] * 100`

---

## qid 635

**Câu hỏi:** Tính tỷ lệ tăng % cho vay và phải thu của tài sản tài chính trong hoạt động cho vay khách hàng của công ty mẹ ABB từ cuối năm 2020 đến cuối năm 2023 là bao nhiêu phần trăm?

- gold = `55.004431680135504` %
- pred = `56.75071462942445`
- query = `(df2.iloc[8]["Số cuối năm Triệu đồng"] - df1.iloc[10]["Số cuối năm Triệu đồng"]) / df1.iloc[10]["Số cuối năm Triệu đồng"] * 100`
- ô gold (gold ghi tay) = `Cuối 2020: 63.293.151 triệu đồng; Cuối 2023: 98.107.189 triệu đồng`
- cách tính gold = `(98107189 - 63293151) / 63293151 * 100 = 55.004431680135504`
- **bảng gold CẦN (2):** ['ABB_financial_statements_2020_separate|4', 'ABB_financial_statements_2023_separate|5']
- **bảng đã CHO XEM (3):** ['ABB_financial_statements_2020_separate|4', 'ABB_financial_statements_2023_separate|5', 'ABB_financial_statements_2021_separate|9']
- bảng đã retrieve (24): ['ABB_financial_statements_2023_separate|5', 'ABB_financial_statements_2020_separate|4', 'ABB_financial_statements_2021_separate|9', 'ABB_financial_statements_2023_separate|9', 'ABB_financial_statements_2022_separate|9', 'ABB_financial_statements_2020_separate|8', 'ABB_financial_statements_2022_separate|5', 'ABB_financial_statements_2021_separate|5', 'ABB_financial_statements_2020_separate|9', 'ABB_financial_statements_2021_separate|10', 'ABB_financial_statements_2023_separate|10', 'ABB_financial_statements_2022_separate|10', 'ABB_financial_statements_2022_separate|7', 'ABB_financial_statements_2023_separate|7', 'ABB_financial_statements_2020_separate|7', 'ABB_financial_statements_2023_separate|6', 'ABB_financial_statements_2022_separate|6', 'ABB_financial_statements_2023_separate|8', 'ABB_financial_statements_2021_separate|8', 'ABB_financial_statements_2022_separate|8', 'ABB_financial_statements_2021_separate|6', 'ABB_financial_statements_2020_separate|5', 'ABB_financial_statements_2021_separate|7', 'ABB_financial_statements_2020_separate|6']
- verify nói: *Câu hỏi yêu cầu tính tỷ lệ tăng cho đến cuối năm 2023, nhưng truy vấn lại lấy số liệu "Số cuối năm" của năm 2020 (df1) làm mẫu số thay vì lấy số liệu của năm 2023 (df2) để so sánh với số đầu năm 2020 hoặc so sánh trực tiếp giữa cuối 2020 và cuối 2023.*
- query trước khi verify sửa: `(df2.iloc[8]["Số cuối năm Triệu đồng"] - df1.iloc[10]["Số cuối năm Triệu đồng"]) / df1.iloc[10]["Số cuối năm Triệu đồng"] * 100`

---

## qid 685

**Câu hỏi:** Tỷ lệ bao phủ nợ xấu của công ty mẹ BAB vào cuối năm 2025 là bao nhiêu phần trăm?

- gold = `107.5416601936008` %
- pred = `0.0`
- query = `df2.iloc[3]["Unnamed: 0"] / df1.iloc[4]["31/12/2025"] * 100`
- ô gold (gold ghi tay) = `Nợ dưới tiêu chuẩn=137.377; Nợ nghi ngờ=137.466; Nợ có khả năng mất vốn=1.179.903 (triệu VND, table_24); Dự phòng cụ thể=625.187, Dự phòng chung=939.271, Tổng=1.564.458 (triệu VND, table_29)`
- cách tính gold = `Nợ xấu (nhóm 3-5) = 137.377+137.466+1.179.903 = 1.454.746 triệu VND. Tổng dự phòng rủi ro cho vay = 625.187+939.271 = 1.564.458 triệu VND. Tỷ lệ bao phủ = 1.564.458/1.454.746*100 = 107.5416601936008%`
- **bảng gold CẦN (2):** ['BAB_financial_statements_2025_separate|24', 'BAB_financial_statements_2025_separate|29']
- **bảng đã CHO XEM (3):** ['BAB_financial_statements_2025_separate|25', 'BAB_financial_statements_2025_separate|61', 'BAB_financial_statements_2025_separate|71']
- bảng đã retrieve (11): ['BAB_financial_statements_2025_separate|61', 'BAB_financial_statements_2025_separate|25', 'BAB_financial_statements_2025_separate|71', 'BAB_financial_statements_2025_separate|24', 'BAB_financial_statements_2025_separate|29', 'BAB_financial_statements_2025_separate|5', 'BAB_financial_statements_2025_separate|9', 'BAB_financial_statements_2025_separate|8', 'BAB_financial_statements_2025_separate|10', 'BAB_financial_statements_2025_separate|66', 'BAB_financial_statements_2025_separate|13']
- ⛔ **thiếu trong prompt:** ['BAB_financial_statements_2025_separate|24', 'BAB_financial_statements_2025_separate|29']

---

## qid 744

**Câu hỏi:** Hiệu giữa số dư trái phiếu phát hành của công ty mẹ Ngân hàng TMCP Kiên Long và công ty mẹ Ngân hàng TMCP Xuất nhập khẩu Việt Nam cuối năm 2024 là bao nhiêu? (Đơn vị tính: Triệu đồng)

- gold = `-2880000.0` triệu đồng
- pred = `0.7999999999999999`
- query = `(df2.iloc[2]["31/12/2024"] - df3.iloc[17]["Unnamed: 4"]) * 1e-6`
- ô gold (gold ghi tay) = `KLB: 800.000 triệu đồng; EIB: 3.680.000 triệu đồng`
- cách tính gold = `800000 - 3680000 = -2880000 (KLB minus EIB, per question order)`
- **bảng gold CẦN (2):** ['KLB_financial_statements_2024_separate|42', 'EIB_financial_statements_2024_separate|54']
- **bảng đã CHO XEM (3):** ['EIB_financial_statements_2024_separate|7', 'KLB_financial_statements_2024_separate|42', 'EIB_financial_statements_2024_separate|95']
- bảng đã retrieve (17): ['KLB_financial_statements_2024_separate|42', 'EIB_financial_statements_2024_separate|95', 'EIB_financial_statements_2024_separate|7', 'EIB_financial_statements_2024_separate|3', 'EIB_financial_statements_2024_separate|6', 'EIB_financial_statements_2024_separate|4', 'EIB_financial_statements_2024_separate|5', 'KLB_financial_statements_2024_separate|7', 'EIB_financial_statements_2024_separate|8', 'KLB_financial_statements_2024_separate|4', 'KLB_financial_statements_2024_separate|8', 'KLB_financial_statements_2024_separate|10', 'KLB_financial_statements_2024_separate|2', 'KLB_financial_statements_2024_separate|9', 'KLB_financial_statements_2024_separate|5', 'KLB_financial_statements_2024_separate|3', 'KLB_financial_statements_2024_separate|6']
- ⛔ **thiếu trong prompt:** ['EIB_financial_statements_2024_separate|54']
- verify nói: *Câu hỏi yêu cầu số dư trái phiếu phát hành của EIB, nhưng truy vấn lại lấy giá trị từ dòng "Phát hành giấy tờ có giá" (row 17) thay vì dòng "Trái phiếu" (nếu có) hoặc dòng tương ứng trong bảng của EIB.*
- query trước khi verify sửa: `df2.iloc[2]["31/12/2024"] - df3.iloc[17]["Unnamed: 4"]`

---

## qid 753

**Câu hỏi:** Chênh lệch lợi nhuận thuần năm 2017 của công ty mẹ Ngân hàng TMCP Quốc tế Việt Nam và công ty mẹ Ngân hàng TMCP Hàng hải Việt Nam là bao nhiêu triệu đồng?

- gold = `571308.0` triệu đồng
- pred = `-998801.0`
- query = `df1.iloc[19]["2017 Triệu VND"] - df3.iloc[22]["Năm 2017 triệu đồng"]`
- ô gold (gold ghi tay) = `VIB: 1.754.849 triệu đồng; MSB: 1.183.541 triệu đồng`
- cách tính gold = `1754849 - 1183541 = 571308 (VIB minus MSB, per question order)`
- **bảng gold CẦN (2):** ['VIB_financial_statements_2017_separate|7', 'MSB_financial_statements_2017_separate|5']
- **bảng đã CHO XEM (3):** ['MSB_financial_statements_2017_separate|5', 'MSB_financial_statements_2017_separate|6', 'VIB_financial_statements_2017_separate|7']
- bảng đã retrieve (13): ['MSB_financial_statements_2017_separate|5', 'VIB_financial_statements_2017_separate|7', 'MSB_financial_statements_2017_separate|6', 'VIB_financial_statements_2017_separate|8', 'VIB_financial_statements_2017_separate|9', 'VIB_financial_statements_2017_separate|6', 'MSB_financial_statements_2017_separate|7', 'MSB_financial_statements_2017_separate|3', 'VIB_financial_statements_2017_separate|5', 'VIB_financial_statements_2017_separate|4', 'MSB_financial_statements_2017_separate|2', 'MSB_financial_statements_2017_separate|4', 'MSB_financial_statements_2017_separate|1']
- verify nói: **
- query trước khi verify sửa: `df1.iloc[19]["2017 Triệu VND"] - df3.iloc[22]["Năm 2017 triệu đồng"]`

---

## qid 754

**Câu hỏi:** Tính chênh lệch quy mô dư nợ cho vay khách hàng nội địa của công ty mẹ Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh so với công ty mẹ Ngân hàng TMCP An Bình vào năm 2021 theo đơn vị triệu đồng.

- gold = `116644397.0` 
- pred = `35.829682`
- query = `(df2.iloc[5]["Số cuối nămTriệu đồng"] - df3.iloc[11]["Số cuối năm"]) * 1e-6`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['HDB_financial_statements_2021_separate|9', 'ABB_financial_statements_2021_separate|32', 'ABB_financial_statements_2021_separate|35']
- bảng đã retrieve (14): ['ABB_financial_statements_2021_separate|32', 'ABB_financial_statements_2021_separate|35', 'HDB_financial_statements_2021_separate|9', 'ABB_financial_statements_2021_separate|9', 'HDB_financial_statements_2021_separate|6', 'ABB_financial_statements_2021_separate|6', 'ABB_financial_statements_2021_separate|5', 'HDB_financial_statements_2021_separate|7', 'ABB_financial_statements_2021_separate|7', 'HDB_financial_statements_2021_separate|5', 'HDB_financial_statements_2021_separate|8', 'ABB_financial_statements_2021_separate|8', 'ABB_financial_statements_2021_separate|10', 'HDB_financial_statements_2021_separate|10']
- verify nói: *Câu hỏi yêu cầu chênh lệch quy mô dư nợ cho vay khách hàng nội địa của HDB so với ABB, nhưng truy vấn chỉ lấy số liệu của ABB từ hai bảng khác nhau (một bảng tổng hợp và một bảng chi tiết) mà không lấy số liệu của HDB, dẫn đến kết quả sai.*
- query trước khi verify sửa: `df2.iloc[0]["Số cuối nămTriệu đồng"] - df3.iloc[11]["Số cuối năm"]`

---

## qid 790

**Câu hỏi:** Cuối năm 2023, tỉ trọng dư nợ ngành công nghiệp chế biến, chế tạo trên BCTC riêng của VIB chênh lệch bao nhiêu phần trăm so với BIDV?

- gold = `11.462937629600624` phần trăm
- pred = `5.03`
- query = `df3.iloc[2]["%"]`
- ô gold (gold ghi tay) = `VIB: 13.400.504 triệu VND (5,03%) / tổng 266.345.545 triệu VND; BID: 287.063.377 triệu VND (16,49%) / tổng 1.740.391.368 triệu VND`
- cách tính gold = `VIB% = 13.400.504/266.345.545*100 = 5.031247659877322%; BID% = 287.063.377/1.740.391.368*100 = 16.494185289477947%; chênh lệch = |16.494185289477947 - 5.031247659877322| = 11.462937629600624 phần trăm (khớp với chênh lệch dùng số % đã làm tròn trong báo cáo: |16,49-5,03|=11,46)`
- **bảng gold CẦN (2):** ['VIB_financial_statements_2023_separate|33', 'BID_financial_statements_2023_separate|30']
- **bảng đã CHO XEM (3):** ['VIB_financial_statements_2023_separate|9', 'VIB_financial_statements_2023_separate|10', 'VIB_financial_statements_2023_separate|33']
- bảng đã retrieve (8): ['VIB_financial_statements_2023_separate|33', 'VIB_financial_statements_2023_separate|9', 'VIB_financial_statements_2023_separate|10', 'VIB_financial_statements_2023_separate|7', 'VIB_financial_statements_2023_separate|11', 'VIB_financial_statements_2023_separate|8', 'VIB_financial_statements_2023_separate|6', 'VIB_financial_statements_2023_separate|12']
- ⛔ **thiếu trong prompt:** ['BID_financial_statements_2023_separate|30']
- verify nói: *Câu hỏi yêu cầu tính chênh lệch phần trăm giữa VIB và BIDV, nhưng truy vấn chỉ trả về một con số (5.03%) của VIB mà không có dữ liệu của BIDV để so sánh.*
- query trước khi verify sửa: `df3.iloc[2]["%"]`

---

## qid 818

**Câu hỏi:** Giá trị trung bình của tổng số dư dự phòng phải thu khó đòi cuối kỳ của FTS tại các mốc cuối năm 2018, 2020, 2021, 2023 và 2024 là bao nhiêu triệu đồng?

- gold = `145.134` 
- pred = `120.68166666666667`
- query = `((df2.iloc[10]["Số cuối năm | Số cuối năm"] + df3.iloc[9]["Số cuối năm | Số cuối năm"] + df1.iloc[13]["Số cuối năm | Số cuối năm"]) / 3) * 1e-6`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['FTS_financial_statements_2023|26', 'FTS_financial_statements_2021|27', 'FTS_financial_statements_2020|28']
- bảng đã retrieve (84): ['FTS_financial_statements_2020|28', 'FTS_financial_statements_2021|27', 'FTS_financial_statements_2023|26', 'FTS_financial_statements_2018|22', 'FTS_financial_statements_2024|22', 'FTS_financial_statements_2024|60', 'FTS_financial_statements_2020|11', 'FTS_financial_statements_2021|10', 'FTS_financial_statements_2023|1', 'FTS_financial_statements_2018|5', 'FTS_financial_statements_2024|5', 'FTS_financial_statements_2023|17', 'FTS_financial_statements_2023|8', 'FTS_financial_statements_2018|4', 'FTS_financial_statements_2018|54', 'FTS_financial_statements_2020|10', 'FTS_financial_statements_2021|9', 'FTS_financial_statements_2024|4', 'FTS_financial_statements_2023|7', 'FTS_financial_statements_2024|71', 'FTS_financial_statements_2018|8', 'FTS_financial_statements_2024|14', 'FTS_financial_statements_2020|20', 'FTS_financial_statements_2021|13', 'FTS_financial_statements_2021|19', 'FTS_financial_statements_2020|14', 'FTS_financial_statements_2018|14', 'FTS_financial_statements_2024|72', 'FTS_financial_statements_2023|55', 'FTS_financial_statements_2020|48', 'FTS_financial_statements_2023|11', 'FTS_financial_statements_2020|57', 'FTS_financial_statements_2021|50', 'FTS_financial_statements_2024|8', 'FTS_financial_statements_2021|41', 'FTS_financial_statements_2024|57', 'FTS_financial_statements_2018|11', 'FTS_financial_statements_2023|42', 'FTS_financial_statements_2023|14', 'FTS_financial_statements_2020|17', 'FTS_financial_statements_2021|16', 'FTS_financial_statements_2024|11', 'FTS_financial_statements_2024|73', 'FTS_financial_statements_2024|44', 'FTS_financial_statements_2020|46', 'FTS_financial_statements_2018|52', 'FTS_financial_statements_2021|39', 'FTS_financial_statements_2018|13', 'FTS_financial_statements_2023|54', 'FTS_financial_statements_2024|56', 'FTS_financial_statements_2018|65', 'FTS_financial_statements_2023|53', 'FTS_financial_statements_2024|55', 'FTS_financial_statements_2020|16', 'FTS_financial_statements_2024|10', 'FTS_financial_statements_2018|57', 'FTS_financial_statements_2021|15', 'FTS_financial_statements_2018|10', 'FTS_financial_statements_2023|13', 'FTS_financial_statements_2018|64', 'FTS_financial_statements_2021|51', 'FTS_financial_statements_2020|58', 'FTS_financial_statements_2020|50', 'FTS_financial_statements_2021|43', 'FTS_financial_statements_2021|52', 'FTS_financial_statements_2024|45', 'FTS_financial_statements_2023|43', 'FTS_financial_statements_2020|47', 'FTS_financial_statements_2021|40', 'FTS_financial_statements_2018|53', 'FTS_financial_statements_2021|14', 'FTS_financial_statements_2020|15', 'FTS_financial_statements_2023|12', 'FTS_financial_statements_2024|9', 'FTS_financial_statements_2018|12', 'FTS_financial_statements_2018|9', 'FTS_financial_statements_2020|18', 'FTS_financial_statements_2021|17', 'FTS_financial_statements_2023|15', 'FTS_financial_statements_2024|12', 'FTS_financial_statements_2021|18', 'FTS_financial_statements_2024|13', 'FTS_financial_statements_2020|19', 'FTS_financial_statements_2023|16']
- verify nói: *Câu hỏi yêu cầu giá trị dự phòng phải thu khó đòi cuối kỳ của năm 2024, nhưng truy vấn chỉ sử dụng dữ liệu từ các năm 2020, 2021 và 2023 (thiếu năm 2024 và lặp lại năm 2023).*
- query trước khi verify sửa: `((df1.iloc[13]["Số cuối năm | Số cuối năm"] + df2.iloc[10]["Số cuối năm | Số cuối năm"] + df3.iloc[9]["Số cuối năm | Số cuối năm"] + df1.iloc[13]["Số cuối năm | Số cuối năm"] + df1.iloc[13]["Số cuối năm | Số cuối năm"]) / 5) * 1e-6`

---

## qid 820

**Câu hỏi:** Tổng doanh thu hoạt động tài chính trung bình của Tổng Công ty cổ phần Phát triển Khu Công nghiệp công ty mẹ trong các năm 2018, 2019, 2020, 2021 và 2022 là mấy trăm tỷ đồng?

- gold = `4.069` 
- pred = `420.1400454176`
- query = `((df1.iloc[4]["Năm 2021"] + df2.iloc[4]["Năm 2022"] + df3.iloc[4]["Năm 2020"] + df3.iloc[4]["Năm 2019"] + df1.iloc[4]["Năm 2020"]) / 5) * 1e-09`
- ô gold (gold ghi tay) = `None`
- cách tính gold = `None`
- **bảng gold CẦN (0):** (gold không ghi)
- **bảng đã CHO XEM (3):** ['SNZ_financial_statements_2021_separate|7', 'SNZ_financial_statements_2022_separate|8', 'SNZ_financial_statements_2020_separate|9']
- bảng đã retrieve (26): ['SNZ_financial_statements_2022_separate|8', 'SNZ_financial_statements_2021_separate|7', 'SNZ_financial_statements_2020_separate|9', 'SNZ_financial_statements_2019_separate|10', 'SNZ_financial_statements_2018_separate|7', 'SNZ_financial_statements_2019_separate|12', 'SNZ_financial_statements_2022_separate|10', 'SNZ_financial_statements_2018_separate|9', 'SNZ_financial_statements_2022_separate|6', 'SNZ_financial_statements_2020_separate|11', 'SNZ_financial_statements_2021_separate|9', 'SNZ_financial_statements_2022_separate|9', 'SNZ_financial_statements_2020_separate|7', 'SNZ_financial_statements_2021_separate|5', 'SNZ_financial_statements_2019_separate|11', 'SNZ_financial_statements_2018_separate|6', 'SNZ_financial_statements_2019_separate|8', 'SNZ_financial_statements_2021_separate|8', 'SNZ_financial_statements_2018_separate|8', 'SNZ_financial_statements_2018_separate|5', 'SNZ_financial_statements_2019_separate|9', 'SNZ_financial_statements_2020_separate|10', 'SNZ_financial_statements_2020_separate|8', 'SNZ_financial_statements_2022_separate|7', 'SNZ_financial_statements_2021_separate|6', 'SNZ_financial_statements_2022_separate|5']
- verify nói: *Câu hỏi yêu cầu "Doanh thu hoạt động tài chính" (hàng 4 trong các bảng), nhưng truy vấn lại lấy giá trị từ hàng 5 là "Chi phí tài chính".*
- query trước khi verify sửa: `((df1.iloc[5]["Năm 2021"] + df2.iloc[5]["Năm 2022"] + df3.iloc[5]["Năm 2020"] + df3.iloc[5]["Năm 2019"] + df1.iloc[5]["Năm 2020"]) / 5) * 1e-09`

---

## qid 856

**Câu hỏi:** Trung bình lãi cơ bản trên cổ phiếu của CTCP Xây lắp Điện I (PC1) (báo cáo hợp nhất) trong các năm 2015, 2020, 2022, 2023 và 2024 là bao nhiêu VNĐ/cổ phiếu?

- gold = `2992.4` VNĐ/cổ phiếu
- pred = `8290.4`
- query = `(df1.iloc[4]["Năm 2015"] + df2.iloc[4]["Năm 2020"] + df3.iloc[1]["2021"] + df1.iloc[4]["Năm 2014"] + df1.iloc[4]["Năm 2015"]) / 5`
- ô gold (gold ghi tay) = `2015: 9179; 2020: 2682; 2022: 1519; 2023: 405; 2024: 1177 (VND/cổ phiếu)`
- cách tính gold = `(9179+2682+1519+405+1177)/5 = 14962/5 = 2992.4 VND/cổ phiếu`
- **bảng gold CẦN (5):** ['PC1_financial_statements_2015_consolidated|46', 'PC1_financial_statements_2020_consolidated|60', 'PC1_financial_statements_2022_consolidated|70', 'PC1_financial_statements_2023_consolidated|73', 'PC1_financial_statements_2024_consolidated|77']
- **bảng đã CHO XEM (3):** ['PC1_financial_statements_2015_consolidated|46', 'PC1_financial_statements_2020_consolidated|60', 'PC1_financial_statements_2022_consolidated|72']
- bảng đã retrieve (53): ['PC1_financial_statements_2015_consolidated|46', 'PC1_financial_statements_2020_consolidated|60', 'PC1_financial_statements_2022_consolidated|72', 'PC1_financial_statements_2022_consolidated|70', 'PC1_financial_statements_2015_consolidated|9', 'PC1_financial_statements_2020_consolidated|7', 'PC1_financial_statements_2024_consolidated|10', 'PC1_financial_statements_2023_consolidated|7', 'PC1_financial_statements_2022_consolidated|5', 'PC1_financial_statements_2015_consolidated|40', 'PC1_financial_statements_2024_consolidated|12', 'PC1_financial_statements_2024_consolidated|9', 'PC1_financial_statements_2023_consolidated|6', 'PC1_financial_statements_2023_consolidated|10', 'PC1_financial_statements_2024_consolidated|11', 'PC1_financial_statements_2022_consolidated|4', 'PC1_financial_statements_2020_consolidated|44', 'PC1_financial_statements_2022_consolidated|7', 'PC1_financial_statements_2023_consolidated|8', 'PC1_financial_statements_2015_consolidated|48', 'PC1_financial_statements_2015_consolidated|10', 'PC1_financial_statements_2020_consolidated|9', 'PC1_financial_statements_2015_consolidated|51', 'PC1_financial_statements_2015_consolidated|39', 'PC1_financial_statements_2020_consolidated|8', 'PC1_financial_statements_2015_consolidated|49', 'PC1_financial_statements_2015_consolidated|50', 'PC1_financial_statements_2015_consolidated|36', 'PC1_financial_statements_2015_consolidated|54', 'PC1_financial_statements_2022_consolidated|6', 'PC1_financial_statements_2024_consolidated|8', 'PC1_financial_statements_2023_consolidated|9', 'PC1_financial_statements_2015_consolidated|57', 'PC1_financial_statements_2020_consolidated|6', 'PC1_financial_statements_2020_consolidated|16', 'PC1_financial_statements_2020_consolidated|63', 'PC1_financial_statements_2023_consolidated|3', 'PC1_financial_statements_2015_consolidated|8', 'PC1_financial_statements_2020_consolidated|15', 'PC1_financial_statements_2015_consolidated|6', 'PC1_financial_statements_2022_consolidated|3', 'PC1_financial_statements_2023_consolidated|5', 'PC1_financial_statements_2020_consolidated|5', 'PC1_financial_statements_2015_consolidated|7', 'PC1_financial_statements_2024_consolidated|7', 'PC1_financial_statements_2022_consolidated|2', 'PC1_financial_statements_2015_consolidated|5', 'PC1_financial_statements_2020_consolidated|4', 'PC1_financial_statements_2024_consolidated|6', 'PC1_financial_statements_2022_consolidated|1', 'PC1_financial_statements_2023_consolidated|2', 'PC1_financial_statements_2015_consolidated|56', 'PC1_financial_statements_2023_consolidated|4']
- ⛔ **thiếu trong prompt:** ['PC1_financial_statements_2022_consolidated|70', 'PC1_financial_statements_2023_consolidated|73', 'PC1_financial_statements_2024_consolidated|77']
- verify nói: *Câu hỏi yêu cầu tính trung bình của EPS qua 5 năm (2015, 2020, 2022, 2023, 2024), nhưng truy vấn chỉ trả về giá trị EPS của năm 2015 từ df1.*
- query trước khi verify sửa: `df1.iloc[4]["Năm 2015"]`

---

## qid 868

**Câu hỏi:** Trong các năm 2015, 2017, 2018, 2022 và 2023, chi phí thuế thu nhập doanh nghiệp hiện hành của Ngân hàng TMCP Ngoại thương Việt Nam (VCB, báo cáo hợp nhất) cao nhất vào năm nào và bằng bao nhiêu tỷ đồng?

- gold = `8406.86` tỷ đồng
- pred = `8265.101`
- query = `(max(df1.iloc[10]["2022Triệu VND"], df2.iloc[11]["2023Triệu VND"])) * 1e-3`
- ô gold (gold ghi tay) = `2015: 1.495.741; 2017: 2.234.378; 2018: 3.648.356; 2022: 8.406.860 (MAX); 2023: 8.079.401 (all triệu VND)`
- cách tính gold = `Max = year 2022, 8.406.860 triệu VND = 8406.86 tỷ đồng`
- **bảng gold CẦN (1):** ['VCB_financial_statements_2022_consolidated|83']
- **bảng đã CHO XEM (3):** ['VCB_financial_statements_2022_consolidated|83', 'VCB_financial_statements_2023_consolidated|94', 'VCB_financial_statements_2023_consolidated|101']
- bảng đã retrieve (43): ['VCB_financial_statements_2023_consolidated|94', 'VCB_financial_statements_2022_consolidated|83', 'VCB_financial_statements_2023_consolidated|101', 'VCB_financial_statements_2018_consolidated|77', 'VCB_financial_statements_2017_consolidated|80', 'VCB_financial_statements_2015_consolidated|89', 'VCB_financial_statements_2023_consolidated|16', 'VCB_financial_statements_2022_consolidated|12', 'VCB_financial_statements_2022_consolidated|90', 'VCB_financial_statements_2017_consolidated|86', 'VCB_financial_statements_2018_consolidated|10', 'VCB_financial_statements_2017_consolidated|15', 'VCB_financial_statements_2023_consolidated|15', 'VCB_financial_statements_2023_consolidated|17', 'VCB_financial_statements_2023_consolidated|18', 'VCB_financial_statements_2022_consolidated|11', 'VCB_financial_statements_2018_consolidated|11', 'VCB_financial_statements_2018_consolidated|9', 'VCB_financial_statements_2022_consolidated|13', 'VCB_financial_statements_2022_consolidated|14', 'VCB_financial_statements_2018_consolidated|12', 'VCB_financial_statements_2023_consolidated|14', 'VCB_financial_statements_2017_consolidated|16', 'VCB_financial_statements_2017_consolidated|14', 'VCB_financial_statements_2023_consolidated|11', 'VCB_financial_statements_2017_consolidated|17', 'VCB_financial_statements_2023_consolidated|12', 'VCB_financial_statements_2015_consolidated|9', 'VCB_financial_statements_2015_consolidated|8', 'VCB_financial_statements_2022_consolidated|8', 'VCB_financial_statements_2022_consolidated|7', 'VCB_financial_statements_2015_consolidated|5', 'VCB_financial_statements_2015_consolidated|10', 'VCB_financial_statements_2017_consolidated|11', 'VCB_financial_statements_2022_consolidated|10', 'VCB_financial_statements_2015_consolidated|11', 'VCB_financial_statements_2018_consolidated|6', 'VCB_financial_statements_2015_consolidated|6', 'VCB_financial_statements_2017_consolidated|12', 'VCB_financial_statements_2015_consolidated|7', 'VCB_financial_statements_2018_consolidated|7', 'VCB_financial_statements_2018_consolidated|8', 'VCB_financial_statements_2017_consolidated|13']
- verify nói: *Câu hỏi yêu cầu tìm mức thuế lớn nhất trong các năm 2015, 2017, 2018, 2022 và 2023, nhưng truy vấn chỉ lấy giá trị của năm 2022 từ bảng báo cáo 2022 mà không so sánh với các năm khác.*
- query trước khi verify sửa: `(df1.iloc[10]["2022Triệu VND"]) * 1e-3`

---

## qid 878

**Câu hỏi:** Trong các năm 2015, 2017 và 2019, giá trị còn lại cuối năm của bất động sản đầu tư (nhà xưởng) của Tổng Công ty Phát triển Đô thị Kinh Bắc (KBC, báo cáo hợp nhất) cao nhất vào năm nào?

- gold = `2019.0` năm
- pred = `432718621923.0`
- query = `max(df1.iloc[11]["Đơn vị tính: VND"], df2.iloc[13]["Đơn vị tính: VND"], df3.iloc[13]["Đơn vị tính: VND"])`
- ô gold (gold ghi tay) = `2015: 20.415.184.100; 2017: 134.884.233.798; 2019: 432.718.621.923 (MAX) (VND)`
- cách tính gold = `Max carrying value at year-end 2019`
- **bảng gold CẦN (1):** ['KBC_financial_statements_2019_consolidated|25']
- **bảng đã CHO XEM (3):** ['KBC_financial_statements_2017_consolidated|21', 'KBC_financial_statements_2019_consolidated|25', 'KBC_financial_statements_2015_consolidated|27']
- bảng đã retrieve (25): ['KBC_financial_statements_2019_consolidated|25', 'KBC_financial_statements_2017_consolidated|21', 'KBC_financial_statements_2015_consolidated|27', 'KBC_financial_statements_2019_consolidated|5', 'KBC_financial_statements_2015_consolidated|6', 'KBC_financial_statements_2017_consolidated|4', 'KBC_financial_statements_2019_consolidated|7', 'KBC_financial_statements_2015_consolidated|8', 'KBC_financial_statements_2017_consolidated|6', 'KBC_financial_statements_2015_consolidated|5', 'KBC_financial_statements_2015_consolidated|10', 'KBC_financial_statements_2019_consolidated|4', 'KBC_financial_statements_2017_consolidated|3', 'KBC_financial_statements_2015_consolidated|12', 'KBC_financial_statements_2017_consolidated|8', 'KBC_financial_statements_2015_consolidated|11', 'KBC_financial_statements_2015_consolidated|7', 'KBC_financial_statements_2019_consolidated|6', 'KBC_financial_statements_2017_consolidated|9', 'KBC_financial_statements_2019_consolidated|8', 'KBC_financial_statements_2015_consolidated|9', 'KBC_financial_statements_2019_consolidated|9', 'KBC_financial_statements_2017_consolidated|5', 'KBC_financial_statements_2017_consolidated|7', 'KBC_financial_statements_2019_consolidated|10']
- verify nói: *Câu hỏi yêu cầu so sánh giá trị còn lại cuối năm của bất động sản đầu tư (nhà xưởng) trong các năm 2015, 2017 và 2019 để tìm năm có giá trị lớn nhất, nhưng truy vấn chỉ trả về giá trị cho năm 2017 mà không lấy dữ liệu của 2015 và 2019 để so sánh.*
- query trước khi verify sửa: `df1.iloc[11]["Đơn vị tính: VND"]`

---

## qid 920

**Câu hỏi:** Tổng giá trị đầu tư vào công ty liên kết của Tổng Công ty Lâm nghiệp Việt Nam - CTCP (VIF), Tập đoàn Công nghiệp Cao su Việt Nam - CTCP (GVR) và Tổng công ty Phân bón và Hóa chất Dầu khí - CTCP (DPM) vào cuối năm 2025 là bao nhiêu tỷ đồng?

- gold = `2982.289953044` tỷ đồng
- pred = `0.0`
- query = `df1.iloc[10]["Công ty Cổ phần19/5 Đoàn Hùng"] + df1.iloc[10]["Công ty Cổ phầnCờ Đồ"] + df1.iloc[10]["Công ty Cổ phầnGỗ lạng Buôn MaThuột"] + df2.iloc[4]["Unnamed: 0"]`
- ô gold (gold ghi tay) = `DPM: 31.808.865.536 VND (balance-sheet caption is exclusively 'công ty liên kết', clean). GVR: balance sheet combined caption = 1.958.492.542.280 VND, split via two note tables into associates-only table_33.csv = 1.428.587.178.733 VND (confirmed via OCR cross-match against an explicit 'CÔNG TY LIÊN KẾT' company-list header naming the same 10-11 companies) and joint-ventures table_34.csv = 529.905.363.547 VND (excluded). VIF: balance sheet combined caption ('Đầu tư vào công ty liên kết, liên doanh') = 1.521.893.908.775 VND; note 14.1 lists 22 total investees but only 6 carry non-zero book value, none of which is the one investee explicitly named 'Công ty Liên doanh...' (the only entity textually identified as a JV); no separate associates-only subtotal exists, so the full combined-caption value was used for VIF.`
- cách tính gold = `31.808.865.536 (DPM) + 1.428.587.178.733 (GVR associates-only) + 1.521.893.908.775 (VIF combined, no JV value to subtract) = 2.982.289.953.044 VND = 2982.289953044 tỷ đồng`
- **bảng gold CẦN (3):** ['DPM_financial_statements_2025_consolidated|6', 'GVR_financial_statements_2025_consolidated|33', 'VIF_financial_statements_2025_consolidated|31']
- **bảng đã CHO XEM (3):** ['VIF_financial_statements_2025_consolidated|29', 'DPM_financial_statements_2025_consolidated|33', 'DPM_financial_statements_2025_consolidated|34']
- bảng đã retrieve (36): ['DPM_financial_statements_2025_consolidated|34', 'DPM_financial_statements_2025_consolidated|33', 'VIF_financial_statements_2025_consolidated|29', 'VIF_financial_statements_2025_consolidated|30', 'VIF_financial_statements_2025_consolidated|32', 'VIF_financial_statements_2025_consolidated|31', 'GVR_financial_statements_2025_consolidated|86', 'GVR_financial_statements_2025_consolidated|117', 'GVR_financial_statements_2025_consolidated|121', 'GVR_financial_statements_2025_consolidated|10', 'VIF_financial_statements_2025_consolidated|6', 'GVR_financial_statements_2025_consolidated|134', 'GVR_financial_statements_2025_consolidated|6', 'GVR_financial_statements_2025_consolidated|9', 'GVR_financial_statements_2025_consolidated|135', 'DPM_financial_statements_2025_consolidated|6', 'VIF_financial_statements_2025_consolidated|11', 'GVR_financial_statements_2025_consolidated|125', 'DPM_financial_statements_2025_consolidated|9', 'GVR_financial_statements_2025_consolidated|11', 'GVR_financial_statements_2025_consolidated|8', 'GVR_financial_statements_2025_consolidated|98', 'DPM_financial_statements_2025_consolidated|8', 'GVR_financial_statements_2025_consolidated|5', 'VIF_financial_statements_2025_consolidated|8', 'VIF_financial_statements_2025_consolidated|10', 'DPM_financial_statements_2025_consolidated|5', 'DPM_financial_statements_2025_consolidated|11', 'VIF_financial_statements_2025_consolidated|9', 'GVR_financial_statements_2025_consolidated|112', 'VIF_financial_statements_2025_consolidated|5', 'GVR_financial_statements_2025_consolidated|7', 'DPM_financial_statements_2025_consolidated|10', 'VIF_financial_statements_2025_consolidated|12', 'VIF_financial_statements_2025_consolidated|7', 'DPM_financial_statements_2025_consolidated|7']
- ⛔ **thiếu trong prompt:** ['DPM_financial_statements_2025_consolidated|6', 'GVR_financial_statements_2025_consolidated|33', 'VIF_financial_statements_2025_consolidated|31']

---

## qid 946

**Câu hỏi:** Trong các năm 2018, 2020 và 2022, chi phí xây dựng cơ bản dở dang cuối năm của Tập đoàn Đầu tư Địa ốc No Va (NVL, báo cáo hợp nhất) cao nhất vào năm nào?

- gold = `2022.0` năm
- pred = `390960770085.0`
- query = `max(df1.iloc[18]["Tại ngày 31 tháng 12 năm"], df2.iloc[17]["Tại ngày 31 tháng 12 năm"], df3.iloc[18]["Tại ngày 31 tháng 12 năm"])`
- ô gold (gold ghi tay) = `2018: 248.217.392.159; 2020: 103.772.861.482; 2022: 390.960.770.085 (MAX) (VND)`
- cách tính gold = `Max ending CIP balance at year-end 2022`
- **bảng gold CẦN (1):** ['NVL_financial_statements_2022_consolidated|8']
- **bảng đã CHO XEM (3):** ['NVL_financial_statements_2018_consolidated|4', 'NVL_financial_statements_2020_consolidated|7', 'NVL_financial_statements_2022_consolidated|8']
- bảng đã retrieve (18): ['NVL_financial_statements_2022_consolidated|8', 'NVL_financial_statements_2020_consolidated|7', 'NVL_financial_statements_2018_consolidated|4', 'NVL_financial_statements_2018_consolidated|8', 'NVL_financial_statements_2020_consolidated|10', 'NVL_financial_statements_2020_consolidated|8', 'NVL_financial_statements_2018_consolidated|6', 'NVL_financial_statements_2022_consolidated|9', 'NVL_financial_statements_2022_consolidated|10', 'NVL_financial_statements_2018_consolidated|5', 'NVL_financial_statements_2022_consolidated|11', 'NVL_financial_statements_2020_consolidated|11', 'NVL_financial_statements_2020_consolidated|6', 'NVL_financial_statements_2020_consolidated|9', 'NVL_financial_statements_2022_consolidated|7', 'NVL_financial_statements_2022_consolidated|12', 'NVL_financial_statements_2018_consolidated|3', 'NVL_financial_statements_2018_consolidated|9']
- verify nói: *Câu hỏi yêu cầu tìm năm có số dư lớn nhất trong ba năm 2018, 2020 và 2022, nhưng truy vấn chỉ lấy giá trị của năm 2018 và 2022 rồi trừ đi, bỏ qua năm 2020 và không trả về năm có giá trị lớn nhất.*
- query trước khi verify sửa: `df1.iloc[18]["Tại ngày 31 tháng 12 năm"] - df3.iloc[18]["Tại ngày 31 tháng 12 năm"]`

---

## qid 955

**Câu hỏi:** Trung bình tỷ lệ % nợ ngắn hạn trên tổng dư nợ cho vay khách hàng tại thời điểm cuối năm 2019 của ACB, BID, MBB, STB (báo cáo riêng) là bao nhiêu?

- gold = `54.66` %
- pred = `0.5494801622412201`
- query = `(df1.iloc[0]["Số cuối nămTriệu VND"] / df1.iloc[3]["Số cuối nămTriệu VND"] + df2.iloc[0]["31/12/2019triệu đồng"] / df2.iloc[3]["31/12/2019triệu đồng"] + df3.iloc[0]["Số cuối nămTriệu đồng"] / df3.iloc[3]["Số cuối nămTriệu đồng"]) / 3`
- ô gold (gold ghi tay) = `ACB: 143.115.446/265.981.486; BID: 683.290.512/1.081.556.050; MBB: 117.047.164/239.082.993; STB: 151.947.082/288.265.973 (triệu VND)`
- cách tính gold = `ACB=143115446/265981486*100=53.806544264513214%; BID=683290512/1081556050*100=63.17661595069437%; MBB=117047164/239082993*100=48.95670851836793%; STB=151947082/288265973*100=52.71072420330373%; average=(53.806544264513214+63.17661595069437+48.95670851836793+52.71072420330373)/4=54.66264823421981%`
- **bảng gold CẦN (4):** ['ACB_financial_statements_2019_separate|27', 'BID_financial_statements_2019_separate|27', 'MBB_financial_statements_2019_separate|28', 'STB_financial_statements_2019_separate|29']
- **bảng đã CHO XEM (3):** ['BID_financial_statements_2019_separate|27', 'MBB_financial_statements_2019_separate|28', 'STB_financial_statements_2019_separate|29']
- bảng đã retrieve (30): ['STB_financial_statements_2019_separate|29', 'BID_financial_statements_2019_separate|27', 'MBB_financial_statements_2019_separate|28', 'ACB_financial_statements_2019_separate|97', 'BID_financial_statements_2019_separate|86', 'STB_financial_statements_2019_separate|31', 'BID_financial_statements_2019_separate|6', 'STB_financial_statements_2019_separate|5', 'STB_financial_statements_2019_separate|6', 'BID_financial_statements_2019_separate|5', 'MBB_financial_statements_2019_separate|5', 'ACB_financial_statements_2019_separate|6', 'ACB_financial_statements_2019_separate|2', 'MBB_financial_statements_2019_separate|9', 'MBB_financial_statements_2019_separate|6', 'ACB_financial_statements_2019_separate|3', 'BID_financial_statements_2019_separate|7', 'ACB_financial_statements_2019_separate|4', 'MBB_financial_statements_2019_separate|8', 'ACB_financial_statements_2019_separate|5', 'STB_financial_statements_2019_separate|7', 'BID_financial_statements_2019_separate|9', 'BID_financial_statements_2019_separate|8', 'STB_financial_statements_2019_separate|9', 'ACB_financial_statements_2019_separate|7', 'STB_financial_statements_2019_separate|10', 'MBB_financial_statements_2019_separate|7', 'MBB_financial_statements_2019_separate|10', 'STB_financial_statements_2019_separate|8', 'BID_financial_statements_2019_separate|10']
- ⛔ **thiếu trong prompt:** ['ACB_financial_statements_2019_separate|27']
- verify nói: *Câu hỏi yêu cầu tính tỷ trọng cho vay ngắn hạn trong tổng dư nợ cho vay khách hàng, nhưng truy vấn đã bỏ qua ngân hàng ACB (không có dữ liệu trong các df) và chỉ tính trung bình của 3 ngân hàng còn lại (BID, MBB, STB) thay vì 4 ngân hàng như yêu cầu.*
- query trước khi verify sửa: `(df1.iloc[0]["Số cuối nămTriệu VND"] / df1.iloc[3]["Số cuối nămTriệu VND"] + df2.iloc[0]["31/12/2019triệu đồng"] / df2.iloc[3]["31/12/2019triệu đồng"] + df3.iloc[0]["Số cuối nămTriệu đồng"] / df3.iloc[3]["Số cuối nămTriệu đồng"]) / 3`

---

## qid 974

**Câu hỏi:** Trong các năm 2022, 2023, 2024, 2025, giá trị tài sản giữ hộ/bảo quản của Vietinbank (CTG, báo cáo hợp nhất) lớn nhất vào năm nào?

- gold = `2024.0` năm
- pred = `132970869.0`
- query = `max(df1.iloc[4]["Số cuối năm"], df2.iloc[5]["Số cuối năm"], df3.iloc[5]["Số cuối năm"])`
- ô gold (gold ghi tay) = `2022: 105.915.412; 2023: 91.656.083; 2024: 132.970.869 (MAX); 2025: 95.027.390 (triệu VND)`
- cách tính gold = `Direct comparison of year-end totals across the 4 reports' off-balance-sheet custody/held-in-trust assets note; max is 2024 at 132.970.869 triệu VND.`
- **bảng gold CẦN (4):** ['CTG_financial_statements_2022_consolidated|82', 'CTG_financial_statements_2023_consolidated|83', 'CTG_financial_statements_2024_consolidated|83', 'CTG_financial_statements_2025_consolidated|81']
- **bảng đã CHO XEM (3):** ['CTG_financial_statements_2022_consolidated|82', 'CTG_financial_statements_2024_consolidated|83', 'CTG_financial_statements_2023_consolidated|83']
- bảng đã retrieve (28): ['CTG_financial_statements_2022_consolidated|82', 'CTG_financial_statements_2024_consolidated|83', 'CTG_financial_statements_2023_consolidated|83', 'CTG_financial_statements_2025_consolidated|76', 'CTG_financial_statements_2025_consolidated|5', 'CTG_financial_statements_2025_consolidated|3', 'CTG_financial_statements_2025_consolidated|8', 'CTG_financial_statements_2025_consolidated|7', 'CTG_financial_statements_2025_consolidated|6', 'CTG_financial_statements_2023_consolidated|7', 'CTG_financial_statements_2024_consolidated|5', 'CTG_financial_statements_2023_consolidated|9', 'CTG_financial_statements_2022_consolidated|9', 'CTG_financial_statements_2024_consolidated|7', 'CTG_financial_statements_2022_consolidated|7', 'CTG_financial_statements_2025_consolidated|4', 'CTG_financial_statements_2023_consolidated|10', 'CTG_financial_statements_2024_consolidated|9', 'CTG_financial_statements_2022_consolidated|12', 'CTG_financial_statements_2023_consolidated|12', 'CTG_financial_statements_2024_consolidated|10', 'CTG_financial_statements_2024_consolidated|8', 'CTG_financial_statements_2022_consolidated|8', 'CTG_financial_statements_2022_consolidated|11', 'CTG_financial_statements_2023_consolidated|8', 'CTG_financial_statements_2022_consolidated|10', 'CTG_financial_statements_2023_consolidated|11', 'CTG_financial_statements_2024_consolidated|6']
- ⛔ **thiếu trong prompt:** ['CTG_financial_statements_2025_consolidated|81']
- verify nói: *Câu hỏi yêu cầu tìm năm có tổng giá trị cao nhất trong khoảng 2022-2025, nhưng truy vấn chỉ trả về con số cho năm 2022 mà không so sánh với các năm còn lại từ df2 và df3.*
- query trước khi verify sửa: `df1.iloc[4]["Số cuối năm"]`

### Bảng model thực sự nhìn thấy

**df1 = `CTG_financial_statements_2022_consolidated|82`**  (5x3)

```
                                   Unnamed: 0  Số cuối năm   Số đầu năm
0                                   Triệu VND          NaN          NaN
1                         Tài sản khác giữ hộ    6063559.0    5345563.0
2                          Tài sản thuê ngoài   11023860.0   10448109.0
3  Các chứng từ có giá trị khác đang bảo quản   88827993.0   95371753.0
4                                              105915412.0  111165425.0
```

**df2 = `CTG_financial_statements_2024_consolidated|83`**  (6x3)

```
                                   Unnamed: 0  Số cuối năm  Số đầu năm
0                                   Triệu VND          NaN         NaN
1                 Kim loại quý, đá quý giữ hộ      80879.0     47734.0
2                         Tài sản khác giữ hộ   10469024.0   8503445.0
3                          Tài sản thuê ngoài   12129496.0  11590006.0
4  Các chứng từ có giá trị khác đang bảo quản  110291470.0  71514898.0
5                                              132970869.0  91656083.0
```

**df3 = `CTG_financial_statements_2023_consolidated|83`**  (6x3)

```
                                   Unnamed: 0  Số cuối năm  Số đầu năm(Trình bày lại)
0                                   Triệu VND          NaN                        NaN
1                 Kim loại quý, đá quý giữ hộ      47734.0                    50029.0
2                         Tài sản khác giữ hộ    8503445.0                  6063559.0
3                          Tài sản thuê ngoài   11590006.0                 11023860.0
4  Các chứng từ có giá trị khác đang bảo quản   71514898.0                 84640576.0
5                                               91656083.0                101778024.0
```
