# Thẻ doc_type sai: có thật, đo được, nhưng chỉ đáng 2 câu (2026-08-23)

Manh mối đến từ lượt gán nhãn B trong `docs/label_calibration_2026-08-23.md`. Nó giải
thích được vì sao lượt A sai ở q714 và q764 bằng một cơ chế nằm trong metadata chứ không
nằm trong cách đọc bảng, và dự đoán rằng một pipeline lọc theo `doc_type` một cách ngây
thơ sẽ ra đúng hai con số sai của lượt A. **Dự đoán đó trúng trên q764: v9 đọc
`DPM_financial_statements_2015_consolidated|5` và ra đúng 2.99, con số của lượt A.**

Đó là một cơ chế đã chạm tới lỗi thật của pipeline, nên đáng đo cho hết. Đây là lần đầu
trong mạch này một manh mối có tính chất đó: đo được mà không cần thêm nhãn.

## Hai hình dạng lỗi, không phải một

**Đảo thẻ.** `HUT_financial_statements_2024`: bản gắn thẻ `_consolidated` và bản gắn thẻ
`_separate` bị đổi chỗ cho nhau.

**Gộp hai bộ dưới một thẻ.** `DPM_financial_statements_2015_consolidated` chứa cả bảng cân
đối riêng lẫn hợp nhất, tổng 4 bảng `balance_sheet` dưới cùng một thẻ.

## Đếm trên toàn corpus

146.246 bảng, 1.965 báo cáo.

Dấu hiệu thô đầu tiên tôi dùng, "có từ 3 bảng `income_statement` hoặc từ 4 bảng
`cash_flow`", cho 286 báo cáo = 15%. **Con số đó sai và tôi đã bỏ.** Một bảng cân đối bị
OCR cắt qua hai trang cũng sinh ra nhiều bảng cùng loại, nên dấu hiệu đó gộp lỗi thật với
chuyện cắt trang bình thường.

Dấu hiệu đúng là **nhãn dòng có lặp lại hay không**. Hai bộ báo cáo gộp dưới một thẻ sẽ
lặp phần lớn nhãn dòng; một báo cáo bị cắt trang thì nhãn dòng rời nhau. Ngưỡng: giao của
hai tập nhãn dòng ≥ 60% tập nhỏ hơn.

| | báo cáo |
|---|---|
| kiểm được (≥2 bảng cùng loại, đủ nhãn) | 1.950 |
| lặp nhãn ≥60% → chứa hai bản của cùng một loại | **100 = 5%** |
| nhãn rời → chỉ là một báo cáo bị cắt trang | 1.850 |
| không kiểm được | 15 |

`DPM_2015_consolidated` cho 0.89, đúng như dự đoán. `HUT_2024` cho 0.0 ở cả hai bản, vì nó
là lỗi đảo thẻ chứ không phải lỗi gộp; dò riêng theo dấu hiệu "bản riêng có dòng cổ đông
thiểu số mà bản hợp nhất không có" thì **cả corpus chỉ có 1 báo cáo**, chính là HUT_2024.
Lỗi đảo thẻ là ca lẻ, không phải hạng mục.

## Phơi nhiễm không dự báo được lỗi

110/1012 câu chạm một báo cáo thuộc nhóm 100 đó, tức 11%. Trong 119 câu chấm được thì 21
câu chạm.

| | v9 đúng |
|---|---|
| câu chạm báo cáo hai-bản | 10/21 = 48% |
| câu không chạm | 39/98 = 40% |

**Câu bị phơi nhiễm lại đúng nhiều hơn một chút.** Phơi nhiễm không phải yếu tố dự báo lỗi.
Điều này chưa giết được giả thuyết, vì phơi nhiễm chỉ nói báo cáo có bản trùng, chưa nói
pipeline có chọn nhầm bản hay không. Nhưng nó đã cắt mọi phiên bản "lỗi này lan rộng".

## Phép đo thẳng vào cơ chế

Câu hỏi đúng: trong những câu v9 sai, có bao nhiêu câu mà **một bản sao khác của chính dòng
đã dùng** lại cho ra gold?

Cách đo: lấy chỉ số `iloc` trong `pandas_query` của v9, tra ngược ra nhãn dòng thật, rồi
quét mọi bảng khác trong cùng báo cáo có nhãn dòng đó, thử mọi ô của dòng đó với các hệ số
1e±3/6/9. Công cụ: `scripts/gate_doc_type_bug.py`, readout ở
`artifacts/runs/gate_doc_type_bug.out`.

| | câu |
|---|---|
| v9 sai, chấm được | 70 |
| dò được nhãn dòng đã dùng | 61 |
| **có bản sao khác cho đúng gold** | **2** |

Hai câu đó:

- q267: v9 = 3.372.600, gold = 340.063, bản sao `ACB_..._2020_separate|55` cho đúng 340.063
- q667: v9 = 1.42, gold = 1.24, bản sao `EIB_..._2023_separate|91` cho 1.247.796

## Mặt trái, và vì sao đường này chết

Trần trên là 2 câu. Mốc đã chốt từ trước là 10 lật thắng / 2 lật thua (McNemar một phía
p = 0.019). 2 câu không tới mốc kể cả khi không mất câu nào.

Mà sẽ mất. Trong 47 câu v9 **đúng** và dò được nhãn dòng, **10 câu** có dòng đã dùng còn
bản sao đọc ra được số ở bảng khác cùng báo cáo. Một luật kiểu "ưu tiên bản sao khác" đặt
10 câu đang đúng vào vòng rủi ro để đổi lấy nhiều nhất 2 câu. Tỉ số đó xấu theo cả hai
hướng: quá nhỏ để đo được, và nhiều khả năng âm.

**Kết: đường doc_type chết.** Lỗi metadata là có thật, đã xác nhận trên hai báo cáo cụ thể,
và trên q764 nó gây ra lỗi thật của pipeline. Nhưng nó chiếm 5% số báo cáo và 2/70 số câu
sai, nên sửa nó không di chuyển được thước đo.

## Điều đáng giữ lại

Con số 15% ban đầu và con số 5% cuối cùng chênh nhau ba lần, và cả chênh lệch đó nằm ở chỗ
tôi chọn dấu hiệu. Dấu hiệu đầu là đếm bảng, dấu hiệu sau là so nhãn dòng. Khi định giá
một lỗi metadata, đếm bảng gần như luôn thổi phồng, vì OCR cắt trang trông giống hệt lỗi
gộp bộ.

Đây là đường thứ năm được định giá rồi bỏ trong mạch này. Bốn đường trước đều chết vì
"bắn trúng chỗ v9 đã đúng". Đường này chết vì lý do khác: cơ chế đúng, nhưng khối lượng
nhỏ. Đó là lý do đáng tin hơn, và nó khép lại nhóm giả thuyết "lỗi nằm ở chọn nhầm bảng
trong cùng báo cáo".
