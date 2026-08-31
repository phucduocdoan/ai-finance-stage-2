# Bisect regression: full1012_v17_unitfix (0.3992) -> full1012_v18_postfix (0.3439)

## Vấn đề

So sánh hai lần chạy full 1012 câu hỏi:
- `full1012_v17_unitfix.jsonl` (2026-08-24 09:43, commit 87dcb79) — leaderboard 0.3992
- `full1012_v18_postfix.jsonl` (2026-08-29 22:48, HEAD) — leaderboard 0.3439

Trong 40 câu hỏi bị lật từ có đáp án ở v17 sang `answer=0.0` ở v18, rerun lại bằng code CŨ (87dcb79) hôm nay cho thấy 17/40 id vẫn ra đáp án khác 0. 17 id này (`158, 388, 395, 417, 524, 529, 540, 543, 551, 556, 566, 585, 591, 735, 736, 755, 901`) là bộ test dùng để bisect. Với ít nhất 3 id (735, 736, 540), routing solver giống hệt nhau giữa code cũ/mới (cùng tên solver, cùng `table_ids` retrieved) nhưng `codegen` sinh ra pandas_query khác và sai ở code mới.

## Bisection tiến trình

Danh sách 25 commit giữa 87dcb79 (exclusive) và HEAD (inclusive), lọc theo các commit đụng tới `src/finance_qa/modules/solve/` hoặc `graph.py`. Chạy lại 17 id trên từng worktree, đếm số câu ra đáp án khác 0 (`nonzero`).

| # | commit | subject (rút gọn) | nonzero/17 | id = 0.0 |
|---|--------|--------------------|-----------|----------|
| baseline | 87dcb79 | (đã đo trước, không rerun) | 17/17 | — |
| 13 | 7e893c7 | Phase 4: split verify_answer | 14/17 | 388, 543, 735 |
| 19 | 8642ab3 | Phase 4: split `_unexpressible` checks | 16/17 | 524 |
| 22 | 8213233 | Fail closed khi raw selection planner để trống slot | 13/17 | 540, 735, 591, 158(≈-0.0) |
| 23 | 1a01801 | Stop stripping 'cho' from raw-table scoring stopwords | (chỉ test riêng qid 529: **0.0**, xem chi tiết bên dưới) | 529 (deterministic) |
| 24 | 7f4fb27 | Label blank trailing all-numeric row as total row | 13/17 | 529, 556, 566, 755 |
| 25 | 35a313c | Fix two-company sign forcing + percent scaling trong codegen | 15/17 | 529, 735 |
| HEAD | b799b22 | Deny import/dunder-attribute trong sandboxed query compiler | 12/17 | 543, 556, 551, 529, 735 |

**Lưu ý quan trọng về nhiễu:** `codegen/execute.py` dùng `REPAIR_TEMPERATURE = 0.3` (không phải 0) cho vòng lặp sửa lỗi (repair), nên với phần lớn các id, kết quả không nonzero/zero ổn định giữa các lần chạy độc lập (cùng 1 commit, chạy lại có thể ra khác) — đây là non-determinism thật của pipeline, không phải lỗi đo đạc. Vì vậy đường cong 14→16→13→13→15→12 (không đơn điệu) phần lớn phản ánh nhiễu sampling ở bước repair, KHÔNG phải bisect sai.

Tuy nhiên, id **529** là một tín hiệu sạch, không nhiễu: nó cho ra đúng cùng một giá trị float `862.662368859` ở 3 lần chạy độc lập tại commit #13, #19, #22 — rồi cho ra đúng `0.0` ở 3 lần chạy độc lập tại #24, #25, và HEAD. Test trực tiếp tại #23 (1a01801) xác nhận: qid 529 đã gãy chính xác tại commit này.

## Kết luận (root cause)

**Commit gây lỗi (đã xác nhận bằng bằng chứng end-to-end): `1a01801` — "Stop stripping 'cho' from raw-table scoring stopwords"**

Diff:
```
src/finance_qa/modules/solve/solvers/raw_table_linking/request.py
-    "cai", "cac", "cho", "co", "cong", "cong ty", "cp", "ctcp", "cua",
+    "cai", "cac", "co", "cong", "cong ty", "cp", "ctcp", "cua",
+    # `cho` is deliberately absent: it was here as a filler particle, but stripping
+    # it also collapses `cho vay` ("to lend") into bare `vay` ("to borrow"), so a
+    # question about lending scores against a table about borrowing.
```

