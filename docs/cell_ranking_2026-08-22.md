# Chọn ô, không phải đọc bảng (2026-08-22)

Hai gate offline, không gọi LLM lần nào, chạy lại được bao nhiêu lần cũng được. Tập đo là
clean eval, 128 nhãn, **119 câu chấm được**. v8 = 46/119 = 0.387. SE ≈ 4,5pp ≈ 5 câu, nên
mọi con số dưới 5 câu ở đây là nhiễu, không phải kết quả.

- `scripts/gate_selection_vs_reading.py` (commit `b4ee26d`)
- `scripts/gate_cell_ranking.py` (commit `2777a25`), readout ở `artifacts/runs/gate_cell_ranking.out`

## 0. Kết luận

Chỗ nghẽn là **chọn ô**, không phải chất lượng header và cũng không phải retrieval. Trong
nhãn một ô, hạng của ô gold trong pool ứng viên gần như quyết định đáp án: **hạng 0 đúng
19/20, ngoài hạng 0 đúng 4/16.** Mười câu sai có ô gold nằm sẵn trong pool nhưng bị một ô
nhiễu xếp trên. Đó là đòn đầu tiên đo được đủ lớn (~+8pp) để vượt SE.

## 1. Ba tầng bằng chứng, không phải hai

Cái này mất công nhất và là tiền đề của mọi số phía sau.

| tầng | đọc ở đâu | median |
|---|---|---:|
| shortlist retrieval | `table_ids` của run | ~22 bảng |
| namespace `df1..dfN` | `diag.evidence_tables` | 3 bảng |
| ô mà query trỏ vào | `solution.pandas_query` | 1 ô |

`relevant_tables` trong submission **bằng đúng** `table_ids` trên cả 1.012 câu, nên nó không
phải một tầng riêng. Giả định `dfN ↔ table_ids[N-1]` là **sai**: q32 có 8 bảng trong
`table_ids` nhưng đúng 1 df (`FPT|5`). Đọc theo giả định sai đó báo 60 lỗi đọc bảng ở chỗ
thật ra chỉ có 23.

## 2. Selection vs reading (gate 1)

Nhãn mang `raw_cell_value` nguyên văn (`444.917.590.949`), đủ hiếm để tìm thẳng trong
146.246 CSV. Quét theo **mã cổ phiếu**, không theo `report_id`, vì câu nhiều năm chỉ được
nhãn ghi một report (q866 hỏi SJG 2018–2020, `report_id` chỉ có SJG_2018). So trên **chuỗi
thô** của CSV, vì `normalize_frame` đổi ô thành float nên `200.405.269.967` không còn tồn
tại dưới dạng chuỗi.

| | sai | đúng | tổng |
|---|---:|---:|---:|
| đã nạp | 23 | 43 | 66 |
| ngoài df | 33 | 0 | 33 |
| ngoài shortlist | 11 | 0 | 11 |
| không có df | 4 | 2 | 6 |
| không dò được | 2 | 1 | 3 |

**44 câu mà bảng gold không vào được `df` thì sai cả 44.** Khi nó vào được, pipeline đúng
65%. Trong 33 câu "ngoài df": 17 sàng lọc nhiều công ty, 15 tra một ô, 1 hai tài liệu.

## 3. Xếp hạng ô gold (gate 2)

Gate 2 cô lập bộ chấm: scope (mã, năm, hợp nhất/riêng) lấy thẳng từ `report_id` của nhãn,
tức **cho không** bước understand. `build_request` và `build_candidates` đều xác định.
`limit_per_slot=400` để thấy hạng thật, rồi so lại với 12 của production.

Tách nhãn một ô và nhãn nhiều ô, vì gộp lại thì con số vô nghĩa: nhãn nhiều ô đòi *mọi*
thành phần lên hạng cao, mà q703 chẳng hạn cần cộng trừ 5 dòng thuyết minh bên liên quan.
Trượt ở đó là thiếu bước tổ hợp, không phải bộ chấm xếp sai.

| | một ô | nhiều ô |
|---|---:|---:|
| hạng 0 | 20 | 0 |
| trong 12 | 10 | 5 |
| ngoài 12 | 5 | 27 |
| ngoài pool | 1 | 6 |
| linker không nhận | 10 | 30 |
| nhãn không có số | 0 | 5 |

