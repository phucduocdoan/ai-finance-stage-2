# Chẩn đoán lớp câu 1 mã × ≥2 năm (2026-08-22)

Mổ 21 câu sai của lớp **1 ticker / ≥2 năm** trên clean eval (32 câu, 34% đúng). Ba sub-agent
mở từng bảng, dò từng ô, và tự phản biện lẫn nhau. Mỗi kết luận dưới đây đều có table_id +
iloc + con số tái tạo được gold.

Đọc kèm `docs/leaderboard_and_strategy_2026-08-21.md`,
`docs/retrieval_preprocessing_2026-08-21.md`, `docs/DECISIONS.md`.

---

## 0. Kết luận

**Retrieval không phải chỗ nghẽn của lớp này.** Nó chỉ chặn 3/21 câu. Phần lớn dữ liệu gold
đã nằm trong shortlist mà pipeline không dùng, hoặc dùng sai ô, hoặc trả sai *kiểu* đáp án.

| Nguyên nhân chính | Số câu | Câu |
|---|---:|---|
| **Sai ô** — đúng năm, sai bảng con / sai dòng | 5 | q496, q629, q641, q649, q821 |
| **Khác / preprocessing** | 4 | q947, q835, q611, q866 |
| **Sai kiểu đáp án** (hỏi "năm nào"/"%" mà trả số tiền) | 4 | q928, q842, q527, q528 |
| **Thiếu năm thật** — corpus/retrieval không có dữ liệu | 3 | q585, q588, q596 |
| **Bỏ quên năm** — bảng đúng có trong shortlist, query không chạm | 3 | q1004, q836, q544 |
| **Sai số học** (dấu, dùng max làm đáp án) | 2 | q894, q523 |

Lỗi **preprocessing/header** là nguyên nhân góp mặt ở **6 câu** (q641, q835, q596, q496, q611,
q866) — nhóm lớn nhất, và là loại lỗi mà không solver nào ở tầng trên sửa được.

**Phát hiện lớn nhất của cả đợt lại không nằm trong 21 câu này.** Truy nguyên q866 dẫn tới một
lớp lỗi header chưa ai xử lý, đã đo trên toàn bộ 146.246 bảng: **~9–11% corpus bị lệch cột**, 79%
trong số đó làm sai giá trị đọc ra, và hàm sửa hiện có chạy 81 lần thì **sai cả 81** (§5.1–5.3).

**q866 cần cả hai fix mới đúng** (§5): `project_year` sửa *kiểu* đáp án nhưng vẫn đọc đúng những
ô sai, nên sẽ trả 2019 thay vì gold 2018. Đây là bằng chứng cụ thể rằng "chạy được 16/17" của
`project_year` chỉ đảm bảo *ra một năm*, **không** đảm bảo ra *năm đúng* — chưa đo được bao nhiêu
trong 16 câu đó trả đúng.

---

## 1. Phát hiện lớn nhất: `project_year` là dead code

`src/finance_qa/modules/solve/codegen/execute.py:313` đã cài đúng cách xử lý câu "năm nào":
biến `max(<ô 2019>, <ô 2022>)` thành `(<ô thắng>) * 0 + <năm>`, giữ năm bên trong *query* nên
chạy lại submission vẫn ra năm. Nó **chưa từng chạy một lần nào**.

Lý do: `_SELECT_CALL = ^\s*(max|min)\s*\((?P<args>.+)\)\s*$` neo hai đầu, còn codegen luôn
bọc `round(...)`.

Toàn bộ 53 câu "năm nào" trong 1.012 câu:

| Dạng `pandas_query` | Số câu |
|---|---:|
| khớp `_SELECT_CALL` (cơ chế chạy) | **0** |
| `round(max(...))` — bị `round` chặn | 17 |
| max/min lồng sâu hơn | 1 |
| hằng số, không chạm bảng nào | 9 |
| không có max/min | 26 |

Tháo `round(...)` rồi gọi lại `project_year` với frames thật của từng câu: **chạy được 16/17**,
mỗi câu trả về một năm (2019, 2021, 2025, 2022, 2023, 2024) thay vì một số tiền. 53 câu = 5,2%
đề thi, hiện đúng 0 câu. 26 câu không có max/min và 9 câu hằng số **không** được cứu bằng cách
tháo `round`.

