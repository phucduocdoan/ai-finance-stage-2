# Đáp án sai loại đại lượng: đường đầu tiên đo được trên 1012 câu (2026-08-23)

Tám đường trước đều nhắm vào "đọc lệch một ô" và đều chết vì cùng một lý do đã đo ở
`docs/miss_shape_2026-08-23.md`: 57/70 câu sai là một con số khác hẳn, nên mọi đường
sửa-lệch-nhỏ chỉ có 13 câu để bắn vào.

Đường này rơi ra từ việc xem tay khối 57. Ca mẫu là q433: hỏi "hệ số nợ phải trả trên tổng
tài sản", gold 26.44, nộp -3.672.086.428.314. Truy vấn không tính tỉ số nào, nó cộng các số
dư rồi nộp.

Công cụ `scripts/gate_answer_type.py`, readout `artifacts/runs/gate_answer_type.out`.

## Vì sao phép đo này khác tám phép đo trước

Một tỉ lệ không thể bằng 10^12. Cái sai đó **chứng minh được mà không cần gold**, giống hệt
tính chất đã dùng ở phép đo hình dạng: lệch đúng một lũy thừa của 10 thì không phải trùng
ngẫu nhiên. Hai hệ quả, và cả hai đều đổi cách đọc con số:

**Không cần sàn nhiễu.** Cột "câu v9 đúng" ra 0, nhưng đó không phải đối chứng mà là đồng
nhất thức: đáp án đúng thì bằng gold nên không thể ngoài khoảng. Đọc nó thành "precision
100%" là đọc sai. Cái thay thế cho đối chứng ở đây là tính chứng minh được của từng câu.

**Cỡ của đường này đo trên 1012, không trên 119.** Vì phát hiện không cần nhãn, nên không
phải chỉ đếm trong 70 câu sai đã biết. Trên toàn bộ submission: **51/1012 câu = 5.0%** nộp
một đáp án ngoài khoảng cho một câu hỏi tỉ lệ. Trên 119 câu chấm được là 7 câu = 5.9%, hai
tỉ lệ khớp nhau, nên 51 không phải con số suy diễn mà là con số đếm trực tiếp.

Đó là lần đầu một đường thoát khỏi sàn phân giải 5.4 câu của tập eval, vì nó không dùng tập
eval để biết mình đúng.

## Phần thua bị chặn bằng 0 theo kiến trúc

51 câu bị bắt đã sai chắc chắn. Chạy lại chúng chỉ đổi được sai thành đúng hoặc sai thành
sai. Mốc 10 thắng / 2 thua được chốt cho những đường **có thể thua**; ở đây bất kỳ tỉ lệ
chuyển đổi lớn hơn 0 đều là lãi ròng. Với 0 thua, McNemar một phía cần 5 câu chuyển để đạt
p < 0.05 và 6 câu để đạt đúng mốc 0.019.

| ngưỡng | câu sai bị bắt trên 119 |
|---|---|
| > 1e2 | 11 |
| > 1e3 | 7 |
| > 1e4 | 7 |
| > 1e6 | 7 |
| > 1e9 | 6 |

Khối này phẳng qua ba bậc từ 1e3 đến 1e6, nên kết quả không sống nhờ hằng số. Giữ 1e3 vì ở
1e2 bốn câu thêm có thể là tỉ lệ hợp lệ trên 100%, và bắt oan thì mất tính chứng minh được,
tức mất chính thứ làm đường này khác các đường trước.

## Giới hạn thật, đo được và phải nói trước khi hiện thực

Câu hỏi kế tiếp là retry có đích để bắn không. Phép kiểm miễn phí: gold có tính được từ một
cặp ô trong chính các bảng bằng chứng đã đọc không.

| câu | số ô số | số cặp thử | kết quả |
|---|---|---|---|
| q432 | 4 | 16 | không cặp nào trúng |
| q727 | 6 | 36 | không cặp nào trúng |
| q1004 | 54 | 2916 | không cặp nào trúng |
| q433 | 124 | 8060 | có, nhưng sàn nhiễu hàng nghìn cặp |
| q446 | 59 | 2331 | có, cùng sàn nhiễu |
| q462 | 191 | 30697 | có, cùng sàn nhiễu |
| q559 | 92 | 102 | trúng `1 / 24`, trùng bừa rõ ràng |

Bốn câu "có" đều đi kèm hàng nghìn cặp thử với dung sai 1%, nên chúng không nói được gì.
Ba câu có rổ ô nhỏ thì đều **không** trúng, và q432 chỉ có 4 ô số cho một câu sàng lọc 10
công ty, tức bằng chứng đọc vào không chứa đáp án.

Kết luận thẳng: với những câu đó, sinh lại truy vấn trên cùng bộ bằng chứng không thể thắng.
Validator phải kéo được truy hồi chạy lại, không chỉ codegen chạy lại. Đây là chỗ đường này
có thể chết, và nó là câu hỏi hiện thực chứ không phải câu hỏi đo lường.

## Một đường đã bị loại trong cùng phiên, ghi lại vì nó gần như đã được tin

Cùng lúc xem tay khối 57, một giả thuyết khác trông rất mạnh: truy vấn đọc dòng có nhãn
**không liên quan gì** đến chỉ tiêu được hỏi. Bằng chứng ban đầu là bốn ca sắc nét, q32 đọc
`Tiền` cho "phải thu theo tiến độ", q308 đọc `Vay ngắn hạn` cho "cho vay dài hạn", q527 đọc
`Cổ tức lợi nhuận được chia` cho một câu tỉ suất lợi nhuận, q769 lấy `Quyền sử dụng đất` trừ
`TỔNG TÀI SẢN`.