Mười một câu sai có ô gold trong pool nhưng dưới một ô nhiễu: **32, 51, 87, 139, 255, 308**
(trong 12) và **109, 164, 185, 214, 267** (ngoài 12). Trừ q139 ra, câu đó lấy đúng ô nhưng
lệch đơn vị 1000, không phải lỗi hạng. Còn **10 câu**.

Ví dụ sạch nhất là q164: ô gold `Trích khấu hao trong năm` ở thuyết minh bất động sản đầu
tư nằm **hạng 28**, còn hạng 0 là dòng lưu chuyển tiền tệ `Khấu hao TSCĐ và bất động sản
đầu tư` gộp cả tài sản cố định vào, ra 28,96 thay vì 4,9. Bộ chấm đánh rơi định ngữ và
thưởng cho dòng gộp. q703 cũng vậy: `table_score` của bảng thuyết minh đúng (0,874) thấp
hơn bảng cân đối (0,922) chỉ vì tên dòng ở báo cáo chính trùng chữ với câu hỏi.

**Confound đã đóng:** scope production khớp nhãn ở **cả 12/12 câu** (so
`diag.raw_table_linker.request.slots` với `report_id`). Không câu nào hỏng vì understand
đoán sai mã hay năm.

Cột "nhiều ô" (30 câu linker từ chối, 27 câu ngoài lằn cắt 12) là lớp sàng lọc mà
`config.py:236-259` đã đo và đóng lại: nới trần bảng làm coverage tăng gấp đôi (10/38 →
20/38) mà điểm đứng nguyên 4/38. Không mở lại.

## 4. Giả thuyết đã bị loại

- **Bảng thuyết minh (`table_pos` cao) bị bỏ qua có hệ thống.** Không. Median `table_pos`
  của bảng gold trong nhóm sai là 7, của bảng được nạp là 8. Không có thiên lệch vị trí.
- **Nới trần bảng cho câu nhiều công ty.** Đã đo rồi, xem §3.
- Bốn bug trong chính dụng cụ đo, xem §1 và §2. Ba lần đầu tôi đọc ra kết quả sai vì dụng
  cụ sai, không vì pipeline sai.

## 5. Giới hạn

Gate 2 **cho không** scope, nên nó đo *trần trên* của việc sửa bộ chấm, không phải điểm
thật. Con số +8pp phải hiểu theo nghĩa đó. Nó cũng chỉ nói ô gold ở hạng nào, không nói
LLM sẽ chọn ô hạng 0; đó là hai chuyện khác nhau.

## 6. Đã sửa bộ chấm (2026-08-22)

Đọc 10 câu có ô gold trong pool, kèm ba thành phần điểm và câu hỏi nguyên văn
(`artifacts/runs/gate_rank_detail.out`), ra **năm** nguyên nhân rời nhau, không phải một.
Vòng lặp đo là 36 câu nhãn một ô có hạng, khoảng 4 phút một lượt, không gọi LLM.

### 6.1. `ngan` trong `_STOPWORDS` xóa mất `ngắn`

`'ngan'` nằm trong `_STOPWORDS` để chặn `ngân hàng`. Hậu quả: `Ngắn hạn` tách ra còn
`['han']`, còn `Dài hạn` ra `['dai', 'han']`. Định ngữ quan trọng nhất của báo cáo tài
chính biến mất khỏi mọi nhãn dòng, và `Ngắn hạn` co lại thành nhãn **một token**.

Tên ngân hàng vốn đã bị `_scoring_query_for_table` bỏ riêng cho từng bảng, nên bỏ `'ngan'`
khỏi stopword là đủ. Các mục hai từ trong `_STOPWORDS` (`ngan hang`, `cong ty`, `viet nam`,
...) là **dead code**: chỗ dùng duy nhất so từng token đã tách, nên chúng không khớp được
bao giờ. Tôi để nguyên chúng.

### 6.2. `min()` ở mẫu số cho nhãn một từ điểm tuyệt đối

`_token_score` chia cho `min(len(query), len(label))`. Nhãn một từ khớp một token bất kỳ ra
**1.000**, bằng đúng nhãn gold sáu từ khớp trọn. q32 hỏi "phải thu theo tiến độ kế hoạch
hợp đồng" và dòng `Tiền` hòa điểm với dòng gold, vì `tiến` bỏ dấu thành `tien`. Thứ tự
quyết định bởi thứ tự dòng trong file, tức ngẫu nhiên.