Đây là thay đổi nhỏ nhất trong tất cả những gì tìm được, nhưng nó chạm đường đi của 53 câu.
Chưa sửa — chờ quyết định.

---

## 2. Bẫy đo lường: dung sai 1% tương đối

`scripts/score_clean_eval.py`:

```python
TOL = 0.01
...
scale = max(abs(a), abs(b))
return scale > 0 and abs(a - b) / scale <= TOL
```

Với nhãn là **năm**, dung sai này vô nghĩa: 2018 vs 2019 lệch 0,05% → **chấm đúng**. Chính nó
đã báo q866 đúng trong lần kiểm đầu của tôi (trả 2019, gold 2018).

Nguồn gốc `TOL = 0.01`: **không có trong thể lệ**. `docs/competition/Thể lệ Stage 2.pdf` là bản
scan (`pypdf` rút ra 8 ký tự, `Read` không có `pdftoppm`); `submission_rule.txt` chỉ nói về
format. Đây là **quy ước của repo**, không phải luật. Docstring của file cũng đã ghi "con số
tuyệt đối của tập này cao hơn leaderboard khoảng 0,11".

Hệ quả: mọi câu "năm nào"/"mã nào" trong clean eval đang được chấm rộng tay. Cần một comparator
riêng cho nhãn phân loại trước khi tin bất kỳ delta nào trên lớp câu này.

---

## 3. Bug âm thầm: `unicodedata.normalize("NFD")` không phân giải `đ`

`đ` (U+0111) có category `Ll`, không phải `Mn`, nên vòng lọc dấu bỏ qua nó. Needle `co dinh`
**không** khớp `Tài sản cố định` (chuẩn hoá thành `tai san co đinh`).

```python
def norm(s):                                   # SAI
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()

def norm(s):                                   # ĐÚNG
    s = str(s).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
```

Bug này nằm trong helper probe tôi phát cho sub-agent, không nằm trong `src/`. Nhưng nó đã làm
sai lệch kết quả dò của cả ba agent trong vòng đầu, và bất kỳ probe nào tái dùng helper cũ đều
sẽ miss mọi nhãn chứa `đ` — tức phần lớn nhãn tài sản.

---

## 4. Ba kết luận bị phản biện lật lại

Agent 3 chạy vòng đối kháng và bác bỏ hai chẩn đoán "retrieval miss" của tôi:

- **q496** không thiếu dữ liệu. Gold chỉ cần dữ liệu 2022, cả hai bảng đều trong shortlist
  (index 0 và 20 trên 22). 2022 đúng là năm khấu hao cao nhất theo số thật:
  686,7 / 1.160,8 / 2.132,4 / **3.472,9** tỷ. Nguyên nhân thật: pipeline chia inventory cho
  chính nó trong `|6`, bỏ qua `|7` ở rank 20/22 → **sai ô**.
- **q523** cũng không phải retrieval miss ở nhánh chính: query dùng `max()` của các giá trị so
  sánh làm đáp án → **sai số học**. (Nhánh phụ vẫn thật: `DCM_2023_separate|12` giữ gold
  2.055.255.000 → 2,06 và nằm ngoài shortlist 35 bảng.)

Và một lần lật thứ ba, lần này lật chính vòng phản biện: **q866 không phải nhãn hỏng** (§5). Cả
tôi và agent 1 đã kết luận "nhãn sai" dựa trên dòng thuế con, trong khi query trỏ vào dòng
"Cộng". Đếm dòng CSV mới ra sự thật.

Bài học: needle lỏng tạo dương tính giả theo cả hai chiều, và **suy ra `iloc` từ nội dung thay vì
đếm dòng là nguồn sai lặp lại nhiều nhất trong cả đợt chẩn đoán này**. Ba lần lật đều bắt đầu từ
một giả định về "query đang đọc ô nào" mà không ai kiểm bằng cách đếm.

---

## 5. q866: nhãn gold ĐÚNG, lỗi ở cột — đã xác minh trên CSV thô

