# Trục cuối, chọn bảng nào của báo cáo: cũng không phải khoảng trống (2026-08-23)

Ba trục của một tham chiếu ô đã có số trước hôm nay. Báo cáo: `b411f8e`, 66/70 câu sai vốn
đã có đủ báo cáo gold. Dòng: `docs/row_match_2026-08-23.md`, vượt sàn nhiễu ~3 câu. Cột:
`docs/cell_ref_fuzzy_2026-08-23.md`, dưới sàn nhiễu. Còn lại đúng một trục: trong một báo
cáo có ~75 bảng, v9 đọc bảng nào.

Kết quả: **không phải khoảng trống, và cách nó không phải mới là điều đáng ghi.** Công cụ
`scripts/gate_table_selection.py`, readout `artifacts/runs/gate_table_selection.out`.

## Phép đo

Với mỗi câu, xét ba tầng bảng theo chỗ nó nằm: bảng v9 đã đọc (`evidence`), bảng có trong
shortlist đã nộp mà v9 không đọc, và bảng của báo cáo gold mà cả shortlist cũng không có.
Báo cáo gold suy từ metadata câu hỏi, không từ retrieval của v9, vì lấy theo v9 thì phép đo
không thể phát hiện chính lỗi của v9.

Điều kiện trúng: bảng đó có một dòng mà **nhãn dòng được câu hỏi phủ >= 60% token**, và một
ô của dòng đó ra gold với hệ số 1e±3/6/9. Hướng phủ là ngược với `lookup._score`: ở đây câu
hỏi dài và nhãn ngắn, nên đo nhãn được phủ chứ không đo câu hỏi được phủ.

## Con số thô, và vì sao không được đọc nó

| | n | bảng đã đọc | shortlist, không đọc | còn lại của báo cáo |
|---|---|---|---|---|
| v9 sai | 70 | 6 = 9% | 8 = 11% | 32 = **46%** |
| v9 đúng | 49 | 20 = 41% | 8 = 16% | 17 = **35%** |

Đọc thô thì cột cuối là 46% so với 35%, tức khoảng 7,5 câu vượt sàn, và câu chuyện sẽ là
"shortlist bỏ sót bảng đúng". Con số đó sai.

**Confound: rổ ứng viên của câu sai to gần gấp đôi.** Câu v9 sai dồn vào tier nhiều công ty
và nhiều năm, nên nó chạm nhiều báo cáo hơn, nên số bảng phải quét nhiều hơn, nên nó trúng
gold ngẫu nhiên nhiều hơn mà không cần có khoảng trống nào.

| số bảng ứng viên trung bình mỗi câu | đã đọc | shortlist | còn lại |
|---|---|---|---|
| v9 sai | 1.5 | 34.9 | **511.7** |
| v9 đúng | 1.7 | 18.0 | **270.9** |

Chuẩn hóa theo cỡ rổ, tức tỉ lệ trúng trên mỗi bảng ứng viên:

| | đã đọc | shortlist | còn lại |
|---|---|---|---|
| v9 sai | 0.0571 | 0.0033 | 0.0009 |
| v9 đúng | 0.2381 | 0.0090 | 0.0013 |

**Dấu bị lật.** Trên mỗi bảng ứng viên, câu v9 sai trúng *ít hơn* câu v9 đúng ở cả hai tầng,
0.0009 so với 0.0013 và 0.0033 so với 0.0090. Chênh lệch 46% so với 35% giải thích hết bằng
cỡ rổ, không còn phần dư nào cho một khoảng trống.

Cột duy nhất mà hai dòng khác nhau thật là "bảng đã đọc", 0.0571 so với 0.2381. Nhưng đó là
đồng nhất thức: câu v9 đúng thì đúng vì nó đọc trúng bảng. Cột đó không nói gì về việc sửa
được gì.

## Điều đáng giữ lại

Bốn trục của bài toán "đọc ô nào" giờ đều đã có số, và không trục nào tới mốc 10 thắng /
2 thua:

| trục | kết quả | nơi ghi |
|---|---|---|
| báo cáo nào | 66/70 câu sai đã có đủ báo cáo gold | `b411f8e` |
| bảng nào trong báo cáo | dấu bị lật sau khi chuẩn hóa cỡ rổ | doc này |
| dòng nào trong bảng | vượt sàn nhiễu ~3 câu | `row_match_2026-08-23.md` |
| cột nào trong dòng | 4% so với đối chứng 7%, dưới sàn | `cell_ref_fuzzy_2026-08-23.md` |

Đây là đường thứ bảy được định giá rồi bỏ, và nó khép lại cả nhóm giả thuyết "pipeline đọc
sai ô". Ba đường trước đó chết vì bắn trúng chỗ v9 đã đúng, đường doc_type chết vì khối
lượng nhỏ, đường này chết vì cái tưởng là tín hiệu hóa ra là cỡ rổ.

Cái đáng rút ra không phải một trục cụ thể mà là **hình dạng của cả bảy lần đo**: mỗi lần
trần trên rơi vào 2-3 câu, mốc là 10, và 1 sigma của tập eval là 5.4 câu. Bảy điểm dữ liệu
cùng hình dạng thì giả thuyết đơn giản nhất không phải "chưa tìm ra đường 10 câu" mà là
**không có đường 10 câu nào**: 0.334 bị giới hạn bởi nhiều nguyên nhân nhỏ độc lập.

Nếu đúng vậy thì việc kế tiếp không phải tìm đường thứ tám, mà là hạ sàn phân giải của thước
đo để các đường 3 câu trở nên đo được và cộng dồn được. Thiết kế đã có ở
`docs/label_calibration_2026-08-23.md`: hai lượt gán nhãn cộng một lượt phá hòa, vì phương
sai nằm ở lượt gán (lượt A 83%, lượt B 95.8% trên cùng một tập câu). Từ 119 lên ~400 câu thì
1 sigma đi từ 4.5 điểm xuống ~2.5 điểm.

## Một giới hạn của chính phép đo này

Điều kiện "nhãn dòng được câu hỏi phủ >= 60% token" chỉ bắt được câu hỏi gọi tên chỉ tiêu
gần như nguyên văn. Câu hỏi về tỉ số dẫn xuất (D/E, ROE) không có dòng nào mang tên đó, nên
chúng đóng góp 0 vào cả hai dòng của bảng. Phép đo vì thế nói về câu tra cứu trực tiếp, và
không kết luận gì về tier tỉ số. Đối chứng vẫn hợp lệ vì nó chịu đúng giới hạn ấy ở cả hai
phía.