Sàn mẫu số ở ba từ. `Tiền` xuống 0.333, gold giữ 1.000.

### 6.3. Không tính tiền cho từ mà câu hỏi không hỏi

Dòng gộp `Khấu hao tài sản cố định và bất động sản đầu tư` khớp mọi từ của một câu chỉ hỏi
bất động sản đầu tư, nên nó hòa hoặc thắng dòng thuyết minh cụ thể `Trích khấu hao trong
năm`. Nhân thêm hệ số theo tỷ lệ từ trong nhãn mà câu hỏi không nhắc. Hệ số 0.5 và 1.0 cho
kết quả gần như y nhau (chỉ q109 nhích 32→30), nên giữ 0.5 — dấu hiệu tốt là tôi không
đang tinh chỉnh một cái núm cho vừa 36 câu.

### 6.4. Đã thử và **bỏ**: nới điểm cột cho bảng thuyết minh một kỳ

Ô gold của 87, 164, 185, 214 đều nằm ở cột tên là `Tổng` / `Cộng` / `Đơn vị tính: VND`, chấm
0.12, trong khi cột có năm in ra chấm 0.50. Lý lẽ: bảng thuyết minh một kỳ đặt tên cột theo
nội dung chứ không theo ngày, vì không có kỳ thứ hai để phân biệt, nên trừ điểm nó là bất
công có hệ thống.

Đo thì đúng hướng nhưng không đủ: cả bốn câu lên hạng đáng kể (185: 72→40, 214: 29→20,
164: 26→22, 87: 5→3) mà **không câu nào tới hạng 0**, đồng thời mất q332 (đang đúng ở hạng
0) và q109. Ablate lại xác nhận bỏ nó thì hạng 0 lên 24 thay vì 23. **Bỏ.** Cái chặn bốn
câu đó là điểm dòng, không phải điểm cột.

### 6.5. `partial_query` cho `_phrase_match_score`

`raw_selection_linker._phrase_match_score` gọi cùng `_semantic_score` nhưng **đảo vai**:
phía "query" là một cụm từ trong search plan, cố ý ngắn. Tính tiền §6.3 ở đó là sai — cụm
`Tiền gửi của khách hàng` khớp dòng đúng `Tiền gửi không kỳ hạn của khách hàng bằng đồng
Việt Nam` sẽ tụt 1.000 → 0.786, hạ oan cả lớp sàng lọc. Thêm cờ `partial_query` để tắt
riêng phần tính tiền đó, giữ nguyên sàn mẫu số.

### 6.6. Số đo

Nhãn một ô có hạng, 36 câu:

| biến thể | hạng 0 | trong 12 |
|---|---:|---:|
| gốc | 20 | 10 |
| §6.1 | 21 | 10 |
| §6.1 + §6.2 | 23 | 8 |
| + §6.4 | 22 | 9 |
| + §6.4 + §6.3 | 23 | 9 |
| **§6.1 + §6.2 + §6.3, bỏ §6.4** | **24** | **7** |

Chạy lại cả 119 câu: nhãn một ô **hạng 0 20 → 24, trong 12 10 → 7, ngoài 12 5 → 4**. Cột
nhãn nhiều ô **không đổi một số nào** (5 / 27 / 6 / 30 / 5), tức thay đổi nằm đúng chỗ nhắm.

Lên hạng 0: **32, 51, 255** (đang sai) và 360 (đang đúng, từ hạng 1). Không câu đúng nào bị
đẩy khỏi hạng 0. Ở tỷ lệ chuyển hóa đã đo (hạng 0 đúng 19/20), ba câu đó là khoảng
**+2,5pp — dưới SE 4,5pp.** Đúng hướng, chưa đủ để đo được trên tập này.

### 6.7. Test cũ pass nhờ chính cái bug

`tests/test_raw_selection_linker.py` dựng một bảng nhiễu ba dòng, trong đó `Động sản` khớp
cụm `Tài sản thuê ngoài` ở **1.000** vì nó chỉ còn một token (`dong` là unit token). Sau khi
sàn mẫu số, nó xuống 0.333, bảng nhiễu còn hai dòng và bị luật "≥4 cụm thì cần ≥3 dòng"
loại thẳng, nên test không tìm thấy nhóm để so. Đổi dòng đó thành `Các chứng từ có giá trị
khác`, một cụm khớp thật, để bảng nhiễu tự đứng được ba dòng và phép so nguyên ý.

