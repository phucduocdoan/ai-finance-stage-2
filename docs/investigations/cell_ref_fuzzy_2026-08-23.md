# Fuzzy ở bước codegen chọn ô: 0 câu, và chỗ hỏng thật nằm ở tiêu đề hai tầng (2026-08-23)

Giả thuyết vào, đúng chỗ được chỉ: truy vấn sinh ra gõ tên cột lệch so với tên cột thật nên
chọn nhầm ô. Ca mẫu là q774, `df1.iloc[1]['31/12/2022 Triệu VND'] - df2.iloc[0]['31/12/2022Triệu VND']`,
một cột có dấu cách một cột không.

Đường này có hình dạng khác năm đường trước, và đó là lý do nó đáng đo: fuzzy **chỉ nổ khi
truy vấn hiện tại đã lỗi**, nên phần thua bị chặn trên bằng kiến trúc chứ không bằng lập
luận. Mốc chốt trước khi chạy vẫn là 10 thắng / 2 thua.

Kết quả: **0 thắng / 0 thua trên 119 câu, trần trên là 6 câu trên 1012.** Công cụ
`scripts/gate_cell_ref_fuzzy.py`, readout `artifacts/runs/gate_cell_ref_fuzzy.out`.

## Chọn nhầm ô hầu như không làm truy vấn lỗi

Chạy lại đúng 1012 truy vấn đã nộp trên chính bảng bằng chứng của nó:

| | câu |
|---|---|
| chạy được, và ra đúng con số đã nộp | 964 |
| chạy được nhưng ra số khác | **0** |
| chạy lỗi | 48 = 4.7% |

Trong 48 câu lỗi, chỉ **6 câu** có đáp án nộp bằng 0.0, tức chỉ 6 câu là codegen chết thật.
42 câu còn lại nộp đáp án khác 0 kèm một truy vấn không chạy, nghĩa là đáp án đến từ một
solver khác còn chuỗi truy vấn thì được ghép lại. Đó là lỗi của mục tiêu chấm "chạy lại truy
vấn", không phải của mục tiêu chấm đáp án, và nó là phát hiện phụ đáng ghi riêng.

Trên 119 câu chấm được, 8 câu có truy vấn lỗi. Fuzzy sửa được 0 trong 8. Trần trên của cả
đường này là 6 câu trên 1012, dưới mốc kể cả khi sửa hết.

## Bản im lặng của giả thuyết cũng không đứng

Câu hỏi thật của "chọn nhầm ô" là bản không lỗi: cột tồn tại, chỉ là cột sai. Phép đo, đúng
khuôn đã dùng cho chọn nhầm dòng: với truy vấn đọc một ô, có **cột khác của chính hàng đó**
cho ra gold không, cho phép hệ số 1e±3/6/9.

| tập | có cột khác của cùng hàng trùng gold |
|---|---|
| v9 sai | 1/23 = 4% |
| v9 đúng | 2/27 = 7% |

Tỉ lệ trên câu sai **thấp hơn** đối chứng. Chọn nhầm cột trong đúng hàng không phải nguồn
lỗi. Cộng với `docs/row_match_2026-08-23.md` (chọn nhầm dòng: 43% so với sàn nhiễu 30%, vượt
sàn khoảng 3 câu), cả hai trục của một tham chiếu ô đều đã đo và đều không phải khoảng trống.

## Chỗ hỏng thật: tiêu đề hai tầng, và tầng ngoài không đủ để chọn

38/48 câu lỗi vì gõ một chuỗi không phải tên cột thật. Hình dạng áp đảo không phải lệch dấu
cách như q774, mà là **tiêu đề hai tầng bị làm phẳng thành `ngoài | trong`, và mô hình chỉ
gõ tầng ngoài**:

