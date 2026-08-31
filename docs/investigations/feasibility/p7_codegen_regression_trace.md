# Trace qid 540 / 735 / 736: codegen divergence, 87dcb79 vs HEAD

## Vấn đề

Tiếp tục điều tra `docs/regression_bisect_2026-08-30.md` sau khi kết luận `1a01801`
bị debunk. Ba id còn lại có tín hiệu "sạch" (table_ids retrieved giống hệt nhau
giữa code cũ/mới) nhưng `codegen` sinh `pandas_query` khác nhau: **540, 735, 736**.
Câu hỏi: đây có phải một regression code cụ thể trong `solve/codegen/` hay
`modules/data/` không, hay là nhiễu sampling LLM (đã biết, temp=0.0 vẫn đổi ~10%
câu trả lời do vLLM continuous-batching non-associativity, `core/llm.py:44-45`)?

## Bước 1 — Diff toàn bộ code path build-prompt / evidence giữa 87dcb79 và HEAD

4 commit đụng `solve/codegen/`: `cacfab1`, `723620a`, `2dab3e4`, `35a313c`.
4 commit đụng `modules/data/`: `1d85b3e`, `2dab3e4`, `cdd6108`, `b5db5a6`.

| File | Diff 87dcb79→HEAD |
|---|---|
| `codegen/codegen.py` (`CODEGEN_SYSTEM`, `build_prompt`, `MAX_TOKENS`) | **Byte-identical text.** Diff chỉ là refactor thuần: rút `_agenerate_with_tools()` ra dùng chung với `screening.py` (cùng control flow, cùng biến). |
| `solve/common/context.py` (`table_context`, `_grid`, render bảng thành text) | +30 dòng: thêm `_mark_trailing_total_row()` — chỉ đổi NHÃN cột đầu tiên của **hàng cuối cùng** khi nhãn rỗng VÀ mọi ô còn lại là số. Không đụng tên cột, không đụng hàng giữa bảng. |
| `solve/common/columns.py` (`year_legend`) | 0 diff |
| `modules/data/table_store.py`, `modules/data/service.py` (`load_frame`, `ordered_table_names`) | 0 diff |
| `agents/finance/utils.py` (`slot_round_robin`, `year_round_robin`) | 0 diff |
| `solve/pipeline/evidence.py` (`codegen_budget`, `load_evidence`) | File mới (do `cacfab1` tách khỏi `graph.py`), nhưng **logic byte-identical** với bản cũ trong `graph.py` (so từng dòng, xem `/tmp/graph_old.py:116-171`). |
| `codegen/execute.py` (35a313c) | Chỉ đổi `as_magnitude()` (bỏ `between_two_companies()` khỏi việc ép abs) và thêm `_is_data_ratio`/`_already_scaled_to_percent`/percent-scaling trong `apply_units()`. Cả hai đều chạy **sau khi** `run_query` đã thực thi xong câu query thô — không thể là nguyên nhân model chọn sai tên cột hay ra `nan`. |
| `agents/finance/config.py` | Đổi format comment (dời qua `docs/config_flags.md`), nhưng mọi **giá trị default** liên quan (`codegen_thinking=False`, `codegen_tool_turns=0`, `codegen_show_grids=True`, `codegen_max_tables=3/5`, `screening_solver=False`, `max_repairs=2`, `selection_sub_tables=6`) giống hệt. |
| `modules/rag/judge.py` | 0 diff |
| `modules/rag/service.py` | Rút `_PRIMARY`/hợp nhất logic vào `candidates.add_primary_statements()` — cùng phép tính, đổi chỗ ở. |
| `agents/finance/understand.py` (`ba75239`) | Chỉ đổi cách suy `doc_type` (separate/consolidated override); không đụng `tickers`/`years`/`multi_year`. |

**Kết luận bước 1**: không có commit nào trong 87dcb79..HEAD thay đổi logic build-prompt,
render bảng, chọn/gán biến `dfN`, hay retrieval ranking theo cách có thể giải thích 3 id trên.
Ứng viên duy nhất còn lại là nhiễu LLM ở một trong các lời gọi (`understand`, `Judge.apick`,
hay chính `codegen.agenerate`) — không cái nào set `LLM_SEED`.

## Bước 2 — qid 540: harness trực tiếp, bỏ qua retrieve/Judge