25/26 file test pass. `tests/test_query_execution.py` sai 2 case **từ trước** thay đổi này
("khôi phục header hai tầng bị lệch", "số cuối kỳ nằm đúng cột semantic"): đó là bảng
`FTS|24` mà `repair_shifted_multilevel_header` bản mới **cố ý từ chối** ở §11.2 của
`multiyear_failures_2026-08-22.md`, còn test vẫn giữ kỳ vọng bản cũ. Commit `ebbe531` chưa
cập nhật test này.

### 6.8. Còn lại

Bốn nguyên nhân đã nhìn thấy mà chưa sửa, kèm câu chúng chặn:

- **Giá trị rác từ cột số tham chiếu.** q87 có hạng 0 là ô giá trị **6** và hạng 1 là **4**,
  đều là số thuyết minh ở một bảng lệch header; giá trị thật rơi sang `Unnamed: 5`.
  `column_profiles.is_identifier` không bắt được vì cột tên là `Năm 2024VND`.
- **Dòng tổng chấm 0 khi câu hỏi không nói "tổng".** q109 có ô gold là dòng `Cộng` của bảng
  thuyết minh, `row_score` đúng 0.00, vì `row_anchor` chỉ được tính khi `wants_total`.
- **`_is_component_row` trừ đúng thành phần được hỏi.** q267 hỏi thẳng "bằng ngoại tệ", ô
  gold là dòng `- Bằng ngoại tệ` và bị trừ 0.12 vì có dấu gạch đầu dòng.
- **q139 là lỗi đơn vị, không phải lỗi hạng.** Lấy đúng ô, lệch 1000 lần. Gate xếp nó vào
  "trong 12" nên nó làm con số bi quan hơn thực tế một câu.

## 7. Vòng thứ hai: trục cột và dòng tổng (2026-08-22)

Điểm khởi đầu không phải §6.8 mà là một phép đo khác. Với 33 câu "ngoài df" ở §2, đo hạng
của bảng gold *trong shortlist*:

```
hạng gold nhỏ nhất: {0: 14, 1: 3, 2: 4, 3: 5, 4: 2, 7+: 5}
```

**14/33 câu có bảng gold ở hạng 0 mà vẫn không vào `df`.** Bốn câu nhãn một ô xem thẳng thì
retrieval đã xếp đúng bảng lên đầu và solver bỏ nó để lấy `|5`, `|6`, `|7`, tức báo cáo
chính: q164 (`SSH|27` -> `|7`), q169 (`STB|45` -> `|98`), q185 (`VIC|21` -> `|6`), q703
(`GEX|67` -> `|5`). Không phải lỗi retrieval, không phải trần bảng của `codegen_budget`.

### 7.1. Năm biến thể, đo trên cùng 119 câu

`--dump` ghi `{id: hạng tệ nhất}` nên so được từng câu, không chỉ so tổng.

| biến thể | hạng 0 | trong 12 | ngoài 12 | ngoài pool |
|---|---:|---:|---:|---:|
| gốc (`9e7bcf6`) | 24 | 12 | 31 | 7 |
| A thưởng riêng hạng 0 | 24 | 11 | 32 | 7 |
| B chuẩn hóa điểm cột theo bảng | 23 | 16 | 29 | 6 |
| C+D cột tổng, cột phần trăm | 24 | 13 | 30 | 7 |
| **C+D+F+G** | **24** | **14** | **29** | **7** |
| C+D+F+G+E thưởng cụm từ có phạt | 23 | 16 | 28 | 7 |

Cột "hạng 0" là cột duy nhất đã đo được tỷ lệ chuyển hóa (19/20). Ba biến thể bị bỏ đều bỏ
vì cột đó, không vì cột nào khác.

### 7.2. Hai luật đã giữ trên trục cột

**C. Cột tổng khi câu hỏi không gọi tên phần nào.** `_column_score` chỉ đọc chữ chỉ kỳ, nên
bảng bộ phận `Điện | Than | Khác | Cộng` cho bốn cột điểm y nhau và thứ tự cột quyết định.
Cộng thêm 0.12 cho cột tổng, và chỉ khi không cột thành phần nào khớp chữ với câu hỏi.
q214 12 -> 6.

