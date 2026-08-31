# Phương án 3: đưa bước `plan` liệt kê tuple trước retrieval — đánh giá khả thi

Điều tra read-only, không sửa code. Dữ liệu đo được lấy từ
`artifacts/runs/gold73_qwen35_planner.jsonl`, `data/metadata/questions_enriched.jsonl`
(1.012 câu, sinh từ `scripts/enrich_questions.py`), và đọc trực tiếp
`src/finance_qa/agents/finance/*`, `src/finance_qa/modules/solve/*`,
`src/finance_qa/modules/rag/*`, `/home/ding/ai-finance-stage-2-refactor/SPEC.md`.

## Kết luận

**Không khả thi ở dạng được đề xuất trong SPEC.md §8.1 (`resolve → plan → retrieve theo
từng tuple → solve`), và cũng không cần thiết**, vì lý do kỹ thuật cụ thể (xem "Luồng hiện
tại"): repo chính đã resolve toàn bộ tổ hợp (mã, năm) cần thiết **một lần, tất định, trước
khi ranking chạy** (`filters.py::shortlist`, tích chéo mã × năm) — đây chính là việc mà
`resolve/docselect.py` của repo refactor làm, chỉ khác là nó nằm ở tầng lọc cứng của repo
chính chứ không phải một bước `plan` riêng. Nút nghẽn thật không phải "retrieve chưa biết
cần tuple nào", mà là **hai lần cắt sau đó**: judge/reranker cắt shortlist xuống `table_ids`,
rồi `generate_pandas` cắt tiếp xuống 3-5 bảng (`codegen_max_tables`). Thêm một bước `plan`
chạy trước retrieve sẽ làm lại việc `shortlist()` đã làm miễn phí.

Trần lợi ích đo được trên bộ 73 câu gold: trong 10 câu "có bảng gold mà vẫn sai", chỉ
**3 câu (488, 502, 542)** thật sự thiếu tuple trong evidence do cỡ cắt (`codegen_max_tables`)
quá nhỏ so với số tuple cần — đây là loại lỗi một bước plan-trước-retrieve (hoặc rẻ hơn:
nới cỡ cắt) có thể sửa. **5 câu (526, 555, 878, 946, 974) đã có đủ tuple trong evidence mà
vẫn sai** — lỗi nằm ở suy luận sau khi có bảng (chọn dòng, lọc điều kiện, argmax nhiều bảng),
không phải ở retrieval, nên một bước plan-trước-retrieve không giúp gì cho 5 câu này. 2 câu
còn lại (685, 790) không phải câu nhiều tuple. Vậy **trần lý thuyết là 3/73**, so với sàn
nhiễu 2 câu — nghĩa là một bản vá hoàn hảo cho đúng lớp lỗi này chỉ nhích điểm ròng khoảng
**1 câu** cao hơn nhiễu. Không đủ để biện minh một thay đổi kiến trúc retrieve N lượt.

**Nên cắt nhỏ, và bản cắt nhỏ hợp lý không giống ý tưởng gốc**: không phải "retrieve nhiều
lượt", mà là mở rộng cơ chế `year_round_robin` đã có (`utils.py`, dùng ở `graph.py:139-141`)
thành round-robin theo *mọi* tuple (mã, năm) câu hỏi nêu ra, và nâng `codegen_max_tables`/
`codegen_max_tables_multi_year` theo số tuple thay vì hằng số 3/5 cố định — sửa một hàm
trong `generate_pandas`, không thêm node, không thêm lượt gọi retrieval/reranker/LLM nào.
Việc này đo được trực tiếp trên 3 câu 488/502/542 mà không cần nộp bài.

Cơ chế gần nhất với "plan" đã tồn tại và đã đo: `solvers/decompose.py` (`SelectionPlan`,
`axis_of`, `aplan`) fan-out một câu hỏi chọn-lọc ra N câu con theo trục năm/mã — nhưng nó
chạy **sau** retrieval (dùng lại `table_ids` đã có, không retrieve lại) và cờ
`selection_decompose` mặc định `False` vì đã đo: 3/34 đúng trên nhóm nó nhắm tới (không hơn
baseline 2-3), và làm rớt 60 câu còn lại từ 40/39 xuống 37 khi bật. Đây là bằng chứng trực
tiếp rằng "liệt kê tuple explicit" không phải chỗ hệ thống đang thiếu điểm — suy luận trên
nhiều bảng sau khi có bảng mới là chỗ thiếu, và cơ chế plan hiện có chưa giải được nó.

*(Cập nhật 2026-08-21: team lead đo lại độc lập và yêu cầu đối chiếu 3 điểm cụ thể. Kết quả ở
mục "Đối chiếu với số đo bổ sung của team-lead" bên dưới **hạ trần lợi ích của Kết luận trên
xuống 0/73** — giữ nguyên văn Kết luận gốc để đối chiếu, không xoá.)*

## Đối chiếu với số đo bổ sung của team-lead (2026-08-21)

Team lead đo độc lập trên cùng artifact: `table_ids` (trước cắt) trung vị 14 bảng (max 84, mean
18.2), `evidence_tables` (sau `generate_pandas` cắt) trung vị 3 (max 5, mean 2.7), và **cắt xảy
ra ở toàn bộ 73/73 câu** — 23 câu dừng đúng ở 3 bảng, 20 câu dừng đúng ở 5 (43/73 sát ranh cắt).
Số này không mâu thuẫn với "Luồng hiện tại" ở dưới, nhưng tự nó không nói được cắt có **gây
sai** cho câu nào hay không — phải kiểm từng câu, làm ở mục (1).

### (1) Ba câu 488/502/542: tuple thiếu có nằm trong `table_ids` (trước cắt) không?

Xác nhận trước bằng đọc code: `generate_pandas` đọc `state["table_ids"]` ở `graph.py:136` nhưng
**không** viết lại khoá `table_ids` trong dict trả về — nó chỉ trả `evidence_tables` (danh sách
đã cắt/đã nạp, `graph.py:144-203`). Vậy `table_ids` trong artifact là danh sách retrieval đầy
đủ (trước cắt), `diag.evidence_tables` là danh sách đã cắt (đưa vào prompt) — đúng cặp cần so.

- **502** — cần 6 năm PLX (2015/2016/2018/2019/2020/2021). `table_ids` (45 bảng) **có đủ cả 6
  năm**, riêng 2021 xuất hiện 8 lần (`PLX_..._2021_separate|39, |8, |6, |10, |9, |7, |4, |5`).
  `evidence_tables` (5 bảng, `codegen_max_tables_multi_year=5` + `year_round_robin`) chỉ giữ
  2015/2016/2018/2019/2020 — mất đúng 2021. **Lỗi cắt thật**: 6 năm cần thiết không thể vừa 5
  chỗ, bất kể round-robin sắp thế nào (`item.multi_year=True`, `item.multi_company=False`).
- **488** — cần 4 mã AAA/DPM/DCM/GVR năm 2016 (`item.multi_year=False`, `item.multi_company=True`
  → `codegen_max_tables=3`, không có round-robin theo mã). `table_ids` (23 bảng) **có** GVR
  (`GVR_..._2016_consolidated|9`, xếp hạng 4, ngay sau top-3). `evidence_tables` (3 bảng) chỉ
  giữ AAA/DPM/DCM. **Lỗi cắt thật**, và lộ đúng lỗ hổng đã ghi ở "Luồng hiện tại": có round-robin
  theo năm, không có round-robin theo mã.
- **542** — cần DCM/DPM/GVR/"Tân Bình" hai năm 2021-2022. Bảng gold thật (theo
  `data/eval/unbiased60_gold.jsonl`, note của người gán nhãn) chỉ dùng
  `DCM_2021|4, DCM_2022|6, DPM_2021|8, DPM_2022|9` — GVR bị loại đúng theo điều kiện câu hỏi
  (tăng trưởng doanh thu), và **"Tân Bình" (mã TIX) hoàn toàn không có trong corpus** — không có
  trong `ViFinQA/code_stock.csv`, không khớp bất kỳ đường dẫn dữ liệu nào (đã kiểm bằng
  `grep`/`find`); note gold ghi rõ "TIX HOÀN TOÀN KHÔNG có trong corpus". Đây không phải lỗi
  resolve hay retrieval, mà là lỗ hổng corpus không sửa được bằng plan/cắt/lookup nào.
  `table_ids` (42 bảng) có `DCM_2021|4`, nhưng `evidence_tables` (5 bảng) thiếu đúng nó — cũng
  là lỗi cắt xét riêng bảng đó, nhưng vô nghĩa với câu hỏi vì TIX là hố dữ liệu không sửa được.

**Nhưng cả 3 câu có một vấn đề nghiêm trọng hơn, đọc trực tiếp từ `diag.verify.reason` (lý do
sai do `verify_answer` tự chấm, không phải suy diễn thêm):**

- 488: `pandas_query` = `((df1.iloc[2]/df1.iloc[18]) > 0.1) * 1e-12` — chỉ tính tỉ lệ LNST/DTT
  của **một mình AAA**, không lặp qua 4 mã, không cộng DTT của các mã thoả điều kiện.
  `verify.reason`: "chỉ kiểm tra điều kiện này cho công ty AAA và không tính tổng doanh thu của
  các công ty thỏa mãn".
- 502: `pandas_query` = `df1.iloc[6]["2016VND"]` — một ô cố định ở bảng Thuyết minh 4, không
  phải kết quả so 6 năm để tìm năm có quỹ lớn nhất rồi tra "lãi dự thu" của năm đó.
  `verify.reason`: "yêu cầu số dư lãi dự thu cuối năm của công ty mẹ, nhưng truy vấn lại lấy số
  dư... từ bảng Thuyết minh 4".
- 542: `pandas_query` chỉ đọc **một bảng** `df3` với chỉ số dòng sai. `verify.reason`: "chỉ lấy
  doanh thu thuần (hàng 2) và doanh thu bán hàng (hàng 0)... thiếu giá trị lợi nhuận gộp (hàng
  4)" — không đề cập, không chạm tới DCM/DPM hay phép trung bình 2 công ty nào.

Không câu nào trong 3 câu có `verify.reason` nói "thiếu bảng". Cả 3 dừng ở một expression
một-bảng/một-dòng, chưa từng thử logic nhiều tuple (lặp qua mã, so 6 năm, trung bình 2 công ty)
— đúng loại lỗi `selection_decompose` đã chẩn đoán (`config.py:318-321`): "even those hand the
model a job one expression cannot hold". Vì vậy **không có bằng chứng trực tiếp rằng đưa đúng
bảng bị cắt vào tầm nhìn của model sẽ sửa được 1 trong 3 câu này** — đo được là bảng bị cắt tồn
tại, không đo được nó là nguyên nhân duy nhất khiến câu trả lời sai.

**Sửa lại trần lợi ích của Kết luận gốc**: 3/73 vẫn đúng ở nghĩa "loại lỗi bảng-bị-cắt tồn tại
đúng như mô tả". Nhưng trần *đo được* của việc "chỉ nới cỡ cắt" — dựa trên `verify.reason` của
chính 3 câu đó — phải hạ xuống: **không câu nào trong 3 câu được xác nhận sẽ đúng nếu chỉ nới cỡ
cắt**, vì cả 3 sai ở bước viết query nhiều tuple trước khi chạm giới hạn bảng. Trần *đo được,
không suy diễn* của phương án cắt-nhỏ ban đầu là **0/73** — dưới sàn nhiễu 2 câu, tức không phân
biệt được với nhiễu bằng dữ liệu hiện có. Con số 3/73 sai nếu dùng làm ước lượng lợi ích điểm số.

### (2) Đối chiếu với 42%/44%/44% và nhóm 196 câu (`config.py:212-220`)

Số của team lead đo trên nhóm 196 câu "nêu khoảng thời gian" (ví dụ "2016-2020"), khác nhóm 3
câu ở mục (1) (502 nêu 6 năm rời rạc, không phải một khoảng; 488/542 không thuộc nhóm này). Hai
phép đo trên hai nhóm khác nhau, không mâu thuẫn, nhưng bổ sung theo hướng xấu hơn cho phương án
cắt-nhỏ:

- **19% của 196 câu** có đủ năm cần thiết trong `evidence_tables` ở cap hiện tại
  (`codegen_max_tables_multi_year=5`), và nhóm này đạt **2/34 đúng trên gold** so với **37/60**
  của các câu còn lại — một hố sâu và khu trú thật, khác với hố 8,4% ("≥2 mã và ≥2 năm") ở mục
  "Kích thước bài toán" vốn đo trên tiêu chí khác (số mã/năm nêu ra, không phải độ dài khoảng).
- Nới cap 5 → 12 → toàn bộ `table_ids` ("whole pool", **không phải** shortlist ~106 bảng) chỉ
  nâng tỉ lệ có đủ năm 42% → 44% → 44% — **chững lại ngay cả khi bỏ cap hoàn toàn**. Điều này
  xác nhận nghi ngờ của team lead: với nhóm 196 câu, phần lớn thiếu hụt (44%→100%, tức 56 điểm
  phần trăm) nằm ở **`table_ids` chính nó** (judge/retrieval không mang năm đó về), không phải
  ở cỡ cắt — cỡ cắt chỉ chịu trách nhiệm cho phần chênh giữa cap hiện tại (42%) và trần của pool
  đã retrieve (44%), khoảng **2 điểm phần trăm** trên nhóm này.
- 502 (mục 1) là trường hợp hiếm hơn: `table_ids` có đủ cả 6 năm, cap=5 là nguyên nhân cắt duy
  nhất, không phải lỗi pool — không suy tổng quát từ 502 sang cả nhóm 196 câu được, vì phần lớn
  nhóm này thiếu ngay ở tầng retrieval, không phải ở cap.
- **Kết luận đối chiếu**: nới cỡ cắt (kể cả nới theo tuple) chỉ chạm tới phần "cỡ cắt" của thiếu
  hụt (~2 điểm phần trăm trên nhóm 196 câu), không chạm tới phần "pool" (~56 điểm phần trăm).
  Phần pool cần sửa ở retrieval (nhiều lượt hơn, backend khác, hard filter khác) — đúng loại
  thay đổi tốn tiền reranker/LLM mà phương án 3 gốc muốn tránh, nhưng không tránh được nếu muốn
  đóng phần lớn hơn của khoảng trống này.

### (3) `lookup.py` (`find_rows`) — có phải câu trả lời đã chọn?

Đọc `src/finance_qa/modules/solve/common/lookup.py:1-21`: đúng như team lead mô tả — mục tiêu
công khai của `find_rows` là "reach the other ~103 tables by name, one lookup at a time, paying
prompt budget only for the rows that come back", vì `codegen_max_tables=3` là hằng số đã đo (nâng
lên 10 làm điểm tệ hơn, 33→29, `config.py:202-210`).

