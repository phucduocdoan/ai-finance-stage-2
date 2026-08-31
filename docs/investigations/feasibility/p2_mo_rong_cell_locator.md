# Phương án 2 — Mở rộng solver `cell_locator`: đánh giá khả thi

Đo trên `artifacts/runs/gold73_qwen35_planner.jsonl` (config default, 52/73) bằng
`scripts/score_gold75.py --blame` (không gọi LLM/reranker) và bằng heredoc Python đọc
trực tiếp field `diag` của từng dòng. Đối chiếu code: `cell_locator.py`,
`capability_router.py`, `raw_table_linker.py`, `selection_facts.py`, `formula_facts.py`,
`table_linking/{columns,rows,schema}.py`, và repo song song
`ai-finance-stage-2-refactor/SPEC.md` + `src/r2ai/corpus/{build,to_dataframe}.py`.

## Kết luận

**Khả thi có điều kiện, nhưng trần lợi ích ≈ 1 câu trên 73 — dưới sàn nhiễu 2 câu.**
Không đáng làm như một hạng mục riêng. Đo trực tiếp 65 câu không do `cell_locator` giải:
35 câu (54%) bị chặn bởi gate "đúng 1 mã, đúng 1 năm" — đây là **thiết kế có chủ đích**,
không phải bug, và mọi câu trong nhóm này đã được soi tay là câu nhiều-ô thật (nhiều năm/
nhiều công ty) — mở rộng sang đó là xây một solver khác (aggregate/selection), không phải
"mở rộng cell_locator". Trong 24 câu lọt qua gate nhưng thất bại nội bộ (ambiguous/
below-threshold/no-cell), chỉ có 3 câu ra sai ở downstream, và soi từng câu cho thấy 2/3 là
lỗi tầng khác (header bị OCR lệch, bảng retrieve sai) — cell_locator không thể sửa được dù
mở rộng logic nội bộ. Câu còn lại (id 263) là một ranh giới nổi/trượt do làm tròn số thực,
không phải một khoảng trống chức năng có thể tổng quát hoá thành luật mới.

Đối chiếu với đo lường "60 câu cell-truth" đã ghi trong `common/lookup.py:1-21` và
`config.py:202-311` (21/30 câu sai của đường `codegen` có bảng gold sẵn trên màn hình mà
vẫn sai, và "cho model xem nhiều bảng hơn" đã bị đo và loại): đây là bằng chứng **ủng hộ
hướng đi** của `cell_locator` (rule tường minh, tra theo tên — nó đã có sẵn guard
`_TOTAL_TOKEN` đúng cho đúng lớp lỗi "dòng thành phần vs dòng tổng" đó), nhưng **không**
nới trần lợi ích 1/73 đã đo, vì đó là số đo trên một đường khác (`codegen` cô lập, cấu
hình/thời điểm khác) và không câu nào trong 21 câu sai hiện tại của tôi khớp đúng khuôn
mẫu đó khi soi tay. Xem mục riêng "Đối chiếu với bằng chứng 60 câu cell-truth" ở dưới.

## `cell_locator` làm gì, và vì sao chỉ fire 8/73

`cell_locator.py` là một **gate hai tầng, fail-closed cả hai tầng**:

- **Tầng 1 — `build_request` (`cell_locator.py:215-242`)**: chỉ tạo được yêu cầu khi
  `len(tickers) == 1 và len(years) == 1` (`cell_locator.py:220-221`), không có cờ
  `multi_year`/`multi_company` (`:222-223`), câu hỏi không khớp `_DERIVED_MARKER` — regex
  bắt các từ tỷ suất/tỷ lệ/hệ số/tăng trưởng/chênh lệch/cao nhất/thấp nhất/trung bình
  (`:39-45, :224-225`), và hình dạng câu hỏi là `lookup`/`single_cell`
  (`:226`). Đây là gate được `capability_router._cell_locator_decision`
  (`capability_router.py:81-94`) gọi lại nguyên văn để quyết định "attempt".
- **Tầng 2 — `locate_single_cell` (`cell_locator.py:363-421`)**: dò `search_rows` theo các
  `metric_phrases`, chấm điểm cột bằng `_column_choice` (`:269-303`, ưu tiên năm khớp tường
  minh > năm suy ra > kỳ hiện/kỳ trước), rồi **từ chối** nếu: không tìm được ô số nào
  (`"no located numeric cell"`, `:387-388`), điểm tin cậy tốt nhất `< threshold=0.78`
  (`"below confidence threshold"`, `:397-403`), hoặc ô tốt nhất và ô nhì cách nhau
  `< 0.04` điểm nhưng là hai ô khác nhau (`"ambiguous located cells"`, `:404-415`).

