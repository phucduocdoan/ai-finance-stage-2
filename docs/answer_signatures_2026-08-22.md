# 73 câu sai, phân theo chữ ký số học: chỉ 7 câu sửa được bằng luật

Ba phiên trước đều đi từ phía retrieval: bảng gold ở đâu, judge chọn gì, khe evidence đủ
chưa. `docs/shortlist_gap_2026-08-22.md` đóng hướng đó. Phiên này đi từ phía ngược lại: so
**con số** đã nộp với **con số** gold, rồi hỏi hai số lệch nhau kiểu gì.

`scripts/gate_sign_rule.py` in bảng này (không gọi LLM, đọc submission và nhãn):

```
73 câu sai, theo chữ ký số học:
  ô khác hẳn                58
  một bên bằng 0             8
  chỉ sai dấu                3  [774, 777, 894]
  sai lũy thừa 10 (x1e-3)    1  [139]
  sai lũy thừa 10 (x1e1)     1  [267]
  sai lũy thừa 10 (x1e-6)    1  [284]
  sai lũy thừa 10 (x1e6)     1  [748]
```

Đây là con số đáng nhớ nhất của phiên: **58 trên 73 câu sai là đọc hẳn một ô khác**, không
phải lệch đơn vị, không phải lệch dấu, không phải cộng trừ nhầm. Hy vọng "có một lớp lỗi hậu
xử lý rẻ tiền" chết ở đây: cả lớp dấu và lớp lũy thừa 10 cộng lại đúng 7 câu.

Nhưng 7 câu đó là 7 câu **xác định**, sửa bằng luật đọc được, không cần chạy lại LLM. Lớp
dấu đã lấy hết, +3, xem §2 và §3.

## 1. Truy vấn có index vào cột thật không: manh mối chết

`config.py:218` ghi kiểu lỗi nó thấy khi nâng trần bảng: "a column name taken from df2 used
to index df5". Nếu đúng vậy thì chặn được bằng một phép kiểm tra thuần cơ học.
`scripts/gate_query_grounding.py` parse `pandas_query` bằng `ast`, đối chiếu mọi tên cột và
chỉ số dòng với frame nó index, trên cả 1012 câu:

```
  ok                          857   84.7%
  cột lạ: mượn từ df khác       8    0.8%
  cột lạ: bịa hẳn              41    4.1%
  dòng quá tầm                  3    0.3%
  biến lạ                       1    0.1%
  không có truy vấn           102   10.1%
```

Cả 49 câu "cột lạ" đều thật: chạy lại truy vấn với `load_frame` thì cả 49 raise. Nhưng
hướng này vẫn chết, vì ba lý do đo được:

- Chỉ **8** câu là kiểu `config.py:218` mô tả (mượn cột từ df khác). 41 câu còn lại là tên
  bị cắt ngắn từ header hai tầng đã làm phẳng (`"31/12/2020"` cho
  `"31/12/2020 | Triệu VND"`), tức lỗi đọc header, không phải lỗi lẫn frame.
- Chỉ **30/49** câu có tên cột hỏng phân giải về đúng một cột duy nhất. Sửa tự động 19 câu
  còn lại là đoán.
- Trên 119 câu chấm được, cả lớp này chỉ có **8 câu, 5 câu sai**, và giao với 23 câu "đã nạp
  đủ bằng chứng mà vẫn sai" đúng hai câu: [97, 748].

Đóng hướng. Ghi lại vì `config.py:218` sẽ còn dụ người đọc sau đi vào đây.

## 2. Luật dấu: hiệu giữa hai pháp nhân là độ lớn

Ba câu sai dấu (774, 777, 894) là lớp duy nhất trong bảng đầu file có một nguyên nhân chung.

Vì sao luật cũ bỏ sót. `SIGNED_METRIC` chứa `chenh lech`, nên `cell_locator.value_transform`
phủ quyết mọi câu hỏi hiệu số; `execute.as_magnitude` phủ quyết y hệt bằng `DIFF_CUE_LOOSE`,
và docstring của nó viết "in those the sign *is* the answer". Câu đó **đúng** với hiệu theo
thời gian và **sai** với hiệu giữa hai pháp nhân:

- q623 "chênh lệch ... cuối năm 2023 và cuối năm 2022 của PC1": 2023 trừ 2022, đảo dấu là
  đảo nghĩa. Nhãn âm, ta trả âm, đúng.
- q774 "chênh lệch ... của công ty mẹ VIB và công ty mẹ SHB": thứ tự VIB/SHB do người viết
  câu chọn, không phải do phép tính. Nhãn dương.
- q894 "trung bình cộng thuế TNDN đã nộp": khoản chi ghi âm trong lưu chuyển tiền tệ, mà
  `MAGNITUDE_METRIC` (`chi phí|dự phòng|hao mòn|khấu hao|lãi vay`) không khớp chữ nào.

Sáu biến thể luật, đo bằng cách lấy `abs()` đáp án ở những câu luật bắn rồi chấm lại (đúng
phép vì mọi nhân đơn vị trên đường `apply_units` đều dương):

| luật | điểm | được | mất | đổi dấu / 1012 |
|---|---:|---|---|---:|
| hiệu, câu chỉ nhắc một mốc | 48 | 774, 777 | | 32 |
| hiệu, scope có ≥2 mã | 48 | 774, 777 | | 38 |
| `đã nộp/trả/chi` | 47 | 894 | | 1 |
| hiệu một mốc + đã nộp | 49 | 774, 777, 894 | | 33 |
| hiệu ≥2 mã + đã nộp | 49 | 774, 777, 894 | | 39 |
| **hiệu ≥2 mã, một mốc, không sàng lọc, + đã nộp** | **49** | 774, 777, 894 | | **28** |

Nguyên bản 46/119. Mọi biến thể đạt 49/119 đều **mất 0 câu**, nên tập 119 câu không tách
được chúng. Chọn biến thể cuối vì hai lý do không nằm trong con số tổng:

1. **Nó nói đúng điều nó làm.** "Hiệu giữa hai pháp nhân trong cùng một mốc" là mệnh đề
   giải thích được: hai bên chỉ khác nhau ở pháp nhân, nên thứ tự là tuỳ ý. Biến thể "câu
   chỉ nhắc một mốc" chỉ là proxy văn bản, và nó bắn sai ngay trên một test đang có:
   `tests/test_solve_units.py:253` khẳng định "Hiệu số giữa chi phí bán hàng và chi phí quản
   lý" phải giữ dấu, mà đó là hiệu giữa hai **chỉ tiêu**, không phải hai pháp nhân.
2. **Nó đổi dấu ít nhất: 28 câu thay vì 39.** Trên 893 câu không có nhãn, mỗi lần đổi dấu
   thêm là một lần rủi ro không đo được. Chặn `SELECTION_MARKER` bỏ đúng ba câu sàng lọc
   (417, 418, 445), nơi "cao hơn" làm `DIFF_CUE_LOOSE` bắn nhưng đáp án là hệ số ROA của một
   công ty, và ROA âm là hợp lệ.

Đọc `artifacts/runs/gate_sign_rule_flips.out`: cả 28 câu bị đổi dấu đều là dạng "chênh lệch
giữa A và B", trừ q894.

### Kiểm lại bằng code thật, không gọi LLM

Bảng trên đo bằng cách lấy `abs()` con số đã nộp. Đúng phép về số học nhưng nó không chạy
`as_magnitude`, nên không loại trừ khả năng luật bắn ở chỗ khác chỗ tôi nghĩ.
`scripts/gate_sign_replay.py` chạy đuôi tất định thật: nạp lại bảng, gọi `apply_units` rồi
`run_query`, một lượt với luật mới và một lượt vô hiệu hoá `between_two_companies` +
`PAID_OUT`. Hai kết quả trùng nhau:

```
chạy lại được 838/1012 câu có solution, không gọi LLM
submission gốc        46/119
chạy lại, luật cũ     41/119   (lệch submission 0 câu)
chạy lại, luật mới    44/119   được [774, 777, 894]
```

**Lệch 0 câu** là con số quan trọng ở đây: cả 838 câu chạy lại được đều tái tạo *đúng* con
số đã nộp khi luật bị vô hiệu hoá, nên replay trung thực với pipeline, không phải một mô
phỏng gần đúng. 41 chứ không phải 46 chỉ vì 174 câu không chạy lại được (42 câu truy vấn
rỗng, phần còn lại solver dòng thô đánh số df khác). Delta +3 / −0 là *cùng ba câu* mà gate
`abs()` chỉ ra. Hai câu bị đổi dấu mà vẫn sai (735, 769) sai vì lý do khác: nhãn 14.11 so
với 15.22, và 31.29 so với 2191.77.

Hai chi tiết phải đúng mới dựng lại được, ghi lại vì lần sau còn dùng:

- `df1..dfN` lấy từ `diag["evidence_tables"]`, không phải `record["table_ids"]`. `table_ids`
  là danh sách retrieval *trước* khi `codegen_budget` xoay vòng và cắt theo `max_tables`,
  dùng nó thì 106/400 truy vấn KeyError chỉ vì số hiệu df lệch.
- `names` phải truyền vào `apply_units`. Đơn vị tra trong page text của bảng đi qua nó, nên
  thiếu nó thì q744 và q787 rơi về "mặc định vnd" rồi bị chia thêm 1e6. Đây chính là hai câu
  duy nhất còn lệch trước khi thêm `names`.

`unit_hint` thì không dựng lại được: nó do understand sinh ra và bản ghi run không lưu.
Trên 838 câu này nó không đổi kết quả câu nào, nhưng đó là lý do phải có phép kiểm "luật cũ
tái tạo đúng số đã nộp" thay vì tin replay vô điều kiện.

## 3. submission v9: vá 23 câu, không chạy lại LLM

Luật dấu nằm hoàn toàn trong `apply_units`, không đổi prompt, không đổi retrieval, không
đổi bảng nào được chọn. Nên chạy lại full 1012 câu là sai cách đo: nó xáo 58 câu "ô khác
hẳn" theo nhiễu LLM, mà biên độ nhiễu đó lớn hơn 3 câu cần đo.
`scripts/patch_sign_submission.py` vá tại chỗ, mỗi câu chỉ vá khi lượt "luật cũ" tái tạo
đúng con số đã nộp:

```
vá 23 câu, giữ nguyên 989 câu
  luật không đổi kết quả   815
  không chạy lại được      174
  replay lệch, bỏ qua      0
```

`output/submission_v9_sign` chấm **49/119 = 0.412** (v8_round2: 46/119 = 0.387). Đã kiểm:
`validate_format` sạch, đúng 23 item khác v8 và chỉ khác ở `answer` + `pandas_query`, cả 23
truy vấn đã vá chạy lại trên CSV staged đều khớp con số ghi trong `answer`, và cấu trúc zip
trùng v8 từng entry (10.922 file).

Vá cả `pandas_query` chứ không chỉ `answer` vì EXECUTION_ACCURACY chạy lại chuỗi đã nộp:
vá một bên thì hai chỉ số chỏi nhau.

### Leaderboard đã trả lời: +8 câu

```
ANSWER_ACCURACY    0.3261 -> 0.334    (+0.0079, 330 -> 338/1012)
EXECUTION_ACCURACY 0.3241 -> 0.332    (+0.0079, 328 -> 336/1012)
DOCS/TABLES        không đổi
```

23 câu đổi dấu, ròng +8. Trên 119 câu sạch chỉ 5 câu bị đổi dấu (ròng +3), nên 18 câu
không nhãn góp thêm ròng +5: luật tổng quát hoá ra ngoài tập nhãn. Nhưng +3/119 = +2.5pp
mà leaderboard chỉ trả +0.79pp, vì luật được *chọn* trên chính 119 câu đó nên delta ở đó
là cận trên. Chi tiết ở `docs/leaderboard_and_strategy_2026-08-21.md` §11.