Nhưng đây **không phải một hướng chưa kiểm chứng** — nó đã được xây, bật thử, và đo, qua cờ
`codegen_tool_turns` (`config.py:274-293`, mặc định `0`, đọc từ `SOLVE_TOOL_TURNS`):

- Trên 94 câu gold: bật loop (3 turns) đạt 43, hai baseline không bật đạt 42/42 — trong sàn
  nhiễu.
- **Trực tiếp trên nhóm liên quan nhất**: "6 câu có bảng gold bị cắt bởi table cap ở baseline
  giữ nguyên hệt cũ (4 sai, 3 trong đó sai dù đã dùng hết cả 3 lượt lookup)" (`config.py:284-286`)
  — đúng cơ chế team lead đề xuất, đo trực tiếp trên đúng loại câu (bảng bị cắt bởi cap), và
  **0/6 được sửa**.
- `find_rows` tự nó "hoạt động" (72% lượt lookup trả về dòng), nhưng 30/46 câu hết ngân sách
  lookup thuộc lớp argmax/median tìm ratio suy dẫn — nhãn dòng không tồn tại trong bảng — nên tra
  theo tên nhãn "là công cụ sai" cho lớp đó (`config.py:288-292`).
- Đã đo cả `codegen_show_grids=False` (ẩn lưới, buộc chỉ dùng `find_rows` để đọc số) — tệ hơn
  nhiều: 25/94 so với 42 (`config.py:301-310`).

