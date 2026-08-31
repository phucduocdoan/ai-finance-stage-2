# Nhãn máy có thay được nhãn cũ không: 83% rồi 95.8%, phương sai nằm ở lượt gán (2026-08-23)

Công cụ: `scripts/gate_label_calibration.py`, readout ở
`artifacts/runs/gate_label_calibration.out`.

## Câu hỏi và mốc chốt trước

Ta có 120 nhãn cho 1012 câu. Ở n = 119, p = 0.41, một sigma lấy mẫu là 4.5 điểm, nên
thước không phân giải nổi thay đổi nào dưới cỡ 10 câu bị lật. Đặt thêm vài trăm nhãn máy
sẽ hạ sigma đó, nhưng chỉ đáng làm nếu nhãn máy đủ tin. Mốc chốt trước khi chạy:

- khớp ≥ 95% → nhãn máy dùng được, đặt thêm vài trăm câu
- khớp < 90% → dừng, sống với tập nhãn nhỏ

Thiết kế: 24 câu rút phân tầng theo bậc L1-L6 (seed 20260823) từ chính tập **đã có
nhãn**, đưa cho một agent chỉ thấy id và đề bài
(`artifacts/label_calib/blind_tasks.jsonl`). Nhãn cũ giấu ở `gold_hidden.json`. Agent bị
cấm đọc `artifacts/eval_clean/`, `output/`, `artifacts/runs/`, và tự khai đã tuân thủ.

## Kết quả: 20/24 = 83%

| quan hệ với nhãn cũ | số câu |
|---|---|
| khớp | 20 |
| khác hẳn | 3 (q714, q764, q836) |
| lệch dấu | 1 (q774) |
| lệch thang | 0 |

**83% < 90%, nên theo mốc đã chốt: dừng, không đặt thêm nhãn.** (Lượt B sau đó ra 95.8%
trên đúng 24 câu này; xem mục "Lượt B" bên dưới. Kết luận cuối cùng khác kết luận của
riêng lượt A.)

Lọc theo tin cậy tự khai không cứu được:

| tin cậy tự khai | khớp |
|---|---|
| high | 15/17 = 88% |
| medium | 4/6 = 67% |
| low | 1/1 |

Ngay cả nhóm `high` cũng chỉ 88%, vẫn dưới 90%. Và agent tự đoán sai chỗ yếu của mình:
nó tự gắn cờ q836 và q774 (đúng, cả hai lệch) nhưng cũng gắn cờ q267 và q968 (cả hai lại
khớp), trong khi hai câu lệch còn lại (q714, q764) nó khai `high`.

Bốn câu lệch không cùng một kiểu:

- **q714** 168.74 so với 238.89. Lệch nội dung thật. Câu này đã được ghi nhận ở
  `docs/l1_cell_cause_2026-08-22.md`: gold cần hiệu của hai dòng, còn có một dòng đã gộp
  sẵn trên bảng đọc thẳng ra được. Hai lượt gán nhãn chọn hai cách đọc khác nhau.
- **q764** 2.94 so với 2.99, lệch 1.8%. Gần khớp, nhưng grader của BTC chấm chặt
  (§7.1 của `docs/leaderboard_and_strategy_2026-08-21.md`) nên 1.8% vẫn là sai.
- **q836** 280.54 so với 289.37. Nguồn không có bảng "trích lập" cho đủ các năm, agent
  thay bằng dòng chi phí dự phòng trong thuyết minh SG&A, tức thay khái niệm.
- **q774** chỉ lệch dấu, quy ước "chênh lệch giữa A và B".

## Điều quan trọng nhất: hai bên của phép so đều do Claude gán

`artifacts/eval_clean/labels_*.jsonl` **không phải gold của BTC**. Nó là một lượt gán
nhãn trước, cũng do agent đọc OCR thô, và `docs/leaderboard_and_strategy_2026-08-21.md`
§8 đã tự đính chính đúng điểm này: "tái lập được" không phải "đúng".

Nên 83% đo **tính nhất quán giữa hai lượt của cùng một mô hình**, không đo tính đúng. Hệ
quả đi theo hai hướng, cả hai đều xấu:

1. Nếu hai lượt lệch nhau 17% thì tầng nhãn có nhiễu riêng cỡ đó, cộng thêm vào sigma
   lấy mẫu 4.5 điểm. Thước còn cùn hơn tôi đã tính.
2. Phần hai lượt **đồng ý** cũng không chứng minh được gì, vì sai lệch tương quan giữa
   hai lượt của cùng một mô hình là không quan sát được từ đây. Thêm nhãn máy hạ được
   nhiễu ngẫu nhiên nhưng không hạ được thiên lệch chung.