Bảng đếm lý do không do `cell_locator` giải, trên toàn bộ 73 câu (đo bằng heredoc, không
suy đoán), **tách hai tầng theo yêu cầu** — (a) *router không cho phép thử*
(`build_request` trả `None`, tức "không được phép thử") và (b) *cho phép thử nhưng
`locate_single_cell` tự từ chối* (fail-closed nội bộ, "thử rồi nhưng đóng lại"). Hai tầng
này cần cách sửa khác nhau và có trần lợi ích khác nhau, nên bảng dưới ghi kèm số câu
đúng/sai hiện tại trong mỗi ô — đây là dữ liệu quyết định trần lợi ích, không phải tổng số
câu không fire:

**(a) Gate 1 — router không cho phép thử (41 câu)**

| lý do | tổng | đang ĐÚNG (qua solver khác) | đang SAI |
|---|---:|---:|---:|
| cần đúng 1 mã + đúng 1 năm | 35 | 20 | 15 |
| derived or comparison marker (`_DERIVED_MARKER`) | 4 | 2 | 2 |
| multi-axis question (cờ state) | 1 | 0 | 1 |
| not a lookup-shaped question | 1 | 1 | 0 |

**(b) Gate 2 — cho thử nhưng `locate_single_cell` tự từ chối (24 câu)**

| lý do | tổng | đang ĐÚNG (qua solver khác) | đang SAI |
|---|---:|---:|---:|
| ambiguous located cells | 14 | 13 | 1 |
| below confidence threshold | 6 | 4 | 2 |
| no located numeric cell | 4 | 4 | 0 |

**Fired (`cell_locator` là solver-of-record): 8/8 đúng.**

Trần lợi ích theo từng ô đã soi tay (chi tiết ở mục "Soi tay 3 câu" và ở mục kết luận):
cột "đang SAI" chỉ có giá trị nếu soi tay xác nhận nguyên nhân sai **nằm trong khả năng
sửa của `cell_locator`** — soi tay cho thấy 15 câu ở dòng đầu gate 1 là nhiều-ô thật
(không sửa được trong `cell_locator`), 2 câu derived-marker cần chia hai dòng/bảng (việc
của `formula_facts`, không phải `cell_locator`), 1 câu multi-axis là so sánh 2 công ty
(việc của phương án khác), và ở gate 2: 2 câu below-threshold là lỗi tầng khác (header
OCR lệch, bảng retrieve sai — mục "Soi tay" dưới), chỉ **1 câu** (`ambiguous`, id 263) là
cơ hội thật của `cell_locator`. Tổng trần lợi ích đo được: **1/21 câu sai**, không phải
21 hay 24.

(8 câu fired đều đúng — precision 100% trên mẫu này khi nó chịu trả lời. Đây là bằng chứng
gate hiện tại đang đúng hướng "thà im lặng còn hơn trả sai": mở rộng recall mà không giữ
được precision này là lỗ, không phải lời.)

Soi tay toàn bộ 35 câu ở dòng đầu bảng (id 488, 502, 524, 525, 526, 530, 542, 555, 582,
754, 790, 871, 878, 920, 946, 974, ...): **100% là câu có "Trong các năm ...", "Trong số
các công ty ..." trong văn bản câu hỏi** — tức nhiều-ô thật, không phải state extraction
đoán nhầm số lượng mã/năm. Gate này đang làm đúng việc của nó.

Với 24 câu lọt gate 1 nhưng gate 2 từ chối: 8 thành `cell_locator` (đúng cả 8, đã tính
trên), 24 rơi xuống solver khác. Trong 24 câu đó, **21 câu vẫn ra đúng nhờ solver dự
phòng** (12 qua `codegen`, 6 qua `raw_table_linker`, 3 qua `formula_facts`) — nghĩa là
việc gate 2 từ chối không làm mất điểm ở 21/24 câu này, dù có nới gate cũng không thêm gì.
Chỉ 3/24 ra sai ở downstream — xem mục dưới.

## Ranh giới với `raw_table_linker` và các solver khác

