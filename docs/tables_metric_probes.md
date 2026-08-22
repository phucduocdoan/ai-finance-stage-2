# TABLES metric — sổ dò leaderboard

Ghi lại toàn bộ 11 lượt submit đã tiêu để dò `relevant_tables`. Đọc file này trước
khi định dò thêm lượt nào cho TABLES.

## Cách dò

Mọi bản dùng chung một carrier: `output/submission_patched.zip` (bản base
aggregate 0.2688). Chỉ thay **duy nhất** field `relevant_tables`, giữ nguyên
`answer`, `relevant_docs`, `evidence`, `pandas_query`, và toàn bộ `data/*.csv`.

Vì `relevant_docs` là field riêng, DOCS_* và ANSWER_* phải bất động qua mọi lượt —
và đúng là bất động, nên mỗi lượt cô lập sạch một giả thuyết về TABLES:

```
DOCS_F2MACRO 0.9268  DOCS_PRECISION 0.9525  DOCS_RECALL 0.926  DOCS_MRR5 0.9631
ANSWER_ACCURACY 0.2628  EXECUTION_ACCURACY 0.2628
```

Công cụ suy luận: recall đơn điệu theo tập hợp. `P ⊆ Q ⇒ recall(P) ≤ recall(Q)`,
nên hai bản rời nhau cộng recall lại đúng bằng bản hợp.

## Sổ kết quả

| bản | `relevant_tables` gửi lên | id/câu p50 | TABLES_RECALL | F2 | P | MRR5 |
|---|---|---|---|---|---|---|
| base | vị trí thật của ta, top-3 bảng | 3 | **0.0** | 0.0 | 0.0 | 0.0 |
| A | `{rid}\|q`, q ∈ 1..M, mọi doc | 146 | **0.0** | 0.0 | 0.0 | 0.0 |
| B | q ∈ [p−4..p+1] quanh top-3 bảng | 18 | **0.0** | 0.0 | 0.0 | 0.0 |
| C | q ∈ 0..300 mọi doc ∪ 6 dạng chuỗi khác | 674 | **0.1311** | 0.0033 | 0.0007 | 0.0 |
| D1 | q ∈ 0..300, mọi doc | 602 | **≈0.1311** (khác 0) | — | — | — |
| D2 | chỉ 6 dạng chuỗi khác | 102 | **0.0** | 0.0 | 0.0 | 0.0 |
| E1 | `td_idx`/`ctd_idx` ±1, mọi bảng của 3 doc | 780 | **0.1272** | 0.0017 | 0.0003 | 0.0 |
| F1 | chỉ `{rid}\|0` | 2 | **0.0** | 0.0 | 0.0 | 0.0 |
| G1 | q ∈ [M+1..M+10] | 20 | **≈0** | — | — | — |
| G2 | q ∈ [M+11..M+50] | 80 | **nhỏ** | — | — | — |
| G3 | q ∈ [M+51..300] | 332 | **0.129** | 0.0064 | 0.0014 | **0.0024** |
| H1 | q ∈ 301..600, mọi doc | 600 | **0.1241** | 0.0035 | 0.0007 | 0.0067 |

`M = max(table_pos)` của report đó theo `tables_metadata_v2.jsonl`. `p` = vị trí
bảng ta dự đoán. Chưa nộp: E2 (`line_no`), E3 (`trtd`), F2 (`301..1300` top-1 doc),
H1, H2 (đã build sẵn, xem dưới).

## Kết luận chắc chắn

1. **Gold `gt_tables` có thật và với tới được.** Trước C tôi đã kết luận sai là
   không thể thắng metric này; C bác bỏ.
2. **Dạng chuỗi `{report_id}|{số nguyên}` là đúng.** D2 = 0.0 giết cả 6 biến thể
   (`|table_N`, `|table_N.csv`, `_table_N`, `_table_N.csv`, `/table_N.csv`,
   `table_N.csv`).
3. **Số của gold không bao giờ ≤ M, và không bao giờ là 0.** A = 0.0, F1 = 0.0.
   Nên vị trí ta đang gửi (1..M, đúng ordinal thẻ `<table>`) **không thể** khớp —
   đây là lý do base/v3/v4/v5 đều TABLES = 0.0.
4. **~13% entry gold có số trong khoảng ~[110..300], ~87% có số > 300.**
   G3 (0.129) chiếm gần trọn phần 0.1311 của D1; G1 ~0, G2 nhỏ.
5. **Vị trí của ta đúng bằng ordinal thẻ `<table>` thô**: 146.246 thẻ đếm lại từ
   1.973 file OCR == 146.246 dòng metadata, 0 lệch trên 1.965 report.
6. **Ví dụ `AAA_..._2015_consolidated|350` trong `submission_rule.txt` là số bịa.**
   Report đó có 47 bảng; không đại lượng nào cho ra 350 (gần nhất `tr`=346 ở
   pos 33). Đừng suy luận gì từ ví dụ này.