Câu hỏi: *"Với SJG, năm nào trong các mốc 2018, 2019, 2020, 2021 có tổng thuế và các khoản phải
nộp Nhà nước **lớn nhất**?"* → hỏi max. gold = **2018**.

Vòng chẩn đoán đầu (cả tôi và agent 1) kết luận "nhãn hỏng". **Sai** — vì cả hai đọc nhầm dòng mà
`pandas_query` trỏ tới. Đếm dòng CSV trực tiếp:

| bảng | số dòng CSV | `iloc` trong query | dòng thật |
|---|---:|---|---|
| `SJG_2018_consolidated\|45` | 15 (line0 = header) | `df3.iloc[13]` | **Cộng** (line14) |
| `SJG_2020_consolidated\|49` | 14 | `df4.iloc[12]` | **Cộng** (line13) |
| `SJG_2019_consolidated\|51` | 16 | `df5.iloc[14]` | **Cộng** (line15) |

Model chọn **đúng dòng**: "Cộng" là tổng cả note (thuế + phí, lệ phí + lợi nhuận nộp NS), khớp
"tổng thuế và các khoản phải nộp Nhà nước" tốt hơn dòng con trùng tên. Lỗi nằm **hoàn toàn ở
cột** (§5.1):

| Đọc trên dòng "Cộng" | 2018 | 2019 | 2020 | max |
|---|---|---|---|---|
| Theo tên cột `cuối năm` (query gốc) | 561,98 tỷ | **703,99 tỷ** ← = predicted | 618,57 tỷ | 2019 ✗ |
| Số dư cuối kỳ thật, sau khi căn lại header | **386,95 tỷ** | 307,75 tỷ | 249,46 tỷ | **2018 ✓ khớp gold** |

Xác minh cách căn lại, **khớp đến từng đồng, hai lần liên tiếp trên hai cặp bảng độc lập**:
`|45` Cộng col6 = `386.945.215.579` = `|51` Cộng `Số đầu năm`; `|51` Cộng col5 =
`307.749.988.310` = `|49` Cộng `Số đầu năm`.

2021 vẫn thiếu thật (0 hit `nha nuoc` trên 64 bảng consolidated + 71 bảng separate của 2021; đối
chứng 2018/2019/2020 mỗi năm đúng 1 hit). Nhưng chuỗi 386,95 → 307,75 → 249,46 giảm đơn điệu nên
việc thiếu 2021 không đổi thứ hạng của 2018 trong ba năm có dữ liệu.

**q866 mang hai lỗi độc lập, phải sửa cả hai:** đọc sai cột (header-shift) *và* trả số tiền cho
câu hỏi "năm nào". `project_year` một mình sẽ trả 2019 — vẫn sai.

### 5.1. Lớp lỗi header mới: note dạng "đầu kỳ / phát sinh / cuối kỳ"

Phát hiện phụ, đáng giá hơn chính q866. Ba bảng note thuế của SJG có **2 dòng header, dòng 2
lệch trái 1 cột**, nên `load_frame` giữ dòng 2 làm *một dòng dữ liệu* (label `Phải nộp`, toàn
NaN) thay vì header thật:

```
,Tại ngày 06/4/2018,Số phát sinh trong năm,Tại ngày 31/12/2018,,,,
Phải nộp,Phải thu,Phải nộp,Đã nộp,Giảm khác,Phải nộp,Phải thu,
Cộng,476.194.675.539,7.408.733.781,561.976.079.979,(650.141.858.055),(920.916.101),386.945.215.579,7.245.967.998
```

Header dòng 1 có 3 nhãn cho 7 cột số; dòng 2 mới là phân loại thật (`Phải nộp`/`Phải thu`/
`Đã nộp`/…) nhưng bị lệch trái 1. Hệ quả: cột **ghi nhãn** `Tại ngày 31/12/2018` thực chứa **số
phát sinh trong năm** (561,98 tỷ); số dư cuối kỳ thật ở cột 6 (386,95 tỷ). **Mọi query đọc theo
tên cột đều lấy sai khái niệm** — và sai một cách hợp lý-trông-đúng, nên verify không bắt được.