- **`raw_table_linker.py`** (`:1-10`, docstring): "next controlled slice" sau
  `long_format` — chuyên các bảng thô/note/ngân hàng không có `Mã số`. Gate của nó
  (`build_request`, `raw_table_linker.py:603-645`) tái dùng đúng `period_intent` và
  `value_transform` của `cell_locator` (import ở `:41`), nhưng **không** đòi đúng 1 mã +
  1 năm: `_scope_slots` (`:552-565`) build tới 8 slot (ticker × year) cho `sum`/`avg`/
  `diff`/`ratio`, và vẫn nhận `direct` (1 mã, 1 năm — trùng scope với `cell_locator`) khi
  gate 1 của `cell_locator` không đạt. Ranh giới thật: `cell_locator` = tra thẳng 1 ô đã
  có nhãn rõ; `raw_table_linker` = LLM chọn giữa các *candidate đã được Python liệt kê
  sẵn* (không viết pandas), cho cả single-cell lẫn multi-slot arithmetic (không gồm
  selection/lớn nhất-nhỏ nhất — `_infer_operation` loại `_SELECTION`/`_CONDITIONAL_FILTER`
  tường minh, `:574-575`).
- **`selection_facts.py`** (docstring `:1-7`): "sibling nhỏ và an toàn hơn của
  `structured_facts`", chỉ nhận câu có **một trục chọn lọc rõ ràng** (lớn nhất/nhỏ nhất
  theo năm hoặc theo công ty). Đây chính là nơi 35 câu "nhiều-ô" ở trên nên đi — nhưng nó
  chỉ fire 2/73 trên run này, cho thấy gate của nó cũng đang hẹp hơn nhu cầu thật. Đây là
  việc của phương án khác (planner trước retrieval / selection trục), **không phải việc
  của `cell_locator`.**
- **`formula_facts.py`**: "sibling hẹp hơn của `structured_facts`", công thức xác định
  trên 1 mã/năm (ratio, growth, diff, avg, median) — đây là nơi hai câu id 355 và 685
  (bị `cell_locator` chặn đúng vì khớp `_DERIVED_MARKER`) nên được giải; cả hai thực chất
  cần chia hai dòng/hai bảng (đối chiếu `pandas_query` gold: `(iloc[9]/iloc[4])*100` và
  `((iloc[1]+iloc[3])/df2.iloc[13])*100`) — không phải lỗi của `cell_locator`.
- **`table_linking/rows.py`** (docstring `:1-19`) đã xây riêng một tầng "ancestor chain"
  để xử lý đúng vấn đề bảng note nhiều tầng nhãn lặp (`Số cuối năm` xuất hiện 3 lần dưới
  3 mục khác nhau) — nhưng chỉ `raw_table_linker` dùng (`build_row_profiles`, import ở
  `raw_table_linker.py:46`). `cell_locator` vẫn gọi `search_rows` thô
  (`common/lookup.py:142`) không có ngữ cảnh tổ tiên. Đây là **nợ kỹ thuật có thật** —
  nhưng trong mẫu 73 câu, không câu sai nào rơi vào đúng tình huống "nhãn lặp cùng bảng"
  (xem mục dưới) nên không đo được lợi ích cụ thể, chỉ là rủi ro phòng ngừa cho tập ẩn.

**Kết luận ranh giới**: "mở rộng cell_locator" theo đúng nghĩa (đúng 1 mã, đúng 1 năm,
1 ô) đã gần chạm biên của lớp câu hỏi nó được thiết kế cho. Mở rộng thêm hầu như chắc chắn
là lấn sang việc của `raw_table_linker` (multi-slot arithmetic) hoặc `selection_facts`
(trục chọn lọc) — nên nếu muốn tăng số câu đúng ở lớp "đọc sai ô" (Numerical Extraction,
54.7% theo BTC), hướng có đòn bẩy cao hơn là mở gate của `selection_facts`/kích hoạt
`selection_decompose`/`raw_selection_linker` (hiện đều `enabled: false` trong run này —
xem `capability_trace` mỗi dòng), không phải nới `cell_locator`.

## Soi tay 3 câu "lọt gate 1 nhưng ra sai" — trần lợi ích thật

Trong 24 câu lọt gate 1, chỉ 3 câu (166, 263, 280) ra sai ở solver dự phòng. Đây là toàn
bộ "cơ hội" còn lại cho `cell_locator`:

- **id 263** (SSI, FVTPL, 2019): ô tốt nhất mà `cell_locator` tự tìm được
  (`table_id=...separate|11, row=22, column="Năm nay"`) **khớp đúng 100%** với
  `pandas_query` gold (`df1.iloc[22]['Năm nay']`). Nó bị `"ambiguous located cells"` từ
  chối vì ô nhì (một dòng khác, một bảng khác) chỉ kém `0.04` điểm — đúng ngay ngưỡng biên
  `< 0.04` (`cell_locator.py:404`), nơi sai số làm tròn dấu phẩy động có thể quyết định
  đậu/rớt. Đây là **một lỗi biên ngưỡng thật, hẹp, tổng quát hoá được** (sửa so sánh
  ngưỡng, không phải luật riêng cho SSI) — nhưng mẫu n=1 không đủ để biết nới ngưỡng có
  làm hỏng các câu khác đang "ambiguous nhưng đúng nhờ fallback" (13 câu còn lại trong
  nhóm `ambiguous`) hay không, vì ta không có nhãn đúng/sai cho *ô mà cell_locator tự chọn*
  ở 13 câu đó (chúng đúng nhờ solver khác, không phải nhờ ô top-1 của cell_locator).
- **id 166** (HBC, số dư cho vay, 2016): `cell_locator` chấm điểm thấp
  (`confidence=0.5187`) đúng, vì bảng nguồn có cột tiêu đề bị lệch — tên cột thực tế là
  `"232.189.027.778"` (một con số, không phải tên cột) do OCR/table-store dựng header sai
  dòng (đã xác minh bằng cách đọc trực tiếp
  `output/submission_frozen/data/HBC_financial_statements_2016_separate_table_71.csv`).
  Đây là lỗi ở tầng trích xuất bảng (`table_store`/OCR), **không thể sửa trong
  `cell_locator`** — mở rộng logic chọn ô không giúp gì khi tên cột vốn đã sai.
- **id 280** (HDB, UPAS L/C, 2022): `cell_locator` chọn nhầm bảng (`|69`, khớp từ khoá
  "UPAS L/C" ở một dòng doanh thu) trong khi bảng gold (`|4`) không nằm trong shortlist
  mà nó xếp hạng cao nhất cho câu này. Đây là lỗi **retrieval/shortlist bảng** (giống lớp
  "Insufficient/wrong-table evidence"), không phải lỗi định vị ô trong một bảng đã đúng —
  thuộc phạm vi truy xuất bảng, không phải `cell_locator`.

→ Trong 3 câu, đúng **1 câu (263)** là cơ hội thật của `cell_locator`, và ngay cả câu đó
cũng là sửa một ranh giới ngưỡng số thực, rủi ro đổi ngang (fix chỗ này, vỡ chỗ khác) cao
hơn giá trị thu về. **Trần lợi ích đo được: 1/73, thấp hơn sàn nhiễu 2 câu.**

## Đối chiếu với bằng chứng "60 câu cell-truth" và thí nghiệm `codegen_max_tables`

Team lead chỉ ra hai dữ kiện đã ghi trong code, không phải trong artifact chạy được —
tôi trích đúng nguyên văn, **không tự chạy lại** (không gọi LLM/reranker theo ràng buộc),
nên số liệu dưới đây là "đã đo, do người khác đo trước và ghi lại", khác với các số ở
mục trên là tôi tự đo lại được từ artifact hiện có.

- **`common/lookup.py:1-21`** (docstring, đã đọc trực tiếp): trên **60 câu cell-truth**
  (= `data/eval/unbiased60_gold.jsonl`, xác nhận file này đúng 60 dòng — là 60/73 câu
  gold không-manual của cùng bộ 73 tôi đang dùng), bảng gold qua được hard filter 60/60
  nhưng chỉ **49/60** tới được model, và trong 30 câu trả lời sai, **21 câu đã có bảng
  gold trên màn hình mà vẫn sai** — lỗi điển hình là lấy dòng thành phần thay dòng tổng.
  Đây là số đo trên đường **`codegen`/`generate_pandas`** (ablation cô lập, xem
  `config.py:274-311`: các cờ `codegen_max_tables`, `codegen_tool_turns`,
  `codegen_show_grids` đều là tham số của nhánh này), **không phải** số đo trên toàn bộ
  73 câu qua `capability_router` như mục trên — hai số không cùng đơn vị đo, không được
  cộng gộp.