Đo bằng coverage của nhãn dòng theo câu hỏi, lấy min trên các chân của truy vấn, kết quả
trông như một đường thật: `min < 0.3` là 24% trên câu sai so với 13% trên câu đúng, và ghép
cặp theo số chân thì nhóm 5 chân trở lên ra 8/9 so với 1/8.

**Nó vẫn sai, và lý do đáng ghi hơn con số.** Thước coverage bị nhiễu bởi độ dài nhãn chứ
không bởi đúng sai. q557 và q573 đọc `Doanh thu thuần về bán hàng và cung cấp dịch vụ
(10 = 01 - 02)` cho câu hỏi về "doanh thu thuần": dòng đúng, nhưng nhãn 12 token kèm mã công
thức nên coverage ra 0.29. q735 đọc `Vay và nợ thuê tài chính ngắn hạn` cho "nợ vay ngắn
hạn", cũng đúng dòng. Ba trong chín câu bị bắt oan vì nhãn dài, nên precision khoảng 50% và
khối thật còn 4-5 câu.

Hai lần trong một phiên, cái trông như tín hiệu hóa ra là một biến khác: ở trục chọn bảng nó
là cỡ rổ, ở đây nó là độ dài nhãn. Cả hai lần chỉ có xem tay mới phát hiện, không phép đo
tổng hợp nào lộ ra.

## Đã hiện thực, đã chạy, và kết quả là 0/7

Validator được nối vào đúng vòng repair đã có ở `execute.py`, coi "đáp án ngoài khoảng cho
câu hỏi tỉ lệ" là một dạng thất bại thay vì dựng cơ chế thứ hai. Hai chi tiết đáng ghi trong
lúc hiện thực, vì cả hai đều là chỗ dễ làm sai:

Phép kiểm phải xét giá trị **sau** `apply_units`, không phải số thô, vì một số thô 1e12 có
thể là tỉ lệ hợp lệ sau khi truy vấn được chia tỉ. Và bản test đầu tiên vô hiệu mà không lộ
ra: dùng `df1.iloc[0]['a'] * 1e13` thì `apply_units` bóc luôn hệ số mô hình tự viết nên giá
trị còn 3.0 và validator chấp nhận đúng. Phải đặt số lớn vào trong chính bảng mới chạm được
đường đó.

Khi hết lượt repair thì trả về giá trị đã bị từ chối, không trả None. Trả None sẽ nộp 0.0,
mất mục tiêu chấm thực thi mà không được gì ở mục tiêu chấm đáp án, và làm sụp chính tính
chất đường này dựa vào: đáp án bị từ chối vốn đã sai, nên vòng lặp không được phép làm xấu
hơn.

Chạy lại 7 câu qua pipeline (`artifacts/runs/answer_type_retry.jsonl`):

| câu | gold | nộp cũ | sau validator |
|---|---|---|---|
| q432 | 88.05 | 2.30e13 | 481.83 |
| q433 | 26.44 | -3.67e12 | 100.0 |
| q446 | 50.38 | 9.88e12 | 100.0 |
| q462 | -11.04 | 8.42e12 | 0.9888 |
| q559 | 4.19 | 1.67e12 | -100.0 |
| q727 | 8.56 | 8.86e7 | -103.94 |
| q1004 | 5.27 | 3.68e10 | 0.05267 |

**Chuyển thành đúng 0, phá mất 0, mốc là 6.** Cả 7 câu giờ đều ra số trong khoảng, tức cơ chế
chạy đúng, nhưng không câu nào ra gold. Phần thua bằng 0 giữ đúng như thiết kế.

Bảng reachability ở trên đã dự báo chính xác chỗ này: sinh lại truy vấn trên **cùng bộ bằng
chứng** không lấy lại được đáp án, vì với q432 và q727 bằng chứng không chứa đáp án. Việc dự
báo đúng làm phép kiểm miễn phí đó đáng dùng lại trước mọi đường kiểu retry sau này.

Hai chi tiết trong bảng chỉ tiếp chỗ hỏng thật. q433 và q446 ra **đúng 100.0**, tức truy vấn
chia một số cho chính nó: mô hình bị ép phải chia nên nó chia bừa. Và q1004 lệch **đúng 1e2**,
tức tỉ số đã tính đúng và chỉ thiếu bước nhân 100, nên nó chuyển từ "sai loại đại lượng" sang
bucket "lệch đúng 10^k" của `docs/miss_shape_2026-08-23.md`.

Phần code đã được trả lại (`git revert`), vì nó tốn thêm lượt gọi LLM trên 51/1012 câu mà
không thêm điểm nào. Giữ lại `scripts/gate_answer_type.py` và doc này làm bản ghi phép đo.

## Đây là đường thứ chín, và nó chết ở một chỗ mới

Tám đường trước chết ở bước **phát hiện**: cái tưởng là tín hiệu hóa ra là cỡ rổ, độ dài
nhãn, hoặc chỗ v9 vốn đã đúng. Đường này phát hiện được thật, 7 câu trên 119 và 51 trên 1012,
chứng minh được từng câu, không cần nhãn. Nó chết ở bước **sửa**.

Đó là thông tin mới và nó hẹp lại chỗ còn phải tìm: vấn đề không phải pipeline không biết
mình sai, mà là biết mình sai cũng không đủ để làm đúng, vì bằng chứng đưa vào prompt không
chứa đáp án. Đường tiếp theo nếu có thì phải tác động vào truy hồi, không vào codegen.