**D. Cột tỷ lệ không trả lời được câu hỏi tính bằng đồng.** `Tỷ lệ(%)` giữ một con số ngay
cạnh số tiền nên nó thắng những trận hòa mà nó không có quyền dự. Loại cột đó khi
`request.target_unit` là đơn vị tiền. `_norm` xóa dấu `%` nên phải kiểm trên chuỗi thô.

### 7.3. Hai luật đã giữ trên trục dòng

**F. Dòng tổng luôn vay điểm của dòng tốt nhất.** `row_anchor` trước đây chỉ tính khi
`request.wants_total`, tức **mọi** dòng tổng còn lại trong corpus chấm đúng 0.00 trên trục
dòng. q109 hỏi trả trước cho người bán và đáp án là dòng `Cộng` của thuyết minh: 20 -> 1.
Kèm theo `total_adjust = -0.06` khi câu hỏi không nói "tổng", đủ để thua dòng cụ thể mà nó
vay điểm, không đủ để thua những dòng câu hỏi không nhắc.

**G. `_is_component_row` chỉ trừ khi có dòng khác khớp hơn.** Dấu gạch đầu dòng là quy ước
in ấn. Điều kiện `row_score < row_anchor` không thêm ngưỡng mới nào. q267 11 -> 1, và nó
cứu q313 mà F vừa làm hỏng (0 -> 1 rồi về 0).

### 7.4. Ba biến thể đã bỏ, và vì sao

**A. Thưởng riêng cho hạng 0** (0.18 so với 0.08 của hạng 1-2). Đây là giả thuyết trực tiếp
từ con số 14/33 ở trên, và nó **sai**: 109, 164, 185 đi đúng hướng nhưng không câu nào đổi
nhóm, còn q267 và q308 bị đẩy khỏi top 12. Thứ hạng retrieval không phải chỗ chặn.

**B. Chuẩn hóa điểm cột theo bảng.** Ý tưởng: bảng thuyết minh một cột `Tổng` không bao giờ
kiếm được +0.42 của `Năm nay`, nên nó chịu bất lợi 0.8 vì *hình dạng* chứ không vì nội dung;
chấm mỗi cột theo cột tốt nhất của chính bảng đó. Đo được: q164 26 -> 4, q214 29 -> 3,
q185 62 -> 26, bốn câu vào top 12. Nhưng nó mất q332 vì chuẩn hóa nâng cột `Số tiềnVND`
không có kỳ nào lên **bằng** cột in rõ `Năm 2024`. Hạ trần xuống 0.88 không cứu được: mọi
bảng đều được nâng cột tốt nhất của chính nó lên trần, nên bằng chứng "in đúng năm được
hỏi" biến mất hoàn toàn. Đó là xóa bằng chứng thật, không phải xóa bất lợi.

Bài học đắt nhất của vòng này: q164 có khoảng cách cột 0.192 nên trông như lỗi trục cột,
nhưng cột `Năm nay` của bảng lưu chuyển tiền tệ **thật sự** là bằng chứng đúng. Khoảng cách
số lớn nhất không phải thành phần sai nhất.

**E. Phạt thưởng cụm từ theo số từ dư.** Thưởng cụm từ là `max(score, 0.92)` phẳng, nên một
dòng chứa 4 từ liền của câu hỏi lấy 0.92 bất kể nó nói thêm gì, ghi đè luôn hình phạt §6.3.
Nhân nó với cùng hệ số precision *nghe* đúng, nhưng đo ra mất q360 khỏi hạng 0 và làm q164
tệ hơn (26 -> 49), ngược hẳn giả thuyết. Ai định thử lại hướng này thì đọc số này trước.

### 7.5. Chỗ chặn còn lại

Bốn câu giờ nằm hạng 1, mỗi câu bị đúng một ô nhiễu chặn: 109, 267, 308, 684. Cả bốn đều
thua một dòng ở báo cáo chính hoặc một dòng thành phần khớp nhiều chữ hơn. q164 (26) và
q185 (70) vẫn xa, và §7.4 cho thấy không sửa được bằng trục cột. q87 (3) vẫn là lỗi giá trị
rác ở §6.8. Số đo nói thẳng: hạng 0 đứng nguyên 24, nên vòng này chưa mua thêm điểm nào,
chỉ dọn bốn khuyết tật cấu trúc và không làm hỏng câu nào.