- **`config.py:202-210`**: nâng `codegen_max_tables` 3→10 tăng coverage (37→47/73 câu có
  đủ bảng gold) nhưng tổng điểm tụt 33→29, tỉ lệ sai trong nhóm đó tăng 38%→53% ("column
  name taken from df2 used to index df5"). Đây là bằng chứng đã đo, đã loại, rằng "cho
  model xem nhiều bảng hơn" không phải hướng đúng.

**Đối chiếu hai dữ kiện này với chính `cell_locator`:**

1. `cell_locator` đã có sẵn đúng loại rule mà lỗi "dòng thành phần vs dòng tổng" cần: xem
   `_TOTAL_TOKEN = re.compile(r"\btong\b|\btong\s+cong\b")` (`cell_locator.py:72`) và
   `_hit_to_cell` (`:329-330`): *"if `_TOTAL_TOKEN` khớp trong `phrase` câu hỏi nhưng
   KHÔNG khớp trong `hit.label` của dòng ứng viên thì loại dòng đó"* — chặn đúng ví dụ
   team lead nêu (hỏi "Tổng chi phí..." mà ứng viên là dòng thành phần không có "tổng").
   `codegen` không có rule tương đương — nó là một LLM đọc lưới ô tự do, không có guard
   tường minh nào cho total-vs-component. Đây là lý lẽ kiến trúc thật: **cách cell_locator
   giải quyết lớp lỗi lớn nhất theo BTC (E — 54.7%) là encode luật tường minh, không phải
   đọc lưới ô** — đúng hướng "reach tables/rows by name" mà `lookup.py` kết luận, khác hẻn
   hướng "cho xem nhiều bảng hơn" đã bị đo và loại.
2. **Nhưng**: rule đó chỉ áp dụng được cho 32/73 câu (những câu lọt gate 1) — nó không
   giúp gì 41 câu không lọt gate 1. Và khi tôi soi lại chính xác **21 câu sai** trong bộ
   73 câu qua `capability_router` (mục "Soi tay" trên), **không câu nào khớp đúng khuôn
   mẫu "dòng thành phần vs dòng tổng"** mà team lead trích từ đo lường 60-cell-truth: 15
   câu là nhiều-ô, 2 câu cần chia bảng, 1 câu so sánh 2 công ty, 2 câu là lỗi header/
   retrieval, 1 câu là ranh giới ngưỡng số thực. Có ba khả năng, tôi **không đủ dữ liệu
   để chọn** giữa chúng: (a) đo 60-cell-truth chạy trên cấu hình cũ hơn — trước khi
   `_TOTAL_TOKEN` hoặc cả `capability_router` tồn tại, nên phần lỗi đó đã được vá từ đó
   tới nay; (b) đo 60-cell-truth cô lập đường `codegen`, còn trong run 73-câu hiện tại
   `codegen` chỉ còn xử lý 40/73 câu (phần dễ hơn đã được `cell_locator`/`raw_table_linker`/
   `formula_facts`/`selection_facts` lấy đi trước), nên tỉ lệ lỗi total-vs-component trong
   *phần còn lại* của `codegen` có thể đã thấp hơn 21/30 lịch sử; (c) mẫu 21 câu sai hiện
   tại chỉ là 21 câu, quá nhỏ để chắc chắn không chứa case này — cần một mẫu lớn hơn (ví
   dụ chạy lại `codegen` cô lập trên toàn bộ 73 hoặc trên bộ ẩn) để đo trực tiếp, nhưng
   việc đó cần chạy gate có LLM, ngoài phạm vi lượt đánh giá read-only này.

**Kết luận của mục này**: hai dữ kiện team lead đưa ra là bằng chứng ủng hộ *hướng đi*
của `cell_locator` (rule tường minh, tra theo tên, không đọc lưới ô) — không phải bằng
chứng nới **trần lợi ích 1/73** đã đo ở trên, vì (i) chúng đo trên một đường khác
(`codegen` cô lập) chứ không phải bộ 21 câu sai của run hiện tại, và (ii) khi tôi tìm câu
sai hiện tại khớp đúng khuôn mẫu đó, không tìm được câu nào. Nếu team lead muốn có số
thật trên toàn hệ thống hiện tại, cách duy nhất là chạy `codegen` cô lập (hoặc toàn pipeline)
trên tập lớn hơn 73 — có gọi LLM, tốn tiền, nằm ngoài ràng buộc của lượt này.

## Việc cần làm, ước lượng

Nếu vẫn muốn làm (ví dụ để phòng ngừa cho ~1000 câu ẩn, không chỉ 73 câu gold), xếp theo
lợi ích/rủi ro giảm dần:

1. **Sửa ranh giới ngưỡng `ambiguous located cells` do làm tròn dấu phẩy động**
   (`cell_locator.py:404`). Thay so sánh `< 0.04` trên giá trị đã `round(...,4)` bằng so
   sánh có epsilon, hoặc so sánh trên giá trị chưa làm tròn.
   *Verify*: chạy lại 73 câu (không cần gọi LLM lại vì đây chỉ đổi logic Python thuần —
   nhưng pipeline hiện tại gọi LLM ở node `understand`, nên cần chạy end-to-end lại qua
   gate có LLM); kỳ vọng id 263 chuyển `codegen`→sai thành `cell_locator`→đúng, và **không
   câu nào trong 8 câu đang đúng qua `cell_locator` bị đổi kết quả**, và không câu nào
   trong 13 câu "ambiguous nhưng đúng nhờ fallback" bị cướp mất đáp án đúng bởi một ô
   top-1 sai của `cell_locator`. Đây là điều kiện verify quan trọng nhất — hiện chưa đo
   được vì cần biết ô mà `cell_locator` sẽ chọn cho từng câu đó, không chỉ biết đáp án
   cuối đúng.
2. **Cho `cell_locator` dùng `table_linking.rows.build_row_profiles` (ancestor chain)**
   thay `search_rows` thô, để tránh nhầm nhãn lặp trong bảng note nhiều tầng (28.5% bảng
   có ≥2 tầng header theo đo của repo refactor, `to_dataframe.py:37-38`). *Verify*: không
   có câu nào trong 73 câu gold hiện đo được lợi ích trực tiếp (không câu sai nào khớp
   đúng tình huống này) — nên tiêu chí verify chỉ có thể là "không giảm 52/73 hiện tại"
   cộng với kiểm thử đơn vị tự viết trên vài bảng note nhiều tầng lấy từ corpus, không
   phải một con số cải thiện đo được trên 73 câu.
3. **Không** làm: nới gate 1 để nhận multi-year/multi-company — đây là xây solver khác
   (đã có `selection_facts`, đang có solver aggregate khác đang xét ở agent khác), gắn vào
   `cell_locator` sẽ phá tính "1 ô, 1 nghĩa" mà class/docstring của nó tuyên bố
   (`cell_locator.py:1-6`).

## Rủi ro và điều chưa biết

- **Chưa đo** hiệu ứng của việc 2 (ancestor chain) trên tập ẩn — chỉ có lý thuyết từ nợ kỹ
  thuật đã thấy trong code, không có câu gold nào xác nhận.
- **Chưa biết** liệu nới ngưỡng `0.78`/`0.04` có làm hỏng câu nào trong 13 câu
  "ambiguous nhưng đúng nhờ fallback" — cần rerun với log ô top-1 thực tế của
  `cell_locator` cho từng câu đó, việc này đòi phải chạy lại pipeline (có gọi LLM ở node
  `understand`), nằm ngoài phạm vi "chỉ đọc artifact có sẵn" của lượt đánh giá này.
  Team lead cần quyết định có đáng chạy gate thật (tốn tiền) để lấy số này không, trước
  khi implement.
- Mẫu 73 câu là mẫu nhỏ; "1/73" và "0 câu khớp lớp ancestor-chain" là số liệu đo được
  trên **mẫu đã có nhãn**, không phải trần thật trên toàn bộ ~1000 câu ẩn — không suy rộng
  quá tay từ số này.
- Số "60 câu cell-truth" (21/30 sai có bảng gold trên màn hình, `codegen_max_tables`
  3→10 làm điểm tụt 33→29) là số **trích từ comment trong code, không phải artifact tôi
  chạy lại được** trong lượt này — không có sàn nhiễu nào được ghi kèm cho con số đó, và
  tôi **không tự suy ra sàn nhiễu cho nó** (không đủ dữ liệu — không có per-question
  breakdown, chỉ có tổng). Không dùng sàn nhiễu 2 câu của bộ 73 cho số đó — chúng là hai
  đơn vị đo khác nhau (toàn pipeline qua `capability_router` vs `codegen` cô lập). Muốn có
  sàn nhiễu thật cho bộ 60-cell-truth, cần chạy lại đường đo đó ít nhất hai lần với hạt
  giống/điều kiện khác nhau — có gọi LLM, ngoài phạm vi lượt này.
- Không có bất kỳ đề xuất nào ở trên hardcode `{question_id: answer}` hay luật riêng 1 mã
  chứng khoán/1 câu; mục 1 và 2 ở "Việc cần làm" là sửa luật tổng quát (so sánh ngưỡng, và
  tái dùng module dùng chung).