`evidence_tables` (bảng thật sự nạp thành `df1/df2/df3`) trong `diag` của CẢ hai bản ghi thật
— `full1012_v17_unitfix.jsonl` / bisect 87dcb79 VÀ `full1012_v18_postfix.jsonl` (HEAD) —
**giống hệt nhau, cùng thứ tự**: `DCM_financial_statements_2020_consolidated|7` (df1),
`DPM_..._2019...|41` (df2), `DPM_..._2020...|43` (df3). (Ghi chú sửa lại phần groundwork
trước: `df1` KHÔNG phải `table_ids[0]`, mà là bảng có số thứ tự `|N` nhỏ nhất trong tập đã
chọn — `ordered_table_names()` sort theo hậu tố số, không theo rank retrieval.)

`load_frame('DCM_financial_statements_2020_consolidated|7')` (bảng thật, không phải bảng
DPM|41 mà groundwork trước đọc nhầm) có cột `['Unnamed: 0', 'CHỈ TIÊU', 'Mã số Thuyết minh',
'Năm nay', 'Năm trước', 'Unnamed: 5']` — đây là một bảng bị lỗi trích xuất header dịch cột
(header "Năm nay"/"Năm trước" lệch một cột so với data thật: cột "Năm nay" chứa số thuyết
minh (25, 26, 30, NaN...), cột "Unnamed: 5" mới là VND năm trước thật). Bug này tồn tại y hệt
ở cả hai bản (code load/repair header không đổi) — bảng nguồn tự nó mơ hồ, không phải do commit
nào gây ra.

Viết harness gọi thẳng `codegen.agenerate()` (bỏ qua `retrieve`/`Judge`, dùng đúng 3
`table_ids` cố định trên, `thinking=False, tool_turns=0, show_grids=True` — đúng config
production), chạy tại **HEAD**:

- 5 lần **tuần tự**: 5/5 ra query đúng kiểu cũ (`df1.iloc[2]["Unnamed: 5"] / ... * 100`).
- 15 lần **đồng thời** (`asyncio.gather`, mô phỏng batch thật của `run_graph.py`):
  **8/15 ra sai** (dùng `"Năm nay"`/`"Năm trước"` — đúng kiểu hallucination thấy trong
  `full1012_v18_postfix.jsonl`), 7/15 ra đúng. Ít nhất 4 biến thể query khác nhau xuất hiện,
  cùng một prompt, cùng code, cùng temperature=0.0.

Đây là bằng chứng trực tiếp: với input hoàn toàn giống hệt (không chỉ table_ids mà cả nội
dung bảng và code build-prompt), model tại HEAD tự nó không ổn định — khớp đúng với ghi chú
đã biết ở `core/llm.py:44-49` (batching non-associativity), và biểu hiện rõ hơn khi có
nhiều request chạy đồng thời (batch thật) so với chạy đơn lẻ tuần tự.

## Bước 3 — qid 736: bảng cuối dùng để build query giống hệt nhau

`table_ids` (danh sách retrieval thô) LỆCH giữa hai bản ghi thật ở đúng vị trí #7-8:
cũ `[..., VPI|10, VPI|6, CEO|8, ...]`, mới `[..., VPI|10, CEO|8, VPI|6, ...]` (hoán vị 2
phần tử liền kề). Nhưng `diag.evidence_tables` (tập bảng THỰC SỰ được cắt còn 3, nạp thành
`df1/df2/df3`) là **giống hệt nhau ở cả hai bản**: `CEO|4, CEO|22, VPI|37` — vị trí #7-8 nằm
NGOÀI ngưỡng cắt `codegen_max_tables=3`, nên hoán vị đó không ảnh hưởng gì tới biến `dfN`
codegen thấy. Vậy divergence của 736 (`df2.iloc[5]/df3.iloc[5]["Số cuối năm"]` cũ vs
`df1.iloc[32]/df2.iloc[5]` mới) xảy ra trên **cùng một bộ 3 bảng, cùng một prompt** — cùng
lớp nguyên nhân với 540: nhiễu sampling ở lời gọi `codegen.agenerate()`, không phải do thứ tự
`table_ids` đổi.

## Bước 4 — qid 735: khác biệt thật ở retrieval, nhưng không do code