Đối chiếu với 3 câu 488/502/542: cả ba dừng ở một expression một-bảng/một-dòng mà **không hề gọi
`find_rows`** trong lần chạy đang xét (`diag.tool_calls` của 542 là `[]`; `codegen_tool_turns`
mặc định 0 nên `find_rows` không được cấp cho cả 3 câu trong artifact này) — nhất quán với giả
thuyết: lỗi ở đây không phải "model biết thiếu và cố tìm nhưng hết ngân sách", mà là "model chưa
từng thử tra thêm bảng nào khác".

**Kết luận mục (3): không nên chọn "mở rộng đường lookup theo tên" làm bản cắt nhỏ.** Cơ chế đã
tồn tại, đã đo, và phần đo trực tiếp nhất (đúng nhóm "bảng gold bị cắt bởi cap") cho 0/6 — khớp
với việc 3 câu tôi kiểm cũng không có bằng chứng lookup sẽ giúp.

### Trần lợi ích và bản cắt nhỏ cuối cùng, sau hiệu chỉnh

- Trần lợi ích đo được, sau khi đối chiếu `verify.reason` từng câu: **0/73 câu được xác nhận sẽ
  đúng nếu chỉ nới cỡ cắt hoặc chỉ mở rộng lookup** — cả hai bản cắt nhỏ (note gốc, và gợi ý của
  team lead) nhắm đúng loại lỗi ("bảng cần thiết bị cắt") mà cả 3 câu mẫu đều có, nhưng lý do sai
  đã chấm của cả 3 câu không phải "thiếu bảng" mà "chưa viết đúng expression nhiều tuple" — sửa
  cắt hoặc lookup không có cơ sở đo được để cho là sẽ đổi kết quả. Trần 3/73 (~1 câu ròng trên
  nhiễu) ở Kết luận gốc **hạ xuống 0/73 (dưới sàn nhiễu, không phân biệt được với nhiễu)** theo
  bằng chứng hiện có.