Khe ANSWER − EXECUTION vẫn đúng 2 câu như v8, tức vá truy vấn cùng đáp án chạy đúng: nếu
chỉ vá con số thì khe phải rộng thêm 23 câu.

### Cài ở đâu

Một chỗ duy nhất: `execute.as_magnitude`. `graph.py` chạy **mọi** solver qua `aexecute`, nên
`abs` ở đó phủ cả codegen, raw_table_linker, raw_selection_linker, cell_locator và nhánh
revise. Quan trọng hơn: `apply_units` bọc `abs()` quanh **toàn bộ** truy vấn, còn
`value_transform` chỉ bọc từng số hạng. Với q774 thì `abs(a) - abs(b)` vẫn âm, chỉ
`abs(a - b)` mới đúng, nên chỗ cài phải là `apply_units`, không phải `value_transform`.

`state["tickers"]` được truyền thêm vào `aexecute` ở 5 điểm gọi trong `graph.py`. Điểm gọi
thứ sáu là nhánh câu con của `decompose`, chỗ đó mỗi câu con chỉ có một công ty một năm nên
nhánh mã không bao giờ bắn; `đã nộp` vẫn bắn được vì nó chỉ đọc văn bản.

Một cái bẫy đã dính rồi và đáng ghi: predicate phải đọc `intent_norm(question)`, không phải
`norm(question)`. `SELECTION_MARKER` có nhánh `cong ty co\b`, nên "Công ty Cổ phần" tự khớp
nếu không gỡ dạng pháp nhân trước.

## 4. Còn lại gì

Bảng đầu file để lại hai lớp:

- **58 câu "ô khác hẳn".** Không có luật hậu xử lý nào chạm được. Đây là bài toán chọn ô, và
  `docs/cell_ranking_2026-08-22.md` đang đo đúng nó.
- **4 câu sai lũy thừa 10** (139, 267, 284, 748). q139 và q284 đúng là ca này: bảng ghi
  nghìn/triệu đồng, code mặc định vnd. q748 là lỗ khác, nó cần `target_unit` kiểu "triệu cổ
  phiếu" mà `Unit` không có.

## 5. Lớp "mặc định vnd": đã đo, manh mối chết

`scripts/gate_unit_default.py` chạy `apply_units` thật trên bản ghi run (không LLM, dựng lại
`df1..dfN` như `gate_sign_replay.py`), rồi ở mỗi câu sai thử lần lượt từng đơn vị trong
`MONEY_SCALE` xem đơn vị nào cho ra nhãn:

```
lớp 'mặc định vnd' bắn ở 396/838 câu (47%)
trong 119 câu sạch: 57 câu, 20 đúng, 37 sai
  thật = None                 35
  sai vì mặc định vnd          2      (q139 thousand_vnd, q284 million_vnd)
  cùng trang đọc đúng          1
```

Chỉ **2 trong 37 câu sai** là do mặc định đơn vị. 35 câu còn lại không có đơn vị nguồn nào
biến số thô thành nhãn, tức đọc sai ô chứ không sai đơn vị. Con số "15 câu sai" ở §4 đếm
thành viên của lớp, không phải nguyên nhân, và đó là cách đọc sai. Tín hiệu mượn đơn vị từ
bảng anh em cùng báo cáo (hoặc cùng trang) đọc đúng q284, đọc sai q139, tức thắng 1 trong 2.
Không đáng làm.

## 6. Lớp thật ra to: câu sàng lọc nhiều công ty

Trong lúc đọc dump của §5, 232 trong 838 câu replay có `target_unit` là percent/ratio nhưng
49 câu trả về `|giá trị| > 1000`, và 42 câu trả trên 1e6. Một câu hỏi tỉ lệ trả về nghìn tỉ
thì sai chắc chắn, không cần nhãn. Tách theo số công ty trong câu hỏi:

| lớp                         | số câu | có nhãn | trả > 1e6 |
|-----------------------------|--------|---------|-----------|
| đích tỉ lệ, một/hai công ty | 130    | 5/15    | 12        |
| đích tỉ lệ, sàng lọc        | 102    | 1/16    | 30        |

Câu tỉ lệ một công ty đúng 33%, bằng tỉ lệ chung. Nên lớp tỉ lệ không phải bug riêng, nó là
lớp sàng lọc trá hình. Đo trực tiếp lớp sàng lọc (từ 3 mã trở lên, hoặc có cụm "trong nhóm",
"xét các", "xét phân nhóm"), bằng `scripts/gate_screening_class.py`:

```
lớp sàng lọc trên 1012 câu: 210 câu (21%)
  trong lớp   4/29     (14%)
  ngoài lớp   45/90    (50%)
```

Nhận diện bằng văn bản nên đếm thiếu: câu gọi tên đầy đủ ("Tập đoàn Sao Mai") không có mã
nào, chỉ vào lớp nhờ cụm từ. 210 là chặn dưới.

Đây là khối headroom lớn nhất còn lại. Nguyên nhân đọc được ngay trong `pandas_query`: 31
trong 42 câu trả > 1e6 không có phép chia nào, truy vấn chỉ là một ô đơn `df1.iloc[k][col]`.
Router cho thấy mọi solver tất định đều từ chối và codegen chạy vì `fallback`. Codegen thấy
bảng của nhiều công ty rồi trả về một ô của một công ty, việc mà không luật hậu xử lý nào
sửa được.

### Mất công ty ở khâu nào

`scripts/gate_screening_evidence.py` tách ba khâu từ bản ghi run, không gọi LLM: scope là mã
đọc từ `table_ids`, evidence là mã trong `diag["evidence_tables"]` sau khi `codegen_budget`
cắt, used là mã của những `dfK` thật sự xuất hiện trong truy vấn.

```
budget cắt mất công ty          124 câu   có nhãn 1/16
understand thu scope < 3 mã      32 câu   có nhãn 3/5
đủ cả ba khâu                    24 câu   có nhãn 0/2
codegen không chạy               20 câu   có nhãn 0/4
sinh code chỉ dùng một phần      10 câu   có nhãn 0/2
```

Đọc bảng này mà kết luận "lỗi ở budget" là sai, và tôi đã sai đúng một lượt trước khi đọc
lại `config.py:236-259`. Ở đó biến nhân quả đã được đổi: nới trần lên 12 bảng đưa coverage
từ 107/310 lên 310/310 mà điểm đứng nguyên 4/38. Budget cắt bảng là có thật, nhưng nó không
phải cái đang giữ điểm ở mức này.

Một cái bẫy trong chính gate đó, đã sửa: `evidence_tables` rỗng không phải bảng bị cắt hết.
102 trong 1012 câu rỗng và tất cả đều do `selection_facts` hay `formula_facts` giải, tức
codegen không chạy nên không ghi gì.

### Solver nào nhận lớp này, và đúng bao nhiêu

Trên run v7, chấm theo tập eval sạch:

| solver                 | số câu | có nhãn |
|------------------------|--------|---------|
| `cell_locator`         | 131    | 13/17   |
| `raw_table_linker`     | 229    | 11/30   |
| `codegen`              | 520    | 23/63   |
| `formula_facts`        | 54     | 1/1     |
| `selection_facts`      | 48     | 1/5     |
| `raw_selection_linker` | 30     | 0/3     |

`selection_facts` là solver duy nhất được viết cho việc chọn lọc, và trên lớp sàng lọc nó
nhận 4 câu, đúng 0. Tôi đọc tay cả bốn plan nó dựng, cả bốn sai cùng một kiểu và không plan
nào có `filters`:

- q410 đổi chỗ selector (`roe`) với chỉ số đáp án (`de_ratio`) rồi bỏ mất mốc trung vị. Số
  nộp 95.81 đúng dáng một tỉ lệ D/E, tức plan đó là plan thật chứ không phải suy đoán.