`repair_shifted_multilevel_header` (`dataframe.py:97`) **không bắt được** dạng này — nó chỉ khớp
pattern "số cuối…số đầu…Unnamed" của một layout khác.

### 5.2. Phạm vi: đã đo trên toàn corpus 146.246 bảng

Quét đủ, không lấy mẫu. Hai lần đo độc lập (agent 1 và tôi, tiêu chí hơi khác nhau) cho cùng
một bậc độ lớn:

| Tiêu chí | Agent 1 | Tôi |
|---|---:|---:|
| Dòng dữ liệu đầu toàn là chữ, ≥2 ô ngoài cột nhãn cũng có chữ | 24.186 (16,5%) | 18.302 (12,5%)¹ |
| + lọc theo từ khoá phân loại | 12.614 (8,6%) | 15.897 (10,9%)² |
| Số cột giữ dữ liệu > số nhãn ở header dòng 1 | 9.990 / 12.614 (79%) | 17.631 / 18.302³ |

¹ tôi thêm điều kiện ≥5 cột (ngưỡng của chính hàm repair) nên số nhỏ hơn.
² danh sách từ khoá của tôi rộng hơn. Chênh 8,6%–10,9% là do định nghĩa, không phải do đo sai.
³ định nghĩa "cột giữ dữ liệu" của tôi lỏng hơn (mọi cột có nội dung dưới dòng 0), nên con số
79% của agent 1 đáng tin hơn.

**Chốt: khoảng 9–11% corpus mang lỗi này, và ~4/5 trong số đó làm sai giá trị theo cột** — không
phải chỉ dư một dòng rác.

Phân bố (agent 1, tôi không kiểm lại phần này):
- Theo loại báo cáo: **rải đều** — consolidated 8,65%, separate 8,73%, aggregated 8,45%.
- Theo `table_pos`: đậm nhất ở **11–30 (16,9%)**, không phải ở pos cao như tôi đoán. pos 0–10 chỉ
  0,77% (báo cáo chính hiếm khi có header 2 dòng); 31–60 là 7,9%; 61+ là 4,8%.

### 5.3. `repair_shifted_multilevel_header` sai ở mọi lần nó chạy

Tôi chạy hàm thật trên 18.302 bảng ứng viên:

| | số bảng |
|---|---:|
| `repair_shifted_bank_header` chạy | 35 |
| `repair_shifted_multilevel_header` chạy | **81** |
| … trong đó output có **tên cột trùng nhau** | 72 (89%) |
| … trong đó còn sót cột nhóm `số đầu/cuối năm` **không có leaf** | 79 (98%) |
| không chạm tới | ~18.200 |

Nguyên nhân: guard hard-code `"số cuối" in group_name and "số đầu" in final_name` + mọi cột sau
đó phải là `Unnamed:` (`dataframe.py:116-121`), rồi gán **toàn bộ** subheader vào *một* nhóm
(`:129`). Với layout đối xứng đầu/cuối — dạng phổ biến nhất — cả hai khối leaf đều bị dán nhãn
"Số cuối năm", còn "Số đầu năm" thành cột trơ.

Ví dụ tôi xác minh trực tiếp, `DIG_2020_consolidated|30`:

```
cols: [Unnamed: 0, Lĩnh vực kinh doanh, Số cuối năm, Số đầu năm, Unnamed: 4, Unnamed: 5, Unnamed: 6]
row1: [Giá trị, %, Giá trị, %, '', '', '']
out : [Unnamed: 0, Lĩnh vực kinh doanh,
       'Số cuối năm | Giá trị', 'Số cuối năm | %',
       'Số cuối năm | Giá trị', 'Số cuối năm | %',   ← thực ra là SỐ ĐẦU NĂM
       'Số đầu năm']                                  ← cột trơ, không leaf
```

Tên cột trùng nhau nghĩa là `df["Số cuối năm | Giá trị"]` trả về **hai cột** — query nào index
theo tên đó đều hoặc lỗi hoặc tính sai âm thầm. Cùng dạng ở `DBC_2025_separate|32`,
`DBC_2025_consolidated|26`, `VGC_2024_separate|19`.

