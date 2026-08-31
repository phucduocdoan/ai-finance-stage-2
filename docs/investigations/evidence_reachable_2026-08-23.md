# Bằng chứng đưa vào prompt chạm gold ở mức ngẫu nhiên: trần trên của codegen (2026-08-23)

Đường thứ chín (`docs/answer_type_2026-08-23.md`) chết ở bước sửa chứ không ở bước phát hiện,
và lý do là q432 có 4 ô số cho một câu sàng lọc 10 công ty. Phép đo này hỏi thẳng câu đó trên
cả 119 câu: **các ô mà truy vấn đã đọc có chứa đáp án không?**

Công cụ `scripts/gate_evidence_reachable.py`, readout `artifacts/runs/gate_evidence_reachable.out`.

## Đối chứng phải là hoán vị, không phải nhóm câu đúng

Một câu có 101 ô số là hơn 10 nghìn cặp, nhân 7 hệ số, với dung sai 1%: chạm gold ngẫu nhiên
gần như chắc chắn. Và rổ ô của câu sai to hơn (101 so với 69), đúng cái confound đã giết trục
chọn bảng.

Nên sàn nhiễu ở đây là gold **của câu khác**, đo trên đúng rổ ô đang xét, 30 câu mỗi lần. Sàn
vì thế tự mang cỡ rổ theo, nên hiệu số không còn đọc được thành cỡ rổ. Ba dạng công thức được
thử, vì một ô đơn không thể ra một tỉ lệ: ô đơn nhân hệ số, `a/b` và `a/b*100`, và `a-b` nhân
hệ số.

## Kết quả

| | n | chạm gold | sàn hoán vị | vượt sàn | ô/câu |
|---|---|---|---|---|---|
| v9 sai | 61 | 87% | 81% | **6 điểm** | 101 |
| v9 đúng | 46 | 98% | 70% | **28 điểm** | 69 |

Trên câu rổ nhỏ (dưới 40 ô), nơi sàn nhiễu còn thấp nên phép đo đáng tin hơn:

| | n | chạm gold | sàn hoán vị | vượt sàn |
|---|---|---|---|---|
| v9 sai | 14 | 43% | 32% | **11 điểm** |
| v9 đúng | 19 | 95% | 41% | **54 điểm** |

Đọc thẳng: trên câu v9 sai, tỉ lệ chạm gold **gần bằng mức ngẫu nhiên**. Trên câu v9 đúng nó
vượt sàn 28 điểm ở tập đầy và 54 điểm ở tập rổ nhỏ.

Chỉ 8/61 câu sai là không chạm được dưới bất kỳ dạng nào (q169, q267, q336, q432, q596, q629,
q727, q1009), nên phát biểu đúng **không phải** "bằng chứng rỗng". Phát biểu đúng là: những
lần chạm được trên câu sai phần lớn là trùng ngẫu nhiên trong một không gian tổ hợp rất lớn.
36/53 lần chạm đi qua dạng `a/b` trên mọi cặp ô, tức đúng dạng có sàn nhiễu `ô^2` và cũng là
dạng dễ trùng bừa nhất.

q629 nằm trong nhóm 8 câu chết, và nó khớp với một quan sát trước đó: câu này đọc đúng nhãn
dòng `Dự phòng phải thu ngắn hạn khó đòi` ở cả hai kỳ mà vẫn ra 184.19 so với gold 46.52. Giờ
có lời giải thích, đúng dòng nhưng sai bảng, vì gold không có mặt trong các ô đã đọc.

## Nhóm câu đúng ở đây là thước đo độ nhạy, không phải đối chứng

Phải nói rõ chỗ này vì nó dễ bị đọc quá lên: câu v9 đúng thì đúng **vì** bằng chứng chứa đáp
án, nên 98% và 95% một phần là đồng nhất thức, giống hệt cột "bảng đã đọc" trong
`docs/table_selection_2026-08-23.md`. Vai trò của nhóm đó ở đây không phải một đối chứng có
thể ngả về phía nào, mà là bằng chứng rằng **phép đo đủ nhạy để phát hiện chạm gold thật**:
nó tách được 54 điểm khi cái cần tách có ở đó. Đối chứng thật vẫn là sàn hoán vị.

Chính vì thế con số 6 điểm và 11 điểm mới đọc được. Một phép đo không nhạy cũng cho hiệu số
nhỏ, và ở đây đã loại được khả năng đó.

## Giới hạn phải nói trước khi dùng kết luận này

Ba dạng công thức được thử đều là một hoặc hai ô. Không dạng nào diễn tả được một tổng hợp
6 tới 10 công ty, mà đó đúng là hình dạng của tier L5. Với những câu ấy phép đo **thiếu lực**
theo đúng hướng làm reachability trông thấp hơn thật.

Nên phát biểu mạnh nhất mà số liệu đỡ được chỉ giới hạn ở câu một công ty và rổ nhỏ, nơi
95% so với 43% là một khoảng cách rất rõ. Với khối nhiều công ty, kết luận đúng không phải
"bằng chứng không chứa đáp án" mà là "câu hỏi này không đo được bằng phép đo này", vì không
bảng đơn lẻ nào chứa một tổng hợp nhiều công ty.

Lát cắt sạch nhất, chỉ dạng ô đơn trên câu `answer_shape = single_cell`, nơi sàn nhiễu chỉ là
`ô x 7`: v9 đúng 12/15 = 80%, v9 sai 5/9 = 56%. Cùng chiều, nhưng n = 9 nên nó chỉ là chứng
cứ phụ.

## Điều này đóng lại cái gì

Chín đường đã định giá và không đường nào tới mốc. Phép đo này giải thích tại sao theo một
cách khác các phép đo trước: với câu v9 đang sai, thứ mà codegen được nhìn thấy chạm gold ở
mức ngẫu nhiên. Mọi cải tiến ở codegen, dù là fuzzy tên cột, chọn dòng, chọn cột, hay validator
loại đại lượng, đều làm việc trên cùng bộ ô đó. **Trần trên của cả nhóm đó bị chặn bởi thứ
được đưa vào prompt, không bởi cách prompt được xử lý.**

Đó là lý do đường thứ chín chuyển đổi 0/7 dù phát hiện đúng 7/7, và là lý do không nên thiết
kế đường thứ mười ở cùng tầng.

## Việc kế tiếp, và nó không còn là chuyện mua nhãn

Đề xuất trước của tôi là mua nhãn mức ô cho một mẫu của 57 câu để biết chúng sai vì đâu.
Phép đo này trả lời phần lớn câu đó miễn phí, nên khoản chi ấy không còn cần thiết.

Hai việc còn lại, và chúng không cạnh tranh nhau:

Thứ nhất, chuyển ngân sách sang bước quyết định ô nào được đưa vào prompt. Lưu ý một chỗ căng
với `docs/table_selection_2026-08-23.md`: ở đó cả tầng shortlist lẫn tầng còn-lại-của-báo-cáo
đều không vượt sàn sau khi chuẩn hóa. Cách đọc duy nhất khớp cả hai phép đo là với khối nhiều
công ty thì **không bảng đơn lẻ nào chứa gold**, nên câu hỏi đúng không phải "chọn bảng nào"
mà là tổng hợp qua nhiều báo cáo. Việc đo tiếp phải hỏi ở mức tổng hợp, không ở mức bảng.

Thứ hai, mở rộng tập eval từ 119 lên ~400 câu. Chín đường đều đáng 2-3 câu trước 1 sigma là
5.4 câu, nên không đường nào trong số đó từng có thể chứng minh được gì. Thiết kế đã có ở
`docs/label_calibration_2026-08-23.md`.