Điểm 2 mới là lý do thật để dừng. Mốc 95% chỉ là quy tắc; cái đáng nói là kể cả đạt 95%
thì nhãn máy vẫn không cấp được thứ ta cần, tức một điểm neo độc lập với mô hình đang
làm pipeline.

Gộp với lượt đối chứng trước (14/15 ở §8 của doc leaderboard): **34/39 = 87%** trên hai
lượt độc lập.

## Đính chính một luận điểm tôi đã dùng trong cùng ngày

Ở `docs/l3_pair_2026-08-23.md` phát hiện 6, tôi bỏ ba câu "thắng nhờ dấu" (q580, q603,
q624) với lý do "nhãn tay thật cho 0 câu lệch dấu trong 119 câu, nhãn máy khai 3/15, nên
quy ước dấu của nhãn máy lệch với quy ước của người". Chữ "của người" là sai: 119 nhãn đó
cũng do Claude gán. Phép so đó là một lượt agent đối một lượt agent, nó **không** xác lập
quy ước của BTC.

Điều còn đứng: v9 nhất quán về dấu với lượt nhãn cũ ở 10/10 câu so sánh mà v9 đúng độ
lớn, còn lượt nhãn mới lệch dấu ở 3/15 và ở q774. Nghĩa là hai lượt gán nhãn không thống
nhất với nhau về quy ước dấu, chứ chưa biết bên nào đúng.

Kết luận của phát hiện 6 không đổi. Nếu tính cả ba câu dấu là thắng thì sổ kết thành
4 thắng / 1 mất, McNemar một phía p = 0.188, vẫn dưới mốc 10/2. Đường L3 hai kỳ vẫn chết
dù giải quyết câu dấu theo hướng nào.

## Lượt B: 23/24 = 95.8%, và nó đổi kết luận

Lượt gán nhãn thứ hai, cùng 24 câu, cùng điều kiện mù, khác agent:

| tin cậy tự khai | lượt A | lượt B |
|---|---|---|
| high | 15/17 = 88% | 16/16 = 100% |
| medium | 4/6 = 67% | 6/7 = 86% |
| low | 1/1 | 1/1 |
| **tổng** | **20/24 = 83%** | **23/24 = 95.8%** |

Lượt A dưới mốc dừng 90%, lượt B trên mốc đặt thêm 95%. Chốt trước hai mốc mà kết quả rơi
vào hai phía là dấu hiệu rõ: **phương sai nằm ở người gán nhãn, không ở việc gán nhãn máy
nói chung.** Một lượt đơn lẻ không phải phép đo tin được, nhưng đó là lỗi thiết kế của
"một lượt", không phải giới hạn của nhãn máy.

Phép so ba chiều tách được đúng chỗ đó:

| | số câu |
|---|---|
| cả ba khớp | 20 |
| một lượt khớp nhãn cũ, lượt kia lệch (q714, q764, q836) | 3 |
| hai lượt mới khớp nhau, lệch nhãn cũ → nhãn cũ là nghi phạm (q774) | 1 |
| ba đáp án khác nhau → câu tự nó mơ hồ | 0 |

**Không có câu nào cả ba đáp án khác nhau.** Nghĩa là không câu nào trong 24 câu này mơ hồ
đến mức vô vọng; mỗi lần lệch đều có hai trong ba bên đồng ý. Ghép cặp hai lượt rồi lấy
phần đa số giải quyết được 23/24.

q774 là câu duy nhất nhãn cũ đứng một mình: cả hai lượt mới đều nói −204503, nhãn cũ nói
+204503. v9 cũng ra +204503, nhưng vì `pandas_query` của nó bọc `abs(...)`, nên dấu dương
đó là do luật chứ không do đọc bảng. Ba bên độc lập về dấu thì hai bên chọn âm.

Điều này **không** phủ nhận luận điểm quan trọng ở trên: hai lượt mới cũng đều do Claude
gán, nên 95.8% vẫn là tính nhất quán, không phải tính đúng, và thiên lệch chung giữa các
lượt vẫn không quan sát được từ đây. Nhưng nó đổi phần khả thi: nếu muốn đặt thêm nhãn thì
cách làm là **hai lượt cộng một lượt phá thế**, không phải một lượt.

## Việc còn mở

Chưa chốt có đặt thêm vài trăm nhãn theo cách hai-lượt hay không. Giá phải trả gấp đôi
mỗi câu, và cái nó mua được vẫn chỉ là hạ nhiễu ngẫu nhiên, chứ không cấp được điểm neo
độc lập với mô hình đang chạy pipeline.
