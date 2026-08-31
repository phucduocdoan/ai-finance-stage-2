# 57/70 câu sai là một con số khác hẳn, không phải một lệch nhỏ (2026-08-23)

Tám lần định giá đều là đường "sửa một lệch nhỏ": chọn dòng bên cạnh, chọn cột bên cạnh,
chọn bản sao khác của bảng, sửa tên cột gõ sai, sửa đơn vị. Mỗi lần trần trên rơi vào 2-3
câu. Phép đo này hỏi trực tiếp vì sao, và nó không cần sàn nhiễu: lệch **đúng** một lũy thừa
của 10 hay **đúng** một dấu thì không phải trùng ngẫu nhiên.

Công cụ `scripts/gate_miss_shape.py`, readout `artifacts/runs/gate_miss_shape.out`.

| hình dạng của 70 câu sai | câu |
|---|---|
| lệch đúng 10^k | 5 |
| chỉ lệch dấu | 0 |
| lệch cả dấu và 10^k | 0 |
| đáp án 0.0 (truy vấn chết) | 8 |
| **một con số khác hẳn** | **57 = 81%** |

Một cạm bẫy có xuất hiện thật và phải trừ: dung sai 1% làm q267 (3.372.600 so với 340.063,
tỉ lệ 9.92) bị nhận là "đúng x10". Nên trục đơn vị đáng 4 câu, không phải 5.

Lỗi dấu đúng bằng 0, và đó là bằng chứng `as_magnitude` trong `execute.py` đang làm việc của
nó: mọi câu từng lệch dấu đã được sửa ở `abs(...)` bọc ngoài truy vấn.

## Vì sao đây là con số quan trọng nhất trong ngày

81% số câu sai không phải là gold bị đọc lệch một ô, một đơn vị hay một dấu. Nó là pipeline
tính ra một đại lượng khác. Điều đó giải thích được hình dạng của cả tám lần đo cùng một lúc:
mọi đường sửa-lệch-nhỏ đều chỉ có 13/70 câu để bắn vào, nên trần trên của chúng bị chặn ở
2-3 câu trước khi ai kịp thiết kế gì, và mốc 10 thắng / 2 thua không bao giờ nằm trong tầm.

Nói cách khác, tám lần đo trước không thất bại vì thiết kế kém. Chúng thất bại vì cả nhóm đó
nhắm vào 19% số câu sai, và ngay cả sửa hết 19% cũng chỉ được 13 câu, còn thực tế mỗi đường
chỉ chạm được một phần nhỏ của 13.

## Việc còn lại theo phép đo này

Đường duy nhất còn khối lượng là 57 câu "một con số khác hẳn", và định nghĩa của khối đó là
pipeline hiểu sai câu hỏi cần đại lượng gì, chứ không phải đọc lệch ô. Phân loại nó cần biết
gold thực sự là chỉ tiêu nào, tức cần nhãn ở mức ô chứ không chỉ ở mức số, và tập nhãn hiện
có không mang thông tin đó cho 119 câu.

Nên hai việc kế tiếp không cạnh tranh nhau mà nối nhau: mua nhãn mức ô cho một mẫu của 57
câu để biết chúng sai vì đâu, và mở rộng tập eval để mọi đường 3 câu trở nên đo được. Cả hai
đều tốn LLM, và cả hai đều là điều kiện cần trước khi thiết kế thêm bất cứ đường nào.