Về số lượng thì 81 bảng là nhỏ; điều đáng nói là hàm này **không phải "chưa đủ rộng" mà là sai
hướng**: nới guard cho nó chạy trên ~18k bảng còn lại sẽ nhân lỗi lên, không sửa được gì. Phải
viết lại phần chia leaf theo số nhóm không rỗng ở header dòng 1 trước, rồi mới nới guard.

### 5.4. Ví dụ ngoài SJG — nguyên văn CSV, đã tự đọc lại

Ca nguy hiểm nhất là **cột năm nay bị dán nhãn năm trước**. `KLB_2019_consolidated|67`:

```
L0: ['', 'Số cuối năm', 'Số đầu năm', '', '']
L1: ['Giá trị ghi số', 'Giá trị hợp lý', 'Giá trị ghi số', 'Giá trị hợp lý', '']
L2: ['Tiền mặt, vàng bạc, đá quý', '694.761', '694.761', '519.751', '519.751']
```

Cột tên `Số đầu năm` thực chứa **Giá trị hợp lý của cuối năm** (694.761), không phải số đầu năm
(519.751). Query hỏi "số đầu năm" nhận về số cuối năm — sai năm, và không có dấu hiệu nào để
verify bắt được. `PVT_2021_consolidated|16` giống hệt layout này.

`VJC_2022_consolidated|22` — cột tên `2021` thực chứa Dự phòng của 2022:

```
L0: ['', '2022', '2021', '', '']
L1: ['Giá gốc VND', 'Dự phòng VND', 'Giá gốc VND', 'Dự phòng VND', '']
L2: ['Công cụ, dụng cụ', '944.247.619.321', '-', '783.597.166.041', '-']
```

`DTK_2020_consolidated|29` nặng hơn: 2 nhãn thời gian cho 4 cột số, **và** dòng dữ liệu còn có
thêm cột STT nên lệch tiếp một bậc so với dòng subheader.

`CRE_2021_separate|26` là ca vô hại (thuộc 21%): L0 có đủ 4 nhãn thật + `Cộng`, L1 chỉ là dòng
đơn vị `VND,VND,VND,VND` — dư một dòng rác, không lệch giá trị.

**Lưu ý về độ tin cậy:** agent 1 gửi hai bản mô tả khác nhau cho cùng những bảng này (bản sau
thêm ô rỗng đầu dòng không có trong file). Các con số thống kê ở §5.2–5.3 tôi đã tự chạy lại;
các dòng CSV ở đây tôi đọc trực tiếp từ `data/tables/`.

---

## 6. Ô gold đã xác minh (tái tạo gold đến từng chữ số)

Dùng làm test fixture cho bất kỳ thay đổi nào ở tầng solver.

| Câu | Ô gold | Kết quả |
|---|---|---|
| q947 | `IJC_2020_consolidated\|8` = 1.478.799.000.000 | 1045,55 |
| q496 | `MWG_2022_consolidated\|6` iloc[11] 25.696.077.735.282 / (`\|7` iloc[9] 10.688.138.631.456 + iloc[13] 5.901.250.000.000) | 154,89 |
| q629 | (−384.655.311.583 − (−262.534.406.527)) / (−262.534.406.527) × 100 | 46,52 |
| q523 | `DCM_2023_separate\|12` iloc[0] 2.055.255.000 | 2,06 |
| q527 | `ACV_2023_separate\|8` row14 10.416.402.014.607 / `\|41` row21 18.811.821.013.840 × 100 | 55,37 |
| q528 | `ABB_2023_separate\|8` row18 2.012.636 / `\|5` row32 161.977.363 × 100 | 1,24 |
| q544 | `DCM_2021_consolidated\|5` row17 2.568.827.826.644 / `\|3` row2 3.186.610.542.693 | 0,81 |
| q1004 | `IJC_2023_separate\|56` | 5,27% |
| q836 | `TTF_2019_separate\|18` iloc[1] −280.535.700.000 | 280,54 |
| q641 | `DLG_2020_consolidated\|36` iloc[2] 64.112.708.746; `2018\|40` iloc[2] 66.271.208.557 | — |