- Nhóm 196 câu "nêu khoảng thời gian" cho thấy hố lớn nhất (2/34 so với 37/60) chủ yếu nằm ở
  **retrieval pool** (trần 44% dù bỏ cap hoàn toàn), không phải cỡ cắt (42%→44%, chênh 2 điểm) —
  nới cỡ cắt kể cả làm đúng cũng chỉ đóng được phần rất nhỏ của hố này.
- **Không còn bản cắt nhỏ nào (nới cap, round-robin theo tuple, hay mở rộng lookup) có ceiling
  đo được vượt sàn nhiễu 2 câu trên bộ 73, dựa trên artifact hiện có.**
- Khuyến nghị: **không đầu tư thêm cho phương án 3 hay các bản cắt nhỏ của nó trong 4 ngày còn
  lại** — không phải vì kiến trúc sai, mà vì không có bằng chứng nó chạm đúng nguyên nhân lỗi đã
  chẩn đoán. Nếu muốn một số đo dứt điểm: cách rẻ nhất là chạy `scripts/score_gold75.py` một lần
  với cap nới theo tuple, áp riêng cho 502 (câu duy nhất trong 3 có bằng chứng thuần lỗi cắt,
  không lẫn hố dữ liệu như 542 hay lỗi suy luận rõ như 488), và xem `verify` có đổi thành đúng
  hay không. Đây là bước tốn tiền LLM ở mức 1 câu — **cần team lead cho phép trước khi chạy**, vì
  vượt ra ngoài phạm vi "chỉ đo trên artifact có sẵn" đã giao cho lượt điều tra này.