`diag.evidence_tables` khác SỐ LƯỢNG giữa hai bản: cũ có 4 bảng (`OGC|34, OGC|6, ASM|34,
ASM|11`), mới chỉ có 3 (`OGC|34, OGC|6, ASM|11` — thiếu `ASM|34`). Vì `codegen_budget()`
(công thức chọn `max_tables`) không đổi (0 diff `utils.py`, logic `evidence.py` byte-identical
với bản cũ trong `graph.py`), số lượng bảng khác nhau chỉ có thể đến từ input của hàm đó:
`tickers`/`years`/`multi_year` do `understand()` gán — một lời gọi LLM riêng, không set
`LLM_SEED`, và commit duy nhất đụng `understand.py` giữa 87dcb79..HEAD (`ba75239`) chỉ sửa
cách suy `doc_type`, không đụng `tickers`/`years`/`multi_year`. Retrieval's `table_ids` thô
cũng lệch thứ tự ở đầu danh sách (`OGC|34` đứng đầu ở bản cũ, cuối danh sách ở bản mới) —
đúng dạng nhiễu đã ghi nhận ở `Judge.apick` (không set `LLM_SEED`), không phải một thay đổi
logic mới (`modules/rag/judge.py` 0 diff; `modules/rag/service.py`/`candidates.py` chỉ gộp
hàm trùng lặp, cùng phép tính).

## Kết luận

**(b) Nhiễu sampling LLM, không quy được về một commit cụ thể nào giữa 87dcb79 và HEAD.**

- Toàn bộ code build-prompt (`codegen.py`), render bảng (`context.py`, `columns.py`), nạp
  bảng (`table_store.py`, `service.py`), chọn/gán biến `dfN` (`evidence.py`, `utils.py`) đã
  được diff dòng-theo-dòng và xác nhận không đổi logic (chỉ đổi cách tổ chức file/comment,
  hoặc thêm một nhánh hẹp — `_mark_trailing_total_row` — không áp dụng cho các bảng liên quan
  ở đây).
- `35a313c` (commit của tôi, nghi ngờ ban đầu) chỉ chạm `as_magnitude`/`apply_units`, chạy SAU
  khi query thô đã thực thi thành công — không thể gây ra việc chọn sai cột hay `nan`.
- Với qid 540, harness gọi thẳng `codegen.agenerate()` tại HEAD, cùng 3 bảng/cùng nội dung/
  cùng prompt như bản ghi thật, tái hiện được CHÍNH XÁC cả hai kết quả (đúng và sai) chỉ bằng
  cách chạy nhiều request đồng thời ở temperature=0.0 — không cần đổi bất kỳ dòng code nào.
  Đây là bằng chứng trực tiếp, mạnh nhất trong toàn bộ điều tra.
- Với qid 736, tập bảng cuối cùng nạp cho codegen giống hệt nhau giữa hai bản — cùng lớp
  nguyên nhân với 540.
- Với qid 735, có khác biệt thật ở tầng retrieval (số bảng, thứ tự), nhưng quy được về các
  lời gọi LLM không set `LLM_SEED` ở `understand()`/`Judge.apick` (không đổi code giữa
  87dcb79..HEAD), không phải một thay đổi logic.

Không đề xuất fix cho chính hiện tượng nhiễu này (nó là thuộc tính cố hữu của decode
temperature=0 dưới continuous batching của vLLM + không set seed toàn hệ thống — set
`LLM_SEED` sẽ làm một lần chạy dễ tái lập hơn nhưng không tăng tỷ lệ đúng, vì seed cố định
một trong nhiều mẫu, không chọn mẫu đúng). Một hướng cải thiện thật (ngoài phạm vi regression
này) là sửa `repair_shifted_bank_header`/`repair_group_leaf_header` (`modules/data/`) để tự
sửa header bị lệch cột kiểu bảng `DCM...|7` ở trên, thay vì để model tự đoán giữa hai tên cột
gây hiểu lầm — đây là một cải tiến chất lượng dữ liệu, không phải root cause của regression
0.3992 → 0.3439.

## Dữ liệu / script

- Harness: `/tmp/probe_qid540.py` (tuần tự), `/tmp/probe_qid540_concurrent.py` (đồng thời) —
  không lưu trong repo, chạy bằng `PYTHONPATH=src .venv_bge/bin/python <script> <n>`.
- Worktree `/home/ding/ai-finance-bisect-87dcb79` KHÔNG bị đổi trạng thái trong phiên này (chỉ
  đọc `git show`, không checkout thêm commit nào) — vẫn ở `87dcb79` như trước.