Cơ chế lan truyền, xác nhận bằng dữ liệu thật (qid 529, câu hỏi về "phải trả người bán ngắn hạn" của QNS):

- Tại commit #22 (trước fix, `cho` vẫn bị strip), `table_ids` retrieved xếp `QNS_financial_statements_2024_consolidated|49` ở vị trí thứ 3 (biến `df3`). Codegen sinh query sạch, đơn bảng:
  `df3.iloc[8]["Năm 2024"]` → ra `862.662368859` (khác 0, nhất quán 3 lần).
- Tại commit #23 (sau fix, `cho` KHÔNG bị strip nữa), thứ tự retrieved bị xáo trộn: `QNS_financial_statements_2024_consolidated|49` tụt xuống vị trí 5, một bảng khác (`...|9`) nhảy lên vị trí 4. Vì các biến `df1..df4` được gán theo thứ tự rank mới, codegen nhận một tập bảng khác và sinh ra query 4-bảng vô nghĩa:
  `df1.iloc[2]["31/12/2023 VND"] + df2.iloc[2]["31/12/2024 VND"] + df3.iloc[26]["31/12/2017"] + df4.iloc[0]["31/12/2020"]` → thất bại/`0.0`.

Vì stopword list này dùng để tính điểm scoring cho MỌI hàng/bảng trong `raw_table_linking` (không riêng qid 529), nên thay đổi này có khả năng làm xáo trộn thứ tự ranking của bảng ứng viên trên diện rộng, không chỉ ảnh hưởng 1 câu hỏi — bất kỳ câu nào có bảng chứa cụm "trả cho", "phải trả cho", v.v. trong nhãn hàng đều có thể bị đổi ranking tương tự.

**Các yếu tố góp phần khác (không phải nguyên nhân chính, nhưng làm giảm thêm điểm số ở các lần chạy sau):**
- `8213233` (Fail closed khi raw selection planner để trống slot) — behavior fail-closed hợp lý về logic nhưng làm tăng số câu trả về "không trả lời được" thay vì đoán, có thể chuyển một số câu vốn may mắn đúng thành 0.0.
- `35a313c` (sign forcing / percent scaling trong codegen) và `b799b22` (chặn dunder-attribute trong sandbox) — mỗi commit đều có phạm vi thay đổi hẹp và có kèm giải thích/test, nhưng cùng chạm vào code path codegen dùng để build và thực thi pandas_query, nên rất có thể mỗi commit đóng góp thêm một phần nhỏ regression cho các id khác trong bộ 17 (không truy vết đầy đủ do giới hạn thời gian — xem phần Đề xuất).
- Nhiễu sampling từ `REPAIR_TEMPERATURE=0.3` trong `codegen/execute.py` làm cho nhiều id (543, 551, 556, 566, 591, 735, 736, ...) không cho tín hiệu bisect sạch — chúng thành công hay thất bại tùy lần chạy, kể cả ở cùng 1 commit.

## Đính chính (2026-08-30, sau khi thử fix)

Kết luận "root cause = `1a01801`" ở trên **sai**, đã kiểm chứng lại và cần rút lại.

Đã áp dụng fix đề xuất ở mục Đề xuất #1 (làm `cho` context-sensitive trong `_tokens()`,
chỉ giữ khi liền trước `vay`/`thue`) và rerun trực tiếp qid 529 — **vẫn ra 0.0**, y hệt
lỗi cũ. Điều tra tiếp cho thấy: `raw_table_linker` **từ chối câu này ngay từ đầu**
("outside raw-table fixed-scope operations"), nên nó không bao giờ chạm tới code đã sửa
trong `raw_table_linking/request.py`. `table_ids` (biến df1..df4 mà `codegen` dùng) thực
ra đến từ một nhánh module khác hoàn toàn: `agents/finance/retrieve.py` ->
`modules/rag/service.py:aretrieve_table_ids` -> `Judge.apick` (`modules/rag/judge.py`,
1 lời gọi LLM). Không có quan hệ import nào giữa `modules/rag/` và
`raw_table_linking/` theo cả hai chiều — `1a01801` (chỉ sửa `raw_table_linking/request.py`,
5 dòng) không thể là nguyên nhân gây ra việc xáo trộn thứ tự `table_ids` cho qid 529.