## Luồng hiện tại

**Retrieval chạy đúng một lượt cho mỗi câu, không bao giờ retrieve lại theo tuple** — kể cả
khi `selection_decompose` (fan-out) được bật.

- Entry point: `understand → retrieve → trace_capabilities → (chuỗi solver hẹp) →
  generate_pandas/solve_selection → execute_and_repair → verify_answer → profile_validate`
  (`src/finance_qa/agents/finance/graph.py:1079-1091`).
- `understand` (`src/finance_qa/agents/finance/understand.py:113-161`) suy `tickers`/`years`/
  `doc_type`/`metric`/`operation` cho **cả câu hỏi**, một lần, bằng regex tất định
  (`find_tickers`, `find_years` — `modules/data/preprocessing/questions.py:148-212`) cộng
  một lời gọi LLM cho các trường không tất định (metric/operation/answer_shape). Không có
  bước liệt kê tuple riêng ở đây; `years`/`tickers` là danh sách phẳng cho toàn câu.
- `retrieve` (`agents/finance/retrieve.py:12-31`) gọi đúng một lần
  `aretrieve_table_ids(...)` (`modules/rag/service.py:93-144`), nhận `tickers`/`years` của
  *toàn câu* làm hard filter, trả về `table_ids` (danh sách bảng đã chấm điểm) và `shortlist`
  (mọi bảng qua được hard filter, trung vị ~106 bảng — dòng 111-113 của `service.py`). Đây là
  lượt retrieval duy nhất trong toàn graph.
- Chuỗi solver hẹp (`cell_locator` → `formula_facts` → `raw_table_linker` →
  `selection_facts` → `raw_selection_linker` → `structured_facts`, định nghĩa ở
  `graph.py:1009-1016`) đều tiêu thụ `table_ids` đã có từ bước trên, không gọi lại
  `aretrieve_table_ids`.
- `solve_selection` (`graph.py:311-420`, dùng `decompose.py`) — nhánh gần nhất với "plan" —
  cũng **không retrieve lại**: nó gọi `tables_for(table_ids, axis, element)`
  (`decompose.py:199-208`), tức là *lọc lại* danh sách `table_ids` đã retrieve một lần theo
  từng phần tử của trục (năm hoặc mã), không phải gọi retrieval service thêm lần nào. Chi phí
  thêm duy nhất là N lệnh codegen con (`agenerate`/`aexecute`) cho N phần tử, không phải N lượt
  retrieval/reranker.
- `generate_pandas` (`graph.py:134-205`) là nơi cắt cuối cùng: lấy đầu `table_ids`, giới hạn
  `codegen_max_tables` (=3) hoặc `codegen_max_tables_multi_year` (=5, có `year_round_robin`
  interleave theo năm — `graph.py:139-141`, `config.py:211-221`). Đây là cỡ cắt gây thiếu
  tuple cho 3/10 câu nêu ở phần Kết luận.

