# Nguyên nhân sai của 15 câu L1, đọc lại từ CSV thật (2026-08-22)

Công cụ: `scripts/gate_l1_cell_cause.py output/submission_v9_sign/submission.json`.
Kết quả thô lưu ở `artifacts/runs/gate_l1_cell_cause.out`. Không gọi LLM, không
chạy lại pipeline, chỉ mở file csv mà chính submission đã dùng.

## Số câu

Tập L1 chấm được: 37 câu (22 đúng, 15 sai). Cả 15 câu sai đều có `pandas_query`
khớp đúng dạng đọc một ô (`dfN.iloc[i]['col']`), nên không có câu nào phải xếp vào
"không phân giải được" vì lý do parse. Kịch bản tự động vẫn xếp 3/15 câu vào bucket
đó vì bộ so khớp nhãn của nó không quyết được (xem phần "hai chỗ script bó tay" bên
dưới); ba câu đó đã đọc tay và có kết luận riêng.

Đếm sau khi đọc tay cả 15 câu (khác một chút so với đếm thô của script, lý do nêu ở
mục kế tiếp):

| Nguyên nhân | Số câu |
|---|---|
| Sai hàng | 9 |
| Sai cả hai (hàng và cột) | 2 |
| Đúng ô, sai đơn vị | 2 |
| Sai cột | 1 |
| Không có báo cáo gold (đúng mã, đúng năm, sai bản riêng/hợp nhất) | 1 |
| Không phân giải được | 0 |

Cụm lớn nhất là **sai hàng: 9/15 (60%)**. Đây là nguyên nhân áp đảo trong nhóm L1
sai, khớp với nhận định ban đầu rằng đây là bài toán định vị ô, không phải bài toán
truy xuất.

## Ba câu script tự động không quyết được, đọc tay

Script gắn 3 câu (32, 169, 267) vào "không phân giải được" vì nhãn hàng VÀ nhãn
cột nó tính đều "khớp" với gold theo phép so khớp chuỗi, nhưng giá trị đọc ra vẫn
sai — tức là matcher không có cách phân biệt tiếp. Đọc trực tiếp báo cáo gốc:

- **q32** thật ra là **sai cả hai**. Bộ so khớp báo hàng khớp vì "Tiền" (đọc được)
  bị coi là nằm trong "phải thu **tiến** độ kế hoạch hợp đồng" (gold) — sau khi bỏ
  dấu, "tiến" và "tiền" đều thành "tien", một trùng âm ASCII tình cờ, không phải
  cùng một chữ. Cột cũng bị báo khớp sai: tên cột đọc được là "Tại ngày 31 tháng 12
  năm" không mang năm nào, năm thật (2024) nằm ở một dòng dữ liệu bị gộp vào header
  ("2024 VND") mà cột không giữ lại, nên so cột theo tên cột không phát hiện được
  rằng bảng này lấy nhầm cột của năm trước.
- **q169** là **sai hàng**, cụ thể là chỉ đọc một trong hai bảng cần cộng. Gold cần
  tổng "Trái phiếu Chính phủ sẵn sàng để bán + giữ đến ngày đáo hạn"; pipeline chỉ
  đọc một bảng con "Trái phiếu Chính phủ (Thuyết minh số 13)" nên tên hàng trùng
  một phần với gold nhưng thiếu bảng thứ hai.
- **q267** là **sai hàng**, do nhãn dòng bị trùng chữ giữa nhiều mục. Chuỗi "- Bằng
  ngoại tệ" xuất hiện dưới nhiều mục tiền gửi khác nhau trong thuyết minh (tiền gửi
  có kỳ hạn của khách hàng, tiền gửi không kỳ hạn, tiền gửi của tổ chức tín dụng
  khác...); dòng đọc được và dòng gold có đúng tên nhưng thuộc hai mục cha khác
  nhau, chỉ phân biệt được bằng dòng header phía trên, không phải bằng chính dòng
  đó.

## Năm câu đáng chú ý nhất

**q87 — HPX, "Giá vốn hàng bán" năm 2024, sai cột do bảng bị lệch cột.** Dòng đọc
đúng ("Giá vốn hàng bán"), nhưng file csv có cột tên "Năm 2024VND" chỉ chứa "6.2"
(một giá trị lạc, có vẻ là mảnh vụn của một ô khác), còn số đúng của gold
(1.097.119.148.438) lại nằm ở cột kế bên tên "Năm 2023VND". Tên cột và dữ liệu
trong file bị lệch nhau một cột — một lỗi trích xuất bảng, không phải lỗi chọn
hàng hay chọn cột của solver. Kết quả nộp là 0.0 (tính từ 6.2 * 1e-9 rồi bo tròn).

**q284 — EIB, "Vốn điều lệ" 31/12/2023, đúng ô nhưng nhân đơn vị hai lần.** Đọc
đúng dòng ("a | Vôn điều lệ", khớp gold "Vốn điều lệ") và đúng ô (17.469.561, khớp
tuyệt đối với `raw_cell_value` gold "17.469.561"). Nhưng bảng này đã ở đơn vị
triệu đồng, còn `pandas_query` lại nhân `1e-6` như đang xử lý VND thô, ra 17.47 —
kết quả nộp ("17.47") lẽ ra phải là "17469561.0" (triệu đồng) hoặc "17469.56" nếu
đổi ra tỷ. Ô đọc không sai, chỗ sai là suy luận đơn vị bảng.

**q109 — IJC, "Trả trước cho người bán ngắn hạn" 2016, sai hàng do trùng gần
nghĩa.** Gold muốn dòng tổng "Trả trước cho người bán ngắn hạn" (25.195.451.251).
Pipeline đọc "Trả trước cho các người bán khác" (5.576.335.963) — một dòng khác,
liền kề, trong cùng thuyết minh khoản trả trước, tên rất giống nhưng là mục "khác"
không phải mục "ngắn hạn". Đây đúng dạng "hàng gần nghĩa bị trùng" nêu trong yêu
cầu.