---

## 7. Chi tiết từng câu

**Sai kiểu đáp án.** q527, q528: query **không có phép chia nào**, nên về nguyên tắc không thể
ra phần trăm. q842, q928: câu "năm nào" trả số tiền (xem §1).

**Bỏ quên năm** — bảng đúng nằm trong shortlist, query không chạm tới:
q1004 (note đúng ở rank 0–4 trên 58), q836 (rank 0, 1, 3, 6 trên 32), q544 (lấy 2022 thay vì
2021).

**Sai ô** — đúng năm, sai bảng con: q496 (§4), q629 (dùng note phải thu thay vì bảng cân đối),
q641, q649, q821.

**Sai số học:** q894 (sai dấu — `-5130022.2` vs gold `5130022.2`, đúng độ lớn), q523 (§4).

**Khác:**
- q947 trộn `separate` cho 2020 với `consolidated` cho 3 năm còn lại. `IJC_2020_separate|8` nằm
  ở vị trí **41/41 — tức được append vào cuối, chưa từng được retrieve**
  (`graph.py:255-293`: `table_ids` = thứ tự retrieval + bảng được query chạm nhưng chưa
  retrieve, nối vào cuối). Bảng đúng `IJC_2020_consolidated|8` ở rank 3.
- q835: `pandas_query` là hằng số `0.0` trong khi bảng đúng ở rank 1 và 4 trên 28; cột "Vay dài
  hạn" của FOX bị lệch cột.
- q611: `EIB_2019_separate|86` gắn nhãn 2019 nhưng header đọc "Tại ngày 31 tháng 12 năm 2018"
  và row18 trùng đúng bảng 2018 → **preprocessing gắn sai năm**; dữ liệu 2019 chưa từng được
  số hoá.

**Thiếu năm thật** (đã quét cạn shortlist): q585 (0/44 — ứng viên rank 3/4 là báo cáo biến động
vốn, cột "Quỹ dự phòng tài chính", quỹ khác), q588 (0/55 bảng có dòng "bên liên quan" nào),
q596 (0/7 cho 2017). q866 **không** thuộc nhóm này: 2021 thiếu thật nhưng không ảnh hưởng đáp
án (§5).

**Lỗi preprocessing/header** (nguyên nhân góp mặt):
- q866: header 2 dòng lệch trái ở note thuế SJG — cột ghi nhãn "cuối năm" chứa số phát sinh
  (§5.1). Đây là câu duy nhất tái tạo được gold *chỉ bằng* cách sửa cột.
- q641: cột số dư thật tên `Unnamed: 8`; cột đọc được `Số phải nộp trong kỳ` là số phát sinh —
  **cùng một lớp lỗi với q866**, khác layout.
- q835: cột "Vay dài hạn" của FOX lệch cột.
- q596: `VNM_2024_separate|24` có `Unnamed: 6` nhân bản `31/12/2024` → hiệu số luôn bằng 0.
- q496: `MWG_2020|9` merge sai ở báo cáo lưu chuyển tiền tệ, khấu hao ra 5.409,7 tỷ — cao hơn
  con số thật 3.472,9 tỷ của 2022. Đây là **bẫy cho mọi solver so sánh năm** sau này.
- q611: gắn sai năm (xem trên).

---

## 8. Tương quan đáng tin: coverage năm

| Query có chạm đủ mọi năm câu hỏi yêu cầu | Tỉ lệ đúng |
|---|---|
| có | 50% (n=20) |
| không | 8% (1/12) |

Đây là tín hiệu độc lập với thứ tự runtime, nên dùng được. Nhưng lưu ý: **nới budget bảng cho
multi-year đã bị đo và loại** — dữ liệu đã ở trong shortlist rồi, thêm bảng không giúp.

---

## 9. Giới hạn của chẩn đoán này

- **Không truy được provenance của v8.** Không file run nào trong `artifacts/runs/` tái tạo
  `pandas_query` của v8; `output/submission_v8_round2/` chỉ có `submission.json` + `data/`. Nên
  các kết luận được chia làm hai loại: *chắc* (không phụ thuộc thứ tự runtime) và *suy luận*
  (phụ thuộc thứ tự bảng lúc chạy). Các số rank trong §7 thuộc loại thứ hai.