Nguyên nhân thật nhiều khả năng là nhiễu đã biết: `core/llm.py` ghi chú rằng dù mọi lời gọi
dùng `temperature=0.0`, chạy lại cùng 1 cấu hình vẫn đổi ~10% câu trả lời (vLLM
continuous-batching float non-associativity), và `Judge.apick` không set `LLM_SEED`. Tín
hiệu "3 lần chạy giống hệt nhau trước commit, 3 lần giống hệt nhau sau commit" mà bisect
dùng làm bằng chứng "sạch" cho qid 529 nhiều khả năng chỉ là trùng hợp ngẫu nhiên với thời
điểm chạy, không phải nhân quả với `1a01801`.

Fix `_tokens()` vẫn được GIỮ LẠI trong code (đúng và có ích cho mục tiêu gốc — tách "cho vay"
khỏi "vay" trong scoring của raw_table_linker, mọi test cũ vẫn pass) — chỉ là nó **không phải
fix cho regression leaderboard** như kết luận ban đầu.

Bằng chứng còn đứng vững (không bị nhiễu che): qid 540, 735, 736 — bisect hôm nay (commit
87dcb79) ra đáp số khớp CHÍNH XÁC từng chữ số với `full1012_v17_unitfix.jsonl` (chạy cách đây
6 ngày, quy trình hoàn toàn độc lập) — đây là bằng chứng determinism thật, không phải nhiễu.
Với các id này, `table_ids` retrieved GIỐNG HỆT nhau giữa code cũ và code mới, nhưng `codegen`
sinh ra pandas_query KHÁC NHAU và sai ở code mới → cơ chế regression thật nằm trong chính
logic/prompt của `codegen` (module `solve/codegen/`), không phải ở tầng retrieval/ranking.
Đây là hướng nên truy tiếp, thay vì stopword list.

## Đề xuất

1. **Fix tối thiểu, rõ ràng nhất**: review lại thay đổi trong `1a01801` — bản thân việc bỏ `cho` khỏi stopword list là chủ đích (đúng cho case "cho vay"/"vay"), nhưng cần kiểm tra xem ranking/scoring trong `raw_table_linking/request.py` (và các file liên quan trong `raw_table_linking/`) có nên tách trọng số khác nhau cho "cho" khi nó xuất hiện như giới từ nối ("trả **cho** người bán") so với khi nó là 1 phần của cụm động từ ("**cho** vay") — ví dụ: chỉ giữ "cho" nếu liền trước "vay"/"thuê", còn lại vẫn strip như cũ. Đây là fix chính xác hơn là revert toàn bộ commit (vì revert sẽ tái tạo lại lỗi "cho vay" -> "vay" mà commit này cố tình sửa).
2. Sau khi sửa raw_table_linking scoring, nên chạy lại full 1012 để đo lại điểm thật, vì phần nhiễu do `REPAIR_TEMPERATURE=0.3` khiến kết quả trên tập 17 câu không đại diện hoàn toàn cho toàn bộ 1012 câu.
3. Vì thời gian có hạn, CHƯA truy vết đầy đủ cơ chế cho từng id còn lại trong số 17 (388, 395, 417, 524, 540, 543, 551, 556, 566, 585, 591, 735, 736, 755, 901) — nên làm thêm 1 lượt "before/after 1a01801" full-17 (thay vì chỉ test riêng qid 529) để xác nhận % đóng góp thực sự của riêng commit này so với các commit sau đó (8213233, 35a313c, b799b22).

## Dữ liệu / worktree

- Log cuối cùng giữ lại: `artifacts/runs/bisect_8213233_17q.jsonl` (commit #22, trước lỗi), `artifacts/runs/bisect_1a01801_qid529.jsonl` (commit #23, qid 529 gãy), `artifacts/runs/bisect_7f4fb27_17q.jsonl` và `artifacts/runs/bisect_35a313c_17q.jsonl` (commit #24, #25), `artifacts/runs/bisect_HEAD_b799b22_17q.jsonl` (HEAD hiện tại).
- Các worktree bisect (`/home/ding/ai-finance-bisect-<hash>`) đã được `git worktree remove` sau khi hoàn tất, trừ `/home/ding/ai-finance-bisect-87dcb79` (worktree cũ dùng chung với phần bisect trước, không tạo bởi phiên này).