**q308 — DLG, "Cho vay dài hạn - Cộng" 2016, sai hàng vì lấy nhầm cả bảng dạng
đầu kỳ/tăng/giảm/cuối kỳ.** Gold cần thuyết minh "Phải thu về cho vay dài hạn"
(225.647.099.300). Pipeline đọc dòng đầu của thuyết minh "Vay ngắn hạn"
(517.950.110.299) — một bảng biến động nợ vay hoàn toàn khác (có cột Số đầu kỳ /
Tăng trong kỳ / Giảm trong kỳ / Số cuối kỳ), không liên quan đến khoản cho vay dài
hạn bên tài sản. "Vay" và "cho vay" là hai chỉ tiêu đối lập (nợ phải trả so với
phải thu), dễ nhầm khi chỉ so theo bề mặt chữ.

**q703 — GEX, công thức 5 số bị đọc thành một dòng tổng có sẵn.** Gold cần
`(phải thu khách hàng + phải thu cho vay ngắn hạn + phải thu khác) - (phải trả
người bán - phải trả khác)`, cả 5 số đều là dòng con. Pipeline đọc thẳng dòng tổng
"Các khoản phải thu ngắn hạn" (mã 130, giá trị 1.296.901.014.225) — một số có thật
trên bảng nhưng là tổng của một nhóm rộng hơn nhiều, không phải kết quả công thức.
Câu này được bộ phân bậc gán L1 vì câu hỏi đọc như một ô, nhưng gold thực chất cần
năm ô; q714 (HUT, "Doanh thu hoạt động tài chính - Chi phí tài chính") rơi vào
đúng dạng này: đọc một dòng đã gộp sẵn ("Lợi nhuận thuần từ hoạt động kinh doanh",
mã 30) thay vì hiệu của hai dòng gold cần.

## Cụm theo hình dạng bảng

- **Thuyết minh ngân hàng có nhiều tầng phân loại** (ngắn/trung/dài hạn, nội tệ/
  ngoại tệ, sẵn sàng để bán/giữ đến đáo hạn...): q51 (VCB), q169 (STB), q267 (ACB),
  q284 (EIB), q306 (EIB) — 5/15 câu sai, dù ngân hàng chỉ là một phần nhỏ trong 37
  câu L1. Các bảng này có nhiều dòng cùng tên gốc, chỉ khác tầng phân loại phía
  trên, đúng như giả thuyết ban đầu về việc dòng dễ nhầm ở các báo cáo ngân hàng.
- **Công thức nhiều ô bị đọc thành một dòng tổng có sẵn**: q169, q703, q714 —
  3/15 câu. Cả ba đều được gắn bậc L1 bởi bộ phân bậc theo văn bản câu hỏi, nhưng
  đáp án gold thực chất cần cộng/trừ nhiều dòng. Đây là giới hạn của việc phân bậc
  theo câu hỏi, không phải của cell locator riêng.
- **Bảng biến động (đầu kỳ/tăng/giảm/cuối kỳ)**: chỉ 1 câu rõ ràng (q308), không đủ
  để gọi là cụm lớn trong 15 câu này.
- **Lệch cột do OCR/trích xuất bảng**: 1 câu (q87), nhưng đáng chú ý vì nó là câu
  "sai cột" duy nhất trong 15 câu, và lỗi nằm ở khâu trích xuất bảng chứ không ở
  logic chọn ô.

## Kiểm định trên 22 câu đúng

Chạy đúng phép so khớp nhãn hàng trên 22 câu ĐÃ ĐÚNG (bỏ qua nhánh so theo giá trị
gold, vì với câu đúng giá trị luôn khớp và nhánh đó sẽ luôn thắng trước, không nói
lên gì về độ tin của riêng phép so nhãn). Kết quả: nếu chỉ dùng logic giá trị +
nhãn đầy đủ như script chạy, 1/22 câu bị matcher báo "sai hàng" một cách oan
(q4: gold "XI. LỢI NHUẬN KẾ TOÁN SAU THUẾ TNDN" so với dòng đọc được "Lợi nhuận
sau thuế" — cùng một khoản, pipeline lấy từ một bảng giải trình biến động lợi
nhuận đã tính sẵn theo triệu đồng, không phải từ báo cáo KQKD chính, nên câu chữ
khác gold nhưng số vẫn đúng). Tỷ lệ từ chối oan quan sát được là 1/22 ≈ 4,5%,
không cao nhưng không phải bằng không — số phần trăm ("sai hàng" trong bảng 15
câu) nên đọc như một xấp xỉ có sai số cỡ vài phần trăm theo hướng này, không phải
một con số tuyệt đối.

## Giới hạn của phép đo này

- Bộ so khớp nhãn chuẩn hoá bằng cách bỏ dấu, nên "tiến" và "tiền" (hai từ khác
  nghĩa) nhìn giống nhau sau khi bỏ dấu — đã gây một ca nhận nhầm (q32, xem trên).
- So khớp cột dựa trên tên cột trong file csv. Khi năm hoặc kỳ nằm ở một dòng dữ
  liệu bị gộp vào header (không nằm trong tên cột), phép so không phát hiện được
  cột sai (cũng q32).
- Script chỉ xử lý được `pandas_query` dạng đọc đúng một ô. Không có câu nào trong
  15 câu sai rơi vào trường hợp này, nhưng nếu chạy trên một submission khác có
  công thức nhiều ô ở bậc L1, script sẽ báo "không phân giải được" đúng như đã
  khai trong docstring, không đoán.
