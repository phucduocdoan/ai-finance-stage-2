# Tổng hợp 4 phương án — trần lợi ích đo được trên gold73

Bốn note trong thư mục này do 4 sub-agent điều tra độc lập (read-only, không sửa code,
không chạy gate tốn tiền). Sàn nhiễu của `score_gold75.py` trên bộ 73 câu = **2 câu**.
Baseline: `artifacts/runs/gold73_qwen35_planner.jsonl` = 52/73, 21 câu sai.

| # | Phương án | Trần lợi ích đo được | So với sàn nhiễu 2 | Ghi chú |
|---|---|---|---|---|
| 1 | adaptive k (nhánh A) | **0** | dưới | TABLES_F2MACRO=0.0 do lệch hệ đánh số bảng, không phải bug k. DOCS đã 0.9488. |
| 1 | quy ước số học BTC (nhánh B) | **1** (q526) | dưới | "chênh lệch không hướng → trị tuyệt đối" chưa có code nào cài. |
| 2 | mở rộng `cell_locator` | **1** (q263) | dưới | 35/65 câu không fire là câu nhiều-ô thật (thiết kế đúng); 21/24 câu bị gate 2 chặn đã đúng nhờ solver dự phòng. |
| 3 | tuple planner trước retrieval | **4** (488, 502, 542, 920) | ngay sàn | Bản đầy đủ theo SPEC.md không cần thiết. Xem hiệu chỉnh dưới. |
| 4 | port `grid.py` vào đường CSV | **0–1** (q555) | dưới | Chỉ số hợp lý là ô đọc đúng (91→4/198), không phải số câu. |

**Kết luận chung: không phương án nào một mình vượt sàn nhiễu trên bộ 73 câu.** Đây là phát
hiện về *công cụ đo*, không chỉ về các phương án: gold73 đã hết khả năng phân biệt ở biên độ
1-4 câu. Muốn quyết định bằng số thì phải (a) làm gộp cả nhóm rồi đo một lần, hoặc (b) chuyển
sang chỉ số nhạy hơn — bộ 60 câu cell-truth, hoặc tỉ lệ ô đọc đúng trên 198 bảng evidence.

## Hiệu chỉnh phương án 3 (team lead đo lại, ngoài note của P3)

P3 nói trần là 3 câu và nút nghẽn là "cỡ cắt quá nhỏ". Đo lại trực tiếp trên artifact:

- Trong 35 câu multi-tuple của bộ 73, **9 câu mất ≥1 tuple cần thiết ở bước cắt**, và cả 9
  đều có **đủ 100% tuple trong `table_ids` trước khi cắt** — mất tuple là lỗi cắt, không phải
  lỗi retrieval. 5 trong 9 câu đó do solver hẹp trả lời (`|evidence_tables|=0`, không dùng
  đường cắt này) nên không tính. Còn lại **4 câu codegen: 488, 502, 542, 920** — nhiều hơn 3
  câu P3 báo.
- **q920 đang bị gán nhãn sai** trong `score_gold75.py --blame`: nó nằm ở nhóm
  "select_evidence/retrieve sai bảng", nhưng retrieval đã có đủ 3/3 tuple; chính bước cắt bỏ
  mất 1 tuple. Đây là lỗi cắt, không phải lỗi retrieval.
- **Điểm P3 bỏ sót, và là điểm quan trọng nhất:** ở q542 và q920, bước cắt **tiêu slot trùng
  tuple trong khi vẫn thiếu tuple khác**. q542: 5 slot nhưng chỉ chứa 3 tuple phân biệt (2 slot
  trùng), trong khi cần 6. q920: 3 slot chứa 2 tuple (1 slot trùng), cần 3.

Ý nghĩa: với 2 câu này, phiên bản round-robin theo tuple **không cần thêm một bảng nào** — chỉ
cần không tiêu hai slot cho cùng một (mã, năm). Điều đó **không mâu thuẫn** với số đo
`config.py:202-221` (nâng `codegen_max_tables` 3→10 làm tổng điểm tụt 33→29): số đo đó nói
"thêm bảng gần-trùng làm mô hình lẫn", còn dedupe theo tuple **giảm** số bảng gần-trùng ở cùng
một ngân sách prompt. Đây là hai việc ngược chiều nhau, không phải cùng một việc.

Với 488 (cần 4 tuple, cap 3) và 502 (cần 6, cap 5) thì vẫn phải nới cap — đó mới là phần rơi
vào vùng đã đo là có hại, và nên tách riêng khỏi phần dedupe.