- q467 mất "3 doanh nghiệp" và mất luôn chỉ số đáp án là tỉ trọng tiền.
- q492 dùng `cfo` thay cho tỉ lệ CFO trên lợi nhuận thuần, và bỏ điều kiện dấu.
- q842 trả về giá trị lợi nhuận thay vì trả về năm. Số nộp 1.500.889.847.164.

Chỗ hỏng là bộ dựng plan, không phải bộ thực thi và không phải dữ liệu.

### Vì sao nó từ chối 123 câu còn lại

`diag["capability_router"]` gộp 123 câu vào một lý do "no max/min selection marker", con số
đó vô dụng vì `deterministic_selection_plan` trả về đúng chuỗi ấy trong bốn tình huống khác
nhau. `scripts/gate_selection_reasons.py` gọi thẳng hàm đó rồi bóc ra:

```
  38  1/2     không có chỉ số nào trong catalog
  15  2/4     dưới 2 mã (đọc được 1)
  13  0/5     len(years) = 4
  11  0/1     nhánh aggregate từ chối: no group filter to aggregate over
  10  -       len(years) = 2
   7  0/1     len(years) = 3
   2  -       len(years) = 5
```

Nhóm 38 câu to nhất lại là hai lớp khác nhau: 14 câu là câu ngân hàng, ticker không có trong
`long_format.parquet`, nên mở rộng catalog bao nhiêu cũng vô ích, chúng phải đi đường
`_read_bank_label_rows`. 24 câu còn lại là thiếu alias chỉ số thật.

Số năm là xấp xỉ, vét từ văn bản câu hỏi chứ understand lấy năm từ LLM, nên các nhóm
`len(years) != 1` phải đọc như chặn trên.

### Kho dữ liệu không phải chỗ nghẽn

`long_format.parquet` (290.230 dòng, 75 mã, 2015-2025) phủ đủ mọi ticker của 183 trong 210
câu sàng lọc. 26 câu không có gì đều là câu ngân hàng (BID, MSB, STB, MBB, EIB, ABB, HDB,
ACB, SHB, NAB, VIB, VPB). Trên 29 câu có nhãn: 26 câu phủ đủ, đúng 2/26.

### Bốn cần cẩu có sẵn, cả bốn đã đo và đều chết

| cần cẩu                              | đo được | ghi ở đâu |
|--------------------------------------|---------|-----------|
| nới `codegen_max_tables_multi_company` | coverage 310/310, điểm 4/38 | `config.py:236-259` |
| `decompose` fan-out theo công ty     | 3/34 (baseline 2-3) | `config.py:388` |
| `selection_facts`                    | 0/4 | §6 trên |
| `structured_facts` + tắt `selection_facts` | 4/29, ngưỡng chốt trước là 8/29 | `artifacts/runs/gate_screening_structured.out` |

Lần cuối chạy `structured_facts`: nó nhận 7 trong 29 câu và đúng 1, đổi được q492 và mất
q571, tổng lớp không nhúc nhích. 19 câu rơi xuống codegen đúng 0/19.

Bốn thứ này hỏng ở cùng một chỗ, và chỗ đó viết thẳng trong schema:
`PandasSolution.pandas_query` là "Single pandas expression returning one number"
(`solution.py:48`). Một biểu thức đơn không có chỗ nào đặt điều kiện lọc, nên mô hình cộng
hoặc nhân thẳng qua mọi công ty. `config.py` đã ghi sẵn kết luận này bằng số: trong 18 câu
nhìn thấy đủ mọi công ty mà vẫn sai, 17 câu sinh ra truy vấn cộng hoặc nhân thẳng qua tất cả.

Nên lever còn lại chưa có bằng chứng phản là cho schema mang phần theo từng công ty, một
điều kiện, và một phép chọn cuối, rồi gộp lại thành một biểu thức để vẫn chạy lại được.