- **`find_rows` không liên quan.** Tôi từng suy ra các bảng ngoài head đến từ `find_rows`; sai —
  `codegen_tool_turns = 0` mặc định nên nó chưa từng chạy. Đã rút lại.
- n = 21 câu. SE của clean eval ≈ 4,5pp; đừng đọc chênh lệch 1–2 câu như tín hiệu.

---

## 10. Đề xuất thứ tự việc

1. **Comparator riêng cho nhãn phân loại** trong `score_clean_eval.py` — không sửa được câu nào
   nhưng không có nó thì mọi thay đổi ở câu "năm nào"/"mã nào" đều không đo được (§2).
2. **`project_year`: bỏ neo `$`/cho phép bọc `round`** — 17 câu, thay đổi nhỏ nhất, đã đo là
   chạy 16/17. Nhưng chỉ đảm bảo *ra một năm*: q866 chứng minh nó có thể ra năm sai nếu cột đọc
   sai. **Đo trước bao nhiêu trong 16 câu đó trả đúng năm** — nếu tỉ lệ thấp thì việc 3 quan
   trọng hơn.
3. **Lớp header 2 dòng lệch trái** (§5.1–5.3) — đã đo: **~9–11% corpus**, 79% trong số đó sai
   giá trị theo cột, rải đều mọi loại báo cáo, đậm ở `table_pos` 11–30. Đây là lỗi lớn nhất tìm
   được trong cả đợt, và nó nằm *dưới* mọi solver. Thứ tự trong việc này:
   a. Viết lại phần chia leaf của `repair_shifted_multilevel_header` — hiện nó chạy 81 lần và
      **sai cả 81** (72 lần tạo tên cột trùng). Nới guard trước khi sửa logic sẽ nhân lỗi lên.
   b. Chỉ sau đó mới nới guard ra ~18k bảng còn lại.
4. Các lỗi preprocessing lẻ: cột `Unnamed: *` nhân bản (q596), lệch cột (q835), năm gắn sai của
   `EIB_2019_separate|86` (q611).
5. **Bỏ quên năm** (3 câu): dữ liệu đã trong shortlist, đây là bài toán bắt codegen chạm đủ năm.
6. Sai ô (5 câu) — cần hiểu vì sao chọn bảng con sai; chưa có cách sửa rẻ.
7. Thiếu năm thật (3 câu) — corpus không có, **không cứu được**. Bỏ ra khỏi mẫu số khi đặt mục
   tiêu.

**Cảnh báo về thứ tự:** sửa lớp header ở việc 3 làm **đổi giá trị của ~9–11% bảng**, nên mọi số
đo trước đó — kể cả 16/17 của `project_year` — phải đo lại sau đó. Nếu định làm việc 3, làm nó
trước việc 2 để không phải đo hai lần.

## 11. Đã làm (2026-08-22)

Ba việc đầu, theo đúng thứ tự đã cảnh báo ở §10: comparator, rồi header, rồi `project_year`.

### 11.1. Comparator (việc 1)

`scripts/score_clean_eval.py` và `scripts/score_gold75.py` giờ đòi khớp tuyệt đối khi nhãn là
một số nguyên trong 1990–2100. `tests/test_score_comparators.py` giữ luật đó, kèm một test ghi
lại đánh đổi đã biết: một *số tiền* rơi trúng khoảng năm cũng sẽ bị đòi khớp tuyệt đối. Cả hai
tập hiện không có nhãn nào như vậy.

Chấm lại v8: **46/119 = 0.387, không đổi**. Đúng như dự đoán, vì v8 trả số tiền cho cả ba câu
"năm nào" nên comparator cũ đã loại sẵn. Giá trị của việc này là chặn trước, không phải sửa điểm.

### 11.2. `repair_shifted_multilevel_header` (việc 2)