Hai điểm nữa đã xác minh trực tiếp trong code, quan trọng cho quyết định:

- **Dedupe không thể làm hỏng DOCS_F2MACRO.** `graph.py:34-38` ghi rõ bước load **không** thu
  hẹp `state["table_ids"]` — cái được nộp — nó chỉ cắt bản cục bộ để đưa vào prompt (`:144`).
  Nên mọi thay đổi ở đây tách biệt hoàn toàn khỏi điểm retrieval đang cao (0.9488).
- **`year_round_robin` chỉ chạy khi `multi_year`** (`graph.py:139-140`). q488 (4 mã, 1 năm) là
  `multi_company` chứ không `multi_year` nên **không được interleave gì cả**, cap = 3. Đây đúng
  là lỗ hổng cơ chế, không phải suy đoán.

**Bằng chứng ngược, phải ghi lại (P1 tìm ra):** `config.py:282-292` — `codegen_tool_turns` mặc
định 0 vì đã đo và thất bại, và cụ thể: **6 câu có bảng gold bị table cap cắt "stayed exactly
as they were"** khi được cấp `find_rows` để với tay bằng tên. Đó là phép đo thứ hai trên đúng
lớp lỗi mà dedupe nhắm tới, và nó âm.

Artifact của lần chạy đó **còn tồn tại** (`artifacts/runs/gold94_tools.jsonl`), nên đã đối
chiếu được. Kết quả bác luôn đề xuất dedupe của tôi:

- Nhóm "bảng gold bị cap cắt" trong lần chạy đó là `[525, 530, 553, 732, 770]` — **không giao
  với 488/502/542/920**. Hai lớp lỗi thật sự khác nhau (một là "mất bảng gold", một là "mất một
  tuple trong nhiều tuple cần"), nên phép đo âm của P1 lúc đầu **không** áp vào 4 câu của tôi.
- Nhưng lần chạy `tool_turns=3` đó **có làm tăng coverage của chính 4 câu này**, và chúng vẫn sai:

| qid | gold | baseline pred | cov | tools pred | cov |
|---|---|---|---|---|---|
| 488 | 28,379904 | 0,000000 | 2/3 | 22,598887 | **3/3** SAI |
| 502 | 87,618442 | 1830,978066 | 1/2 | 1529,199064 | 1/2 SAI |
| 542 | 6,145490 | 0,046519 | 3/4 | 7,639048 | 3/4 SAI |
| 920 | 2982,289953 | 0,000000 | 0/3 | 700,483067 | **2/3** SAI |

q488 có **đủ 3/3 bảng gold trên màn hình** và vẫn sai. q920 từ 0/3 lên 2/3 và vẫn sai.

Hình dạng lỗi cho thấy rõ nút nghẽn nằm ở đâu:
- **q542**: `tools` trả đúng `7,639048` = mức thay đổi của **riêng DCM** (theo `conversion` của
  gold), trong khi đáp án là **trung bình DCM+DPM** = 6,145490. Tính một công ty rồi dừng.
- **q502**: `tools` trả `1529,199064` = **số dư quỹ năm 2016** (gold ghi 2016 = 1.529.199.064.366),
  trong khi câu hỏi cần *lãi dự thu của năm có số dư lớn nhất* (2020). Sai cả chỉ tiêu lẫn năm —
  chính bước argmax là bài toán.
- **q488**: đủ bảng, sai ở bước lọc điều kiện ">10%" rồi tổng.

**Kết luận sửa lại: đề xuất dedupe của tôi không sống nổi qua phép thử của chính nó.** Cả 4 câu
đều thất bại ở bước lọc-điều-kiện/tổng-hợp nhiều bảng, không ở việc bảng có mặt hay không. Đây
đúng là kết luận P3 đã nêu cho 5 câu kia, và khớp với `decompose.py` đo 3/34. Trần thật của
phương án 3 là **0**, không phải 4.

Cảnh báo về độ chặt: lần chạy `tools` khác baseline ở nhiều hơn một biến (có `find_rows`, `|ev|`
lớn hơn, sampling khác), nên đây **không** phải ablation sạch của riêng coverage. Nhưng nó là
bằng chứng gần nhất có được, và nó chỉ về hướng âm.

## Phân lớp 21 câu sai theo TẦNG thất bại (đo trực tiếp, offline, 0 đồng)

Câu hỏi "nên cải thiện tầng nào" trả lời được không cần chạy LLM. Với mỗi câu sai trong
`gold73_qwen35_planner.jsonl`, so bộ bảng gold (`evidence_table_id`, tách bằng regex
`\w+\|\d+` — nó là danh sách phân cách `;`, **không** phải một id) với `table_ids` trước cắt
và `diag.evidence_tables` sau cắt:

| Tầng thất bại | n | Nhóm câu |
|---|---|---|
| Đúng tài liệu, **sai bảng trong tài liệu đó** | **6** | 166, 280, 502, 530, 871, 974 |
| Bảng gold đã retrieve nhưng **bị bước cắt** | 6 | 263, 488, 525, 542, 685, 920 |
| **Đủ** bảng gold trên màn hình, vẫn sai | 4 | 526, 555, 878, 946 |
| Sai cả tài liệu | 2 | 355, 790 |
| Gold không ghi bảng, không phân loại được | 3 | 524, 582, 754 |

**12/21 câu sai vì bảng cần thiết không có trước mặt mô hình** (6 ở tầng xếp hạng bảng, 6 ở
bước cắt), chỉ **4/21** sai khi đã có đủ. Khớp với mọi số đo khác: DOCS_F2 0,9488 đã bão hoà
nên tầng *tài liệu* chỉ mất 2 câu; ô đọc đúng đã 194/198 nên tầng *render cell* mất 0-1 câu.

Thêm một số đo về hình dạng code sinh ra: **0/21** biểu thức `pandas_query` có bất kỳ phép gộp
/lọc/argmax nào (`.sum()`, `.max()`, `.idxmax()`, `.loc[...]`, `.query()`). Tất cả đều là
`df.iloc[i]["col"]` viết tay, kể cả các câu argmax — chúng dùng `max(ô1, ô2, ô3)` trên các ô
mô hình *đoán*, không phải argmax trên dữ liệu.

### Nhóm 6 câu "đúng tài liệu, sai bảng": nguyên nhân, soi từng ca

Đây là nhóm **chưa ai chạm tới**, và là nhóm đầu tiên trong cả phiên có trần (6) **vượt sàn
nhiễu 2**. Soi metadata bảng-cần so với bảng-được-chọn:

- **q530 NAB**: cần `|30` `note_title="CHO VAY KHÁCH HÀNG"`, chọn `|26` `note_title="TIỀN GỬI
  TẠI VÀ CHO VAY CÁC TCTD KHÁC"`. Cả hai có dòng đầu `"Nợ đủ tiêu chuẩn"`. **Metadata đúng và
  đủ phân biệt — tầng xếp hạng vẫn chọn sai.** Đây là lỗi ranking thuần.
- **q871 MPC**: cần `|46` (note 19, quỹ khen thưởng, dòng "Số dư đầu năm/Trích lập trong năm"),
  chọn `|48` — có **`note_id_inherited=True`** nên mang y nguyên `note_title` của note 19 dù
  nội dung là bảng biến động vốn chủ. **Lỗi metadata: note_id kế thừa tạo ra bảng song sinh
  cùng tiêu đề.**
- **q280 HDB**: bảng cần có `note_id=''` và `note_title=''` — **rỗng hoàn toàn**. Nhãn cần
  (`"Cho vay tái tài trợ về nghiệp vụ UPAS L/C"`) nằm trong `first_col_labels` nên text có ở
  đó, nhưng bảng không có danh tính để khớp. **Lỗi metadata: thiếu tiêu đề.**
- **q166 HBC**: cần `|71` note 32, `note_title="NGHIỆP VỤ VỚI BÊN LIÊN QUẢN"` — **OCR sai
  "QUẢN" thay vì "QUAN"**, đủ để phá khớp BM25 trên "bên liên quan". **Lỗi metadata: nhiễu OCR
  trong tiêu đề.**

Tức 3/4 ca soi tay là **chất lượng metadata ở tầng *danh tính bảng*** (bảng này nói về cái gì),
1/4 là ranking thuần. Đây là tầng metadata **khác** với tầng P4 điều tra (render ô, đã sạch
194/198) — nên kết luận "metadata không phải nút nghẽn" của P4 **không** áp cho tầng này.

Tỉ lệ hỏng tiêu đề, chỉ tính bảng `statement_type="note"`:

| | bảng note | `note_title` rỗng |
|---|---|---|
| bảng gold của câu **sai** | 18 | **5 (28%)** |
| bảng gold của câu **đúng** | 32 | 2 (6%) |
| toàn corpus | 124.279 | 20.290 (16,3%) |

Chênh 28% vs 6% đúng hướng nhưng **n=5 so với 2** — gợi ý, chưa phải bằng chứng. Còn
`note_id_inherited` phủ 19.246/124.279 (15,5%) bảng note, và q871 cho thấy nó có thể *tạo* ra
bảng nhiễu chứ không chỉ bỏ sót.

**Hệ quả cho leaderboard**: đây đúng là tầng mà `TABLES_F2MACRO` đo, và nó đang bằng 0,0 vì
lệch hệ đánh số với BTC. Ta chưa từng tối ưu tầng này vì không nhìn thấy nó. Thước đo cục bộ
thì có sẵn: `evidence_table_id` trong `unbiased60_gold.jsonl` + `manual15_gold.jsonl`.

## Thử bộ chọn bảng theo metadata — TRƯỢT ngưỡng tự đặt

Ngưỡng đăng ký trước: bộ chọn phải surface **≥8/12** bảng gold mà retrieval chưa từng thấy.

Baseline recall bảng gold (59 câu có `evidence_table_id`, 95 bảng gold):

| | recall | câu đủ bộ |
|---|---|---|
| trong `table_ids` đã nộp (median 14 bảng/câu) | 83/95 = **87,4%** | 48/59 |
| sau bước cắt vào codegen | 58/95 = **61,1%** | 34/59 |

12 bảng gold retrieval chưa từng thấy, **9 thuộc câu đang sai** (166, 280, 355, 502, 530, 790,
871, 920, 974).

Prototype (lọc theo mã + `period_years`, chấm idf trên `note_title`×3 + `section_title` +
`first_col_labels`): **1/12 @k=5, 2/12 @k=10, 6/12 @k=20, 7/12 @k=50**. **Trượt ngưỡng.**
Nhưng q530 ra **rank 1** — ca tôi dự đoán là "metadata đúng, ranker không dùng" — nên cơ chế
đúng, chỉ bị 4 khuyết tật cụ thể chặn. Sáu ca trượt, soi từng cái:

| câu | bảng cần | vì sao trượt | loại |
|---|---|---|---|
| 790 | `BID\|30` | `tickers=['VIB']` — "BIDV" không map sang `BID`, pool chưa bao giờ có BID | alias, **tất định** |
| 502 | `PLX_2020\|12` "Phải thu ngắn hạn khác" | chỉ tiêu cần ("lãi dự thu") nằm trong `first_col_labels`, và **chỉ biết được sau step 1** (năm có quỹ bình ổn lớn nhất) | cần retrieval theo step |
| 974 | `CTG_2025\|81` | `note_title=''` | tiêu đề rỗng |
| 521 | `HDG_2024\|10` | `note_title=''` | tiêu đề rỗng |
| 871 | `MPC_2024\|46` | bảng song sinh `\|48` có `note_id_inherited=True` mang cùng tiêu đề, đè lên | note_id kế thừa |
| 920 | `GVR_2025\|33` | khái niệm cần ("công ty liên kết") ở sub-header, không có trong `first_col_labels` | khó thật |

### Lỗ alias, đo đúng cách: 2/1012

`MANUAL_ALIASES` (`questions.py:44-63`) là 18 dòng tay, có `Eximbank`/`MBBank`/`Saigonbank`
nhưng **không có `BIDV`, `Vietcombank`, `VietinBank`, `Techcombank`, `Agribank`, `VPBank`,
`Sacombank`**. Dựng alias thương hiệu cho đúng 21 ngân hàng trong corpus, khớp theo biên từ:
**2/1012 câu** bị mất mã (q790, q800 — cả hai là BIDV). Nhỏ, nhưng là fix **tất định** nên
sàn nhiễu 2 câu không áp dụng: hiệu ứng tái lập chính xác, kiểm được offline.

(Phép đo đầu tiên của tôi ra 565/1012 — **rác**, do khớp chuỗi con trên từ 3 ký tự nên
"nam"/"phú"/"hải" khớp bừa. Đã bỏ. `distinct['BID']` rỗng vì mọi từ trong "Ngân hàng TMCP Đầu
tư và Phát triển Việt Nam" đều chung với công ty khác — phép đo đó về nguyên tắc không thể
tìm ra q790.)

### `note_title` rỗng: 49% dồn vào 147 report chết hẳn

| | |
|---|---|
| bảng note | 124.279 |
| `note_title` rỗng | 20.290 (16,3%) |
| có bảng note CÓ tiêu đề ngay trước, cùng report (suy được bằng carry-forward) | 2.765 (13,6% số rỗng) |
| **report mà 100% bảng note không có tiêu đề** | **147/1.944 report = 9.982 bảng = 49% số rỗng** |

Tệ nhất: `GEG_2024_consolidated` 167/167, `ACB_2025_consolidated` 121/121,
`PNJ_2025_consolidated` 117/117, `GAS_2024_consolidated` 110/110. Và đúng hai report của bảng
gold bị trượt: **`CTG_2025_consolidated` 92/92**, **`HDB_2022_consolidated` 104/104** — tức
q974 và q280. Đây là lỗi trích ở tầng **report**, không phải thiếu lẻ tẻ từng bảng, nên
carry-forward chỉ vá được 13,6%.

Hai điều làm việc này quan trọng hơn vẻ ngoài của nó:

- **`note_title` nằm trong CẢ BA view đánh index** (`document_text.py:5-8`): `doc_text`
  (BM25 + reranker), `dense_text`, `judge_text`. Nên nó là khuyết tật tầng *retrieval*, không
  phải metadata trang trí.
- **Không có nơi nào trong repo SINH ra `note_title`.** Mọi tham chiếu trong `src/` và
  `scripts/` đều là *đọc* (`document_text.py`, `metadata_enrichment.py:294`,
  `raw_table_linker.py`, `table_profile.py`, `lookup.py`, `context.py`, `filters.py`,
  `audit_tier1.py`, `diag_repr*.py`). Nó đến từ code đã dựng
  `tables_metadata_v2.jsonl` và không còn trong repo. **Nên sửa việc này là viết code mới +
  rebuild có staging, không phải vá một extractor sẵn có.**

## Việc chưa xác minh được trong lượt này

- Dedupe theo tuple có làm hỏng câu nào đang đúng hay không — chưa đo, cần 1 lượt chạy 73 câu.
- Tỉ lệ thật của "chênh lệch không hướng" trong 1.012 câu: chỉ có ước lượng từ khoá thô
  89/1.012, không có nhãn tay.
- Ngưỡng `ambiguous` của `cell_locator` (q263 lệch đúng biên 0.04) có làm vỡ 13 câu
  "ambiguous nhưng đúng nhờ fallback" hay không — cần rerun có LLM.
- Dung sai chấm điểm `ANSWER_ACCURACY` thật của BTC (ảnh hưởng việc làm tròn 2 chữ số).

---

# Sửa tất định đã vào code + kết quả cược chính (note_title)

## 1. `BIDV` vào `MANUAL_ALIASES` — XONG

`questions.py`. Trong 21 mã ngân hàng của corpus, `BID` là mã duy nhất mà không luật
nào phía câu hỏi với tới được: tên pháp lý "Ngân hàng TMCP Đầu tư và Phát triển Việt
Nam" không sinh ra chữ ký nào chứa "BIDV", và mọi từ trong tên đó đều chia sẻ với tổ
chức phát hành khác, nên `name_signatures` không thể suy ra. Đúng **2 trong 1.012** câu
đổi (790: `['VIB']` → `['BID','VIB']`, 800: `['MSB']` → `['BID','MSB']`), không câu nào
khác bị ảnh hưởng. Không cần dựng lại `questions_enriched.jsonl` vì `understand.py:58`
gọi `find_tickers` lúc chạy.

## 2. Quy tắc độ lớn trên đường codegen — XONG, +2 trên gold73

Kế hoạch ban đầu ("`abs` cho `operation="diff"`") **sai** và đã bị đo bác bỏ: trần của nó
là 0 câu, và nó sẽ làm vỡ q752 (gold −3.903.526) cùng q759 (gold −3,100151), hai câu
"chênh lệch" mà gold **giữ dấu âm**. Không triển khai.

Nguyên nhân thật của q526: ô đọc được là `(83.790.676.915)` → parse thành −83,79 trong khi
gold là +83,79. Quy tắc xử lý việc này đã tồn tại từ lâu trong
`cell_locator.value_transform`, nhưng **đường codegen chưa bao giờ hỏi tới nó**.

Đã làm:
- `intent.py`: `MAGNITUDE_METRIC` + `SIGNED_METRIC` chuyển từ `cell_locator` lên thành
  vốn từ dùng chung, thêm `MAGNITUDE_BLOCK`. `cell_locator` import lại — hành vi y nguyên.
  (Import `value_transform` từ `solvers/` vào `codegen/` sẽ là vi phạm tầng.)
- `execute.py`: `as_magnitude()` + bọc `abs(...)` **trong query**, bên trong hệ số quy đổi
  đơn vị. Vào query chứ không vào con số, vì `EXECUTION_ACCURACY` chạy lại chính chuỗi đã
  submit — đặt `abs` ngoài query là làm hai chỉ số lệch nhau.

Đo trên `full1012_v7.jsonl` bằng đúng hàm đã ship, không phải predicate nháp:

| | n | câu |
|---|---|---|
| Ô âm có chỉ tiêu chi phí, trên đường codegen | 14 | |
| → đổi dấu | **11** | 194, 197, 436, 525, 526, 651, 712, 839, 862, 865, 924 |
| → guard chặn | 3 | 454 (diff), 601 (diff), 639 (block) |

Trên gold73: **LỜI 2 (q525, q526), LỖ 0.** Cả hai là sai dấu thuần — biên độ khớp gold
tới 12 chữ số, chỉ khác dấu (q525 `-1.582259850422` vs `1.582259850422`; q526
`-83.790676915` vs `83.790676915`).

Lưu ý con số cũ "12 đổi / 6 chặn" đo trên *mọi* solver; 599, 603, 778 nằm ở
`raw_table_linker`/`formula_facts`, không đi qua `apply_units` nên thay đổi này không
với tới. Test: `tests/test_solve_units.py` (5 shape bị chặn, 2 shape đổi, và
`scaled` không bị `abs` làm nhiễu).

## 3. Lỗi lệch một bảng của `context_page_text` — TÌM THẤY KHI DỌN ĐƯỜNG, ĐÃ SỬA

`table_pos` là **1-based** (min toàn cục trên 146.246 dòng = 1; mỗi report chạy đúng
1..len(tables), đối chiếu với `find_table_offsets`). Nhưng
`metadata_enrichment.py` lấy `cur_offsets[tpos]` — tức là **trang của bảng KẾ TIẾP**.
`metadata_v3.py` đã làm đúng (`idx = tpos - 1`) từ trước; chỉ producer là sai.

Đo trên mẫu 152 report / 11.136 bảng:

| | n | tỉ lệ |
|---|---|---|
| `context_page_text` lấy sai trang | 6.622 | **59,5%** |
| → bảng cuối report, chạy quá mảng nên nhận `""` | 151 | 1 mỗi report |
| Đọc sai "Đơn vị tính" từ trang đó | 375 | **3,4%** |
| → sửa xong *thêm* khai báo trước đây không có | 187 | |
| → sửa xong *bỏ* khai báo đọc nhầm từ trang khác | 183 | |
| → sửa xong *đổi* sang đơn vị khác | 5 | |

Ví dụ sạch trên `AAA_2015_consolidated`: trang lưu cho bảng 1 chính là trang của bảng 2,
trang lưu cho bảng 2 là trang của bảng 3 — dịch đúng một bảng.

Ảnh hưởng: `page_text()` → `detect_unit` (nơi tìm dòng "Đơn vị tính", sai đơn vị là sai
1.000 lần), và prose hiển thị cho model trong `context.py`. **Không** ảnh hưởng retrieval:
`document_text.py` cố tình loại `context_page_text` khỏi cả ba view index.

Đã sửa producer + tách `page_prose_for()` cho testable được, test mới
`tests/test_metadata_enrichment.py`. **Chưa dựng lại artifact**:
`tables_metadata_v2.jsonl` là artifact được bảo vệ (`DECISIONS.md` §8), nên giá trị đã
sửa chỉ xuất hiện sau một lần rebuild qua đường staging — đó là quyết định của bạn, không
phải của tôi.

## 4. Cược chính `note_title`: extractor CHẠY ĐƯỢC, nhưng tiền đề TRƯỢT

Quy tắc: đi dọc OCR của report theo thứ tự tài liệu, nhận heading dạng số-đầu-dòng
(`19 CÁC KHOẢN PHẢI TRẢ VÀ CÔNG NỢ KHÁC`), lọc phần chạy trang lặp lại
("Mẫu số", "THUYẾT MINH BÁO CÁO...", rail `1 2 3 4 5`), rồi gán cho mỗi bảng heading
đang có hiệu lực tại vị trí bảng đó. Gán theo vị trí tài liệu chứ không theo trang là
điều bắt buộc: 19,3% title hiện có **không** nằm trên trang của chính bảng nó
(bảng tiếp nối — ACB|26,27,33 mang title từ trang trước). Probe:
`scripts/probe_note_title.py`.

Đối chiếu trên các report *đã có* title (2.668 bảng note):

| | n | tỉ lệ |
|---|---|---|
| Khớp chính xác (đã normalize) | 2.016 | 75,6% |
| Một bên chứa bên kia | 462 | 17,3% |
| Lệch | 189 | 7,1% |
| Quy tắc không tìm được heading | 1 | 0,0% |

→ **92,9% đồng thuận.** Và nhiều ca "lệch" là v1 sai, không phải quy tắc sai:
`AAA|13` v1 ghi `'20. 10. 30. 25.'`; `ACB_2016_separate|101..111` v1 ghi
`'Báo cáo bộ phận'` cho 11 bảng liền trong khi quy tắc theo đúng heading đang chạy.

Trên 147 report chết: **9.654 / 9.980 bảng (96,7%) lấy lại được title.**

### Nhưng đây là con số quyết định — và nó trượt

11 bảng gold chưa bao giờ được retrieve, xem quy tắc mới cho gì:

| Câu | Bảng gold | note_title cũ | Quy tắc mới |
|---|---|---|---|
| 280 | HDB_2022_consolidated\|19 | *(rỗng)* | `TIỀN GỦI VÀ CHO VAY CÁC TCTD KHÁC` ✅ |
| 355 | MSN_2022_consolidated\|23 | *(rỗng)* | `Thông tin này đã được công bố trên trang…` ❌ rác |
| 521 | HDG_2024_consolidated\|10 | *(rỗng)* | `Hai Trieu Street, District 1` ❌ rác |
| 166 | HBC_2016_separate\|71 | `NGHIỆP VỤ VỚI BÊN LIÊN QUẢN (tiếp theo)` | y nguyên, chỉ bỏ "(tiếp theo)" |
| 259 | VIC_2023_consolidated\|20 | `PHẢI THU VỀ CHO VAY` | **không đổi** |
| 502 | PLX_2020_separate\|12, \|35 | `Phải thu ngắn hạn khác`, `Quỹ bình ôn giá xăng dâu` | **không đổi** |
| 790 | BID_2023_separate\|30 | `CHO VAY KHÁCH HÀNG` | **không đổi** |
| 856 | PC1_2023\|73, PC1_2024\|77 | `Lãi cơ bản trên cổ phiếu` | **không đổi** |
| 920 | GVR_2025_consolidated\|33 | `CÁC KHOÀN ĐẦU TƯ TÀI CHÍNH` | **không đổi** |

**8 trong 11 bảng gold bị bỏ sót ĐÃ CÓ title đúng và phân biệt được.** Chỉ 1 bảng
(q280) được title dùng được, và 2 bảng nhận title rác — rác này có thể làm *hại*, vì nó
đi vào cả ba view index. Cược chính đặt ra là "sửa `note_title` → nâng recall bảng gold";
đo được **nhiều nhất 1/11, kèm 2 rủi ro âm**. Không ship.

Điều này đóng lại một giả thuyết chứ không phải mở ra một cơ chế: 147 report chết là
thật, extractor chạy tốt (96,7%), nhưng **những bảng ta thực sự bỏ sót không bỏ sót vì
thiếu title.** Chúng bỏ sót vì **xếp hạng** — đúng như q530 đã chỉ ra ở §2 phía trên
(metadata sạch, phân biệt được, vẫn bị xếp sau).

### Nút thắt còn lại, sau khi đã loại trừ

- LLM logic: 4 phép đo âm.
- Render ô: 194/198 sạch (P4) → 0–1 câu.
- Doc retrieval: `DOCS_F2 0.9488`, chỉ 2/21 câu sai ở tầng này.
- `note_title`: 1/11 (mục này).
- **Xếp hạng bảng trong đúng tài liệu: 8/11 bảng gold bỏ sót + 6/21 câu sai.** Đây là chỗ duy nhất còn lại.

---

## Grounding nhãn dòng cho codegen — đo xong, trần bằng 0, không xây

Giả thuyết: codegen địa chỉ hoá dòng bằng vị trí (`df1.iloc[13][...]`, **520/520**
query) và `diag.target_row` là số trần 46,3% / rỗng 50,8% / nhãn thật chỉ 2,9%, nên
không có gì kiểm được nó đáp xuống dòng nào. Nghe rất giống ô E của BTC (Numerical
Extraction 54,7%) và câu p42 "Cell Grounding là trọng tâm".

Đo (`scripts/probe_row_grounding.py`, tất định, không gọi LLM):

| phép đo | kết quả |
|---|---|
| Oracle: thay chỉ số dòng gold vào rồi chạy lại query (n=12) | **sai→đúng 0, đúng→sai 0** |
| Số câu vốn đã dùng đúng chỉ số dòng | 11/12 |
| Bản tất định qua `lookup.search_rows` | 0 câu cứu, **3 câu đang đúng bị phá** |
| M1: tỉ lệ *phát hiện được* bằng so khớp nhãn | ~19,6% câu, so với tỉ lệ sai thật ~47% |
| M5: dòng gold bị `_grid` cắt/ẩn | 0/12 — lưới không phải nút thắt ở mẫu này |

**Không xây.** Và phải ghi lại một sai lầm phương pháp: bucket "đúng bảng, sai dòng"
trong phân loại đầu tiên là **artifact của chính bộ phân loại** — nó so `target_row`
với nhãn gold, trong khi `target_row` là chỉ số số theo *thiết kế* (`CODEGEN_SYSTEM`
dặn thẳng "Never use `.loc[...]`", và `execute.py:_row_dump` parse nó bằng `int()`).
Suy từ "không có grounding nhãn" (đúng) sang "dòng đang bị đọc sai" (sai).

## Câu hỏi "năm nào": sai dạng đáp án

53 câu trong 1.012 hỏi *năm nào* một chỉ tiêu đạt cực trị. `raw_selection_linker` trả
đúng dạng năm cho 17/18 câu nó nhận, bằng `(<ô thắng>) * 0 + <năm>` — query chạy lại
vẫn ra năm nên `EXECUTION_ACCURACY` không vỡ. `codegen` (28) và `selection_facts` (7)
trả về **giá trị** của ô thắng: 35 câu sai theo định nghĩa. Đã đọc tay cả 35, không
câu nào mơ hồ.

Nhưng trần thật nhỏ hơn nhiều con số 35. Phân nhóm cấu trúc từ `pandas_query`:

| nhóm | số câu | nghĩa |
|---|---|---|
| A. có `max()` qua nhiều năm | 18 | ứng viên thật |
| Y. bằng chứng chỉ chạm 1 năm | 13 | lỗi *chọn bằng chứng*, đội lốt lỗi dạng |
| X. giá trị = 0 | 3 | hỏng sâu hơn |
| B. nhiều năm, không có `max()` | 1 | |

`scripts/gate_year_shape.py` lấy ý kiến thứ hai độc lập: mô hình chỉ thấy câu hỏi và
đúng bộ bảng pipeline đã thấy, chỉ được trả về một cái năm, prompt cố ý trung tính.
Đem so với năm suy ngược từ `pandas_query`.

    đồng thuận 9   bất đồng 2   không suy ngược được 11   prototype bỏ trống 13

Điểm neo: q946 cả hai đều ra 2022, **gold = 2022**.

Hai câu bất đồng soi tay xong thì **không câu nào là lỗi dạng**:
- q907 — ba năm **hoà** ở 407 (2019/2020/2021); `max()` trả năm đầu tiên. Câu hỏi tự nó
  nhập nhằng, không sửa được bằng bước chiếu.
- q841 — hỏi **tổng** chi phí trả trước, query đọc cột `Chi phí đất trả trước`, tức một
  thành phần. Sai cột, không phải sai dạng.

**Ước lượng đã đo: ~9 câu** (q822, q832, q874, q921, q936, q946, q948, q960, q978),
tức khoảng +0,9 điểm `ANSWER_ACCURACY`. Con số đầu tiên tôi đưa ra là "+20 đến +32";
nó là **ước lượng chứ không phải phép đo**, và đã bị chính phép đo cắt xuống còn một
phần tư. Ghi lại để lần sau không lặp lại.

### Hai phát hiện phụ, chưa xử lý

- **102/1012 câu submit `pandas_query` là một số trần** (54 `formula_facts` + 48
  `selection_facts`), `item.evidence` rỗng hoàn toàn — 48/48 câu `selection_facts`.
  Chúng qua `EXECUTION_ACCURACY` một cách vô nghĩa vì số trần chạy lại ra chính nó, và
  không có neo bằng chứng nào.
- **`TABLES_F2MACRO = 0.0`** dù `relevant_tables` có đủ cho cả 1.012 câu (có câu nộp
  58–59 bảng). Số 0 tròn trĩnh gợi ý lệch định dạng/khoá chứ không phải precision thấp.
  Đây là **cả một chỉ số đang bằng không** — đáng soi trước mọi thứ khác trong danh sách.