Vậy: hard filter (`filters.py::shortlist`, tương đương `resolve/docselect.py` của repo
refactor) đã ghép **mọi tổ hợp (mã, năm)** câu hỏi nêu ra thành ứng viên **một lần, trước cả
khi có ranking** — đúng nguyên lý "liệt kê tuple trước" mà SPEC.md §8.1 muốn, chỉ khác là nó
nằm sẵn trong hard filter của retrieval hiện tại chứ không phải một node `plan` tách riêng.
Cái duy nhất chưa tất định là hai lần cắt sau nó (judge picks, rồi `codegen_max_tables`).

## `decompose.py` đã làm được đến đâu

`decompose.py` **là** một bộ lập kế hoạch tuple-liệt-kê, nhưng phạm vi hẹp hơn SPEC.md §8.1
đáng kể theo hai chiều:

1. **Chỉ với câu có marker so sánh rõ ràng.** `axis_of` (`decompose.py:136-161`) chỉ kích
   hoạt khi câu chứa một trong 8 marker (`cao nhất`, `thấp nhất`, `lớn nhất`, `nhỏ nhất`,
   `nhiều nhất`, `ít nhất`, `trung vị`, `vượt` — `decompose.py:48-51`) **và** trục (năm hoặc
   mã) có ≥2 phần tử. Không có nhánh cho `CONDITIONAL` thật (lọc theo điều kiện trên toàn
   nhóm rồi mới argmax) trừ trường hợp có `filter_metric` trong `SelectionPlan`
   (`decompose.py:79-91`) — cái này tồn tại và được `pick()` áp dụng (`decompose.py:280-304`),
   nên về mặt schema nó **có** che được lớp CONDITIONAL của SPEC (id 417/421/429/431 dạng đó),
   nhưng chưa từng được đo riêng cho lớp đó.
2. **Nó liệt kê tuple sau retrieval, không trước.** `aplan` (`decompose.py:316-331`) chỉ sinh
   ba mẫu câu hỏi con (rank/filter/answer) bằng LLM — không sinh ra tuple mới, tuple đã có sẵn
   từ `years`/`tickers` của `understand`. Việc "liệt kê tuple" nằm ở `axis_of` +
   `tables_for`, cả hai đều thuần Python, không gọi LLM, không gọi lại retrieval.

Đã được gọi ở đâu, giai đoạn nào, có bật mặc định không:
- Gọi tại `graph.py:344` (`plan = await aplan(...)`) trong `make_solve_selection`, và định
  tuyến vào nhánh này qua `selection_route` (`graph.py:983-995`) — nhánh dự phòng cuối cùng
  của `SOLVER_CHAIN`, chạy sau toàn bộ 6 solver hẹp đã bỏ qua câu hỏi.
- Cờ `selection_decompose` mặc định **`False`** (`config.py:347`, đọc từ env
  `SOLVE_DECOMPOSE`). Lý do ghi ngay trong comment (`config.py:312-346`, cũng lặp lại trong
  docstring đầu `decompose.py:1-30`): đo trên 94 câu gold, kích hoạt 34/94, hoàn tất 30/34,
  chỉ đúng **3/34** (băng nhiễu là 2-3 của baseline) — không vượt ngưỡng ≥8 đề ra trước khi
  đo — và **guardrail vỡ**: 60 câu không vào nhánh này tụt từ 40/39 xuống 37 khi bật (nghi là
  nondeterminism của server, nhưng chưa xác nhận, và default vẫn giữ False).
- Nguyên nhân lỗi đã chẩn đoán sẵn trong docstring: không phải do ranking (28/31 câu có đủ
  mọi phần tử trục trong `table_ids` đã submit) mà do **bước đọc cuối cùng tại phần tử thắng**
  — vẫn là một expression codegen suy dẫn ratio, vẫn sai với cùng tỷ lệ như baseline không
  fan-out. Tức: liệt kê tuple xong không tự động giải được bài toán suy luận nhiều bảng.

Kết luận cho phần này: **phương án 3 không phải xây mới từ đầu — nó đã tồn tại ở dạng hẹp,
đã được đo, và đã bị tắt vì không cải thiện điểm trong khi có rủi ro rớt điểm ở phần không
liên quan.** Mở rộng nó (thêm nhánh CONDITIONAL, đưa lên trước retrieval) là công việc thật,
nhưng bằng chứng hiện có cho thấy nút nghẽn không nằm ở việc thiếu liệt kê tuple.

## Kích thước bài toán, đo trên 1.012 câu