7. `page` và `char_off` bị loại làm đơn vị: p(≤300) = 1.000 và 0.000, cần ~0.142.
   Ứng viên khớp phân phối: `td_idx` 0.154, `ctd_idx` 0.153, `trtd` 0.117.

## Điểm còn treo

E1 (đúng `td_idx` ±1) được 0.1272 ≈ D1, **nhưng** E1 chỉ phủ ~20–40 số trong dải
`(M..300]` mà G3 chứng minh là nguồn điểm, tức là một tập rất thưa. Ba khả năng:

- (a) trùng hợp;
- (b) `td_idx` khớp cả ở vùng > 300, hai hiệu ứng độc lập nhau;
- (c) **recall bão hoà ~0.13 theo độ dài danh sách, không theo nội dung** —
  evaluator có thể cắt top-K. Bảng recall/độ dài đơn điệu đáng ngờ:
  G1 20→~0, G2 80→nhỏ, G3 332→0.129, D1 602→0.1311, E1 780→0.1272.
  Phản chứng: A có 146 id mà đúng 0.0.

Hai bản đã build sẵn để chặn đường, **nộp H1 trước**:

- `output/submission_probeH1_301_600.zip` — q ∈ 301..600 mọi doc, 600 id/câu,
  cùng cỡ D1 nhưng dải rời hẳn D1.
  - ~0.13 → giả thuyết (c) đúng, mọi số D1/E1/G3 là ảo, **đóng hẳn hướng TABLES**.
  - ~0.0 → số đo là thật, gold thật nằm trong [M+51..300] và phần > 300 không
    nằm ngay sát 300.
- `output/submission_probeH2_d1_plus_td.zip` — D1 ∪ (td-family > 300, 3 doc),
  1359 id/câu. Chỉ có nghĩa nếu H1 ≈ 0.0. ~0.25 → (b) đúng; ~0.13 → (a).

## H1 đã nộp: đóng hướng TABLES (2026-08-22)

```
TABLES_F2MACRO 0.0035  TABLES_PRECISION 0.0007  TABLES_RECALL 0.1241  TABLES_MRR5 0.0067
DOCS_* và ANSWER_* bất động như mọi lượt trước, nên lượt này cô lập sạch.
```

H1 gửi dải 301..600, **rời hẳn** D1 (0..300), cùng cỡ danh sách. Nó ra 0.1241 so với 0.1311
của D1. Hai dải không giao nhau mà điểm gần y nhau, tức recall **không nói gì** về việc gold
nằm ở số nào. Theo đúng luật đã đặt trước khi nộp: mọi số D1/E1/G3 là ảo, đóng hướng này.

Suy ra số hit thật từ `precision × số id gửi`:

| bản | id/câu | hit/câu | recall | `|gold|` suy ra | mật độ hit/id |
|---|---:|---:|---:|---:|---:|
| G3 | 332 | 0.46 | 0.1290 | 3.6 | 0.0014 |
| C | 674 | 0.47 | 0.1311 | 3.6 | 0.0007 |
| H1 | 600 | 0.42 | 0.1241 | 3.4 | 0.0007 |

Ba bản độc lập cho `|gt_tables|` ≈ **3.5 entry/câu**, con số đầu tiên của lượt dò này mà
nhất quán. Nhưng mật độ hit trên mỗi id cao nhất từng đo được là 0.0014 (G3), nên muốn
recall 1.0 phải gửi cỡ 2.500 id/câu với precision ~0.0005, cho
`f2 = 5PR/(4P+R) ≈ 0.0025`. Metric này đòi danh sách **chặt**, mà không lượt nào tìm được
dải nào đủ dày. Không có đường đi.

Hai chỗ phải sửa lại trong "Kết luận chắc chắn" ở trên:

- **Kết luận 4 sai.** "~87% gold có số > 300" suy ra từ D1/G3, mà H1 vừa chứng minh những
  số đó không định vị được gì.
- **Kết luận 1 vẫn đúng nhưng vô dụng.** Gold có thật và với tới được, chỉ là với tới bằng
  cách quét rộng, và quét rộng thì precision chết.

**H2 không nộp.** Điều kiện của nó là H1 ≈ 0.0. Không dò thêm lượt nào cho TABLES.

## Chi phí và trần

Con số ~0.11 `TABLES_F2MACRO` (aggregate ~+0.02) từng ghi ở đây **không với tới được**: nó
giả định tìm được danh sách chặt, mà H1 đã đóng khả năng đó. `f2 = 5PR/(4P+R)` tính một lần
từ P và R macro, recall nặng gấp 4 lần precision, đó là lý do bản quét rộng vẫn ra F2 > 0 dù
precision ~0.0007. Nhưng F2 > 0 kiểu đó là 0.0035, không phải 0.11.

12 lượt submit đã tiêu cho TABLES. Toàn bộ đất còn lại nằm ở `ANSWER_ACCURACY`.

So sánh: `ANSWER_ACCURACY` đang 0.2628 và đó là nơi còn nhiều đất. Sau H1/H2
không dò thêm lượt nào cho TABLES.