| câu | gõ | cột thật |
|---|---|---|
| q21 | `'31/12/2020'` | `'31/12/2020 \| Triệu VND'` |
| q41 | `'31/12/2016'` | `'31/12/2016 \| Giá gốc'`, `'31/12/2016 \| Dự phòng'` |
| q234 | `'Số cuối năm'` | `'Số cuối năm \| Số lượng'`, `'Số cuối năm \| Giá trị VND'` |

Và đây là chỗ đường này chết chứ không phải chỗ nó thắng: **27/38 câu có tầng ngoài khớp
nhiều hơn một cột con.** Giá gốc so với dự phòng, số lượng so với giá trị, là hai con số
khác nhau, và cái chọn giữa chúng là câu hỏi, không phải tên cột. Không có cách so chuỗi nào
giải được, vì thông tin cần dùng không nằm trong chuỗi.

Nên luật fuzzy đúng phải biết từ chối: chỉ nhận khi tiền tố khớp **đúng một** cột. Sau khi
siết như vậy, số câu sửa được rồi chạy được là 4/48, và không câu nào trong 119 câu chấm
được.

## Hai lỗi của phép đo, ghi lại vì cả hai đều làm số nhỏ đi

**Gom cột của mọi frame.** Bản đầu so chuỗi với danh sách cột của toàn bộ frame trong truy
vấn. Hai bảng của hai năm gần như luôn có cùng tên cột, nên mọi tên đều thành "nhập nhằng"
và bị từ chối. Đã sửa thành gắn chuỗi với đúng biến `dfN` của nó qua một regex trên
`dfN[...]` và `dfN.iloc[i][...]`. Sửa xong con số không đổi (vẫn 4/48), tức lần này giả
thuyết về nguyên nhân sai nhưng kết luận không đổi.

**`Unnamed: 4` khớp `Unnamed: 0`.** `difflib` cho tỉ lệ 0.875, vượt mốc 0.85, mà
`Unnamed: 0` là cột nhãn chỉ tiêu chứ không phải cột số. q729 sửa xong đổi từ `KeyError`
sang `TypeError`. Tên `Unnamed: N` không mang nghĩa nào để so, nên đã loại khỏi cả hai phía.

Một chi tiết nhỏ nữa: `errors="coerce"` là hằng chuỗi trong `pd.to_numeric` nên bị đếm là
"gõ sai tên cột". Đã loại giá trị của tham số có tên khỏi phép đếm, 39 xuống 38.

## Điều đáng giữ lại

Ba phép đo liên tiếp giờ đã khoanh xong một tham chiếu ô. Báo cáo đúng đã có (`b411f8e`,
66/70). Dòng thì fuzzy không cứu được và trần chỉ ~3 câu (`docs/row_match_2026-08-23.md`).
Cột thì thấp hơn sàn nhiễu, và phần lỗi thật là tiêu đề hai tầng nhập nhằng mà so chuỗi
không có thông tin để giải.

Đây là đường thứ sáu được định giá rồi bỏ. Nó cũng chốt luôn một điều rộng hơn: **mọi biến
thể "fuzzy hơn" hay "trọng số khác" ở bước tham chiếu ô đều không còn chỗ**, vì cả ba trục
đã có số và không trục nào tới mốc. Việc còn lại nằm ở bước chọn bảng nào của báo cáo được
đưa vào prompt, là chỗ `lookup.py` tự ghi 49/60 trên tập 60 câu cell-truth và chưa ai đo lại
trên 119.

## Phát hiện phụ, không thuộc mục tiêu đáp án

42/1012 câu nộp một truy vấn không chạy được kèm một đáp án đúng-về-số. Nếu ban tổ chức chấm
bằng cách chạy lại truy vấn thì 42 câu đó mất điểm ở thước đo ấy mà không mất gì ở thước đo
đáp án. Sửa nó không di chuyển điểm đáp án, nên nó không phải một đường cạnh tranh với các
đường khác, nhưng nó là điểm rơi tự do nếu thước đo thứ hai có tính.