Đo thô bằng regex trên `data/metadata/questions_enriched.jsonl` (đã có sẵn `tickers`/`years`
tất định từ `enrich_questions.py`, không dùng LLM):

| Tiêu chí | Số câu | Tỉ lệ |
|---|---|---|
| ≥2 mã CK | 310 | 30,6% |
| ≥2 năm | 356 | 35,2% |
| **cả ≥2 mã và ≥2 năm** | **85** | **8,4%** |
| chứa từ khoá so sánh/điều kiện (`cao nhất`, `thấp nhất`, `lớn nhất`, `nhỏ nhất`, `nhiều nhất`, `ít nhất`, `trung bình`, `trung vị`, `tổng`, `trong nhóm`, `trong số`, `trong các`, `so với`, `vượt`, `năm nào`) | 627 | 61,9% |
| ≥2 mã HOẶC ≥2 năm HOẶC từ khoá trên | 740 | 73,1% |
| không nhận ra mã CK nào | 1 | 0,1% |
| không nhận ra năm nào | 1 | 0,1% |

Đây là **đo thô**, không khớp trực tiếp với phân tầng độ khó của BTC:
- Số "cả ≥2 mã và ≥2 năm" (85/1.012 = 8,4%) khá gần con số 73 mà repo refactor đo được bằng
  `resolve/company.py` + `resolve/period.py` (khác biệt do phương pháp trích xuất khác — repo
  refactor có xử lý riêng phạm vi/đa bản mà bộ enrich của repo chính không có).
- Số "có từ khoá so sánh/điều kiện" (627, 61,9%) **cao hơn nhiều** so với Intermediate+Hard
  của BTC (200+216=416/1.012=41,1%), vì danh sách từ khoá bắt cả câu dễ (ví dụ "tổng tài sản"
  là một dòng có sẵn, không phải phép tổng nhiều ô; "so với năm trước" đôi khi chỉ là 1 phép
  trừ 2 ô cùng bảng). Từ khoá không phân biệt được "nhiều ô cần multi-hop thật" với "một dòng
  có tên chứa từ đó".
- Không có cách tất định nào trong repo chính hiện tại để tái tạo đúng ranh giới
  Easy/Medium/Intermediate/Hard của BTC (định nghĩa Hard là *multi-hop phụ thuộc*, một khái
  niệm ngữ nghĩa, không phải đếm mã/năm). Không đo được khoảng cách giữa 41,1% (BTC) và 73,1%
  (đo thô) bằng dữ liệu hiện có — nói rõ đây là **không biết**, không suy diễn thêm.

## Việc cần làm, ước lượng

Phiên bản đầy đủ theo SPEC.md §8.1 (`resolve → plan → retrieve theo tuple → solve`) **không
được đề xuất** — lý do đã nêu ở Kết luận: retrieval hiện tại đã resolve tuple một lần tất
định trong hard filter, nên "retrieve theo từng tuple" sẽ lặp lại việc đó và nhân chi phí
reranker/judge (mỗi câu multi-hop hiện tốn 1 lượt gọi reranker + 1 lượt gọi judge; retrieve
theo N tuple sẽ tốn N lượt của cả hai — tốn tiền thật, đúng loại chi phí ràng buộc cấm chạy
gate cho biết).

Bản **cắt nhỏ được đo** (khuyến nghị thay thế, xem thêm mục dưới):

1. **Mở rộng `year_round_robin` (`utils.py`) thành round-robin theo tuple (mã, năm) đầy đủ**,
   dùng trong `generate_pandas` (`graph.py:136-144`). Hiện chỉ round-robin theo năm khi
   `multi_year`; không có nhánh tương tự cho `multi_company` một-năm (q488, cap vẫn = 3) hay
   cho tổ hợp mã×năm (q542).
   Verify: chạy lại 3 câu 488/502/542 qua `generate_pandas` với slice mới (không cần chạy cả
   graph, có thể test đơn vị bằng cách gọi hàm slice trực tiếp với `table_ids` đã lưu trong
   `evidence_tables` cũ + `shortlist`), kiểm tra mọi tuple câu hỏi nêu có ≥1 bảng trong slice.
   Không cần gọi LLM/reranker để verify bước này — chỉ là logic Python.
2. **Đo lại bằng `scripts/score_gold75.py` trên 73 câu**, một lần, để xem điểm còn thay đổi
   nằm trong hay ngoài sàn nhiễu 2 câu. Đây là bước duy nhất cần chạy pipeline thật (tốn tiền
   LLM ở mức bình thường của 1 lần chạy 73 câu, không phải gate mở rộng).