Luật mới: dòng 0 là header tầng hai nếu nó toàn chữ, dồn về trái, và các cột phía sau rỗng; biên
nhóm suy từ **số lần leaf đầu tiên lặp lại**, và số lần lặp phải bằng số nhãn nhóm. Mọi cột có
tên phải nhận được ít nhất một leaf — cột có tên mà không có leaf chính là dấu vết của bug cũ.

Đo trên cả 146.246 bảng (`scripts/gate_multilevel_header.py`, không lấy mẫu):

| | bản cũ | bản mới |
|---|---:|---:|
| bắt | 93 | 10.372 |
| tên cột trùng nhau | 72 (77%) | **0** |
| sửa sạch | 21 | 10.277 |
| sửa nhưng còn cột `Unnamed:` rỗng ở đuôi | 0 | 95 |

Bản mới từ chối 90 trong 93 bảng bản cũ từng sửa, kể cả 21 bảng bản cũ sửa "sạch": đọc lại CSV
thô cho thấy chúng lệch không đều theo dòng (`DIG|30` có `Tổng cộng` ở cột 6, `FTS|24` có dữ liệu
ở các cột 2/4/5/7/8), không có cách chia nào đúng. Từ chối để nguyên nhãn kỳ gần đúng còn hơn.

Kiểm bằng tay: bốn bảng đã audit ở §5.4 ra đúng (`SJG|45`, `|49`, `|51`, `KLB|67`), năm bảng còn
lại bị từ chối và **từ chối là đúng** — `VJC|22`, `PVT|16`, `CRE|26` có dòng 0 là nhãn mục
(`Các bên liên quan`, `a) Ngắn hạn`, `Tài sản`) chứ không phải header. Thêm 12 bảng lấy ngẫu
nhiên trong số bắt được, đọc từng cái: 12/12 đúng.

Số dư cuối kỳ của q866 sau khi sửa: **386.945.215.579 / 307.749.988.310 / 249.462.096.512**,
khớp từng chữ số với §6, và 2018 thắng đúng như gold.

Test: `tests/test_dataframe_repair.py`, 6 case dựng từ CSV thật (trước đó hàm này không có test
nào).

### 11.3. `project_year` (việc 3)

Nguyên nhân đã xác nhận trên artifact thật: **978/1.012 query của v8 bắt đầu bằng `round(`**, còn
`_SELECT_CALL` neo hai đầu, nên hàm chưa từng chạy lần nào. q866 nộp đúng
`round(max(df3…, df4…, df5…), 2)`. `_unwrap_round` bóc lớp `round(expr, n)` khi đối số thứ hai là
số nguyên; `round(a, b)` với b là một ô thì không bóc.

Đo lại trên v8: 53 câu "năm nào", khớp `max`/`min` **0 → 17** (813, 822, 829, 832, 841, 866, 874,
879, 889, 907, 921, 936, 946, 948, 960, 978, 1008). 36 câu còn lại query không phải `max`/`min` —
q842 nộp `round(1500889847164.0, 2)`, q928 nộp một tổng `abs`. Khớp cấu trúc chưa phải là chạy:
hàm vẫn đòi mỗi số hạng đọc đúng một frame và năm thắng phải là năm câu hỏi có nhắc.

Chạy thử cả chuỗi trên frame đã sửa header, chọn tay ô `Cộng`: `project_year` trả
`("(df3.iloc[12]['Tại ngày 31/12/2018 | Phải nộp']) * 0 + 2018", '2018')`. Ba việc ăn khớp nhau.
Cái này **không** chứng minh codegen sẽ tự chọn đúng ô đó.

### 11.4. Chưa đo được

Điểm sau ba thay đổi. Artifact v8 dựng bằng tên cột **cũ** nên `round(max(df3.iloc[13]["Tại ngày
31/12/2018"]…` giờ không chạy lại được; đo thật cần chạy lại pipeline, tức là gọi LLM. Sửa header
cũng dời `iloc` đi một dòng ở 10.372 bảng, nên mọi query đã lưu đều lệch dòng.

Chỉ mục `data/indexes/tables_doc_text.parquet` và `tables_dense.npy` dựng từ tên cột cũ. Retrieval
docs hiện 0.9488 nên chưa cấp bách, nhưng hai bên đã lệch nhau.