3. **Không làm gì thêm cho 5 câu "đã đủ tuple mà vẫn sai"** trong ngân sách 4 ngày còn lại —
   bằng chứng hiện có (`selection_decompose` đo được 3/34) cho thấy đây là bài toán suy luận
   nhiều bảng chưa có cách giải đã biết, rủi ro cao, lợi ích không chắc, và có tiền lệ làm rớt
   điểm chỗ khác khi đụng vào.

Nếu vẫn muốn thử bản đầy đủ (plan trước retrieve cho câu CONDITIONAL thật), chi phí ước lượng:
- Sửa `understand` để phân loại thêm nhãn CONDITIONAL/nhóm-điều-kiện (hiện chưa có trường nào
  giữ "nhóm công ty cần lọc").
- Thêm một bước sinh tuple (mã, năm) từ nhóm đó *trước* khi gọi `aretrieve_table_ids`, rồi gọi
  retrieval N lần (N = số tuple) hoặc gọi hard filter N lần + 1 lượt judge trên hợp các ứng
  viên — cả hai đều đổi kiến trúc `retrieve.py`/`graph.py` (thêm node, đổi cạnh, đổi state).
  Đây chính là phần lớn nhất trong 4 phương án theo mô tả của việc này, và với trần lợi ích đo
  được là ~1 câu ròng trên 73, **không cân xứng với 4 ngày còn lại.**

## Phương án thay thế rẻ hơn

- **Nới `codegen_max_tables`/`codegen_max_tables_multi_year` theo số tuple thực tế của câu**
  (mục 1 ở trên) — đã đo hướng tới ceiling 3/73, không cần node mới, không tốn thêm lượt
  reranker/LLM, verify được bằng script tạm không cần gate.
- **Solver tự yêu cầu thêm bảng khi thiếu** (như team lead gợi ý): các solver hẹp
  (`raw_table_linker`, `cell_locator`, ...) đã có sẵn `shortlist` (mọi bảng qua hard filter,
  ~106 bảng, giữ tỉ lệ chứa gold table 60/60 trên 60 câu cell-truth theo comment
  `service.py:111-113`) nhưng `generate_pandas` không dùng `shortlist` để bù khi
  `table_ids` thiếu tuple — nó chỉ cắt từ `table_ids`. Một điều kiện nhỏ "nếu thiếu bảng của
  một tuple đã biết, lấy thêm từ `shortlist`" rẻ hơn cả mục 1, nhưng không tổng quát bằng vì
  cần biết trước danh sách tuple để so khớp — tức vẫn cần một dạng liệt kê tuple tối thiểu,
  chỉ khác là dùng nó để *bù* thay vì *định tuyến lại retrieval*.
- Cả hai phương án trên giữ nguyên **một lượt retrieval/reranker/judge cho mỗi câu**, khác
  biệt duy nhất với hiện trạng là logic cắt/bù ở `generate_pandas`.

## Rủi ro và điều chưa biết

- **Chưa biết** ranh giới thật của Intermediate/Hard theo định nghĩa BTC trên 1.012 câu —
  chỉ có đo thô bằng từ khoá/số mã/số năm, sai lệch với 41,1% của BTC theo hướng phóng đại.
- **Chưa đo** liệu nới cỡ cắt (mục 1) có gây tác dụng phụ trên các câu khác đang đúng (giống
  cách `codegen_max_tables` từ 3 lên 10 đã đo là *tệ hơn* trên baseline — comment
  `config.py:202-210`: nhiều bảng hơn không đồng nghĩa đúng hơn, vì bảng gần-trùng lặp gây
  nhầm cột). Nới có điều kiện (chỉ khi thiếu tuple) khác với nới toàn cục đã đo tệ, nhưng chưa
  có số đo riêng cho biến thể có điều kiện này.
- **Chưa biết** liệu 5 câu "đủ tuple mà vẫn sai" có chung nguyên nhân suy luận hay mỗi câu một
  kiểu — không đủ dữ liệu (5 câu) để tổng quát hoá thành một sửa lỗi chung mà không phạm luật
  cấm sửa riêng cho từng câu.
- Repo refactor (`SPEC.md` §8.1) chỉ trưng ra 4 câu (417, 421, 429, 431) làm ví dụ
  CONDITIONAL trong bộ dev 118 câu của họ, và module C (`solve/`) của họ **chưa có code, chỉ
  có đặc tả** — không có số đo độc lập nào từ repo đó chứng minh kiến trúc "plan trước
  retrieve" thực sự cải thiện điểm; đó vẫn là một giả thuyết chưa kiểm chứng ở cả hai repo.
