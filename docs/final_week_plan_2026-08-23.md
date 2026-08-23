# Kế hoạch tuần cuối: leaderboard làm thước đo (2026-08-23)

Hạn còn 7 ngày. Hai điều kiện vừa xác định lại đổi hẳn thứ tự ưu tiên so với mọi kế hoạch
trước, nên doc này thay thế phần "việc tiếp theo" của `docs/evidence_reachable_2026-08-23.md`.

## Hai con số làm nền cho mọi thứ dưới đây

**Lượt nộp thoải mái.** Nên thước đo tốt nhất không còn là tập 119 câu. Tập đó có 1 sigma
bằng 5.4 câu, và đó là lý do duy nhất chín đường vừa rồi không chứng minh được gì: mỗi đường
đáng 2-3 câu. Leaderboard chạy trên 1012 câu và **không có sàn nhiễu**, cùng một submission
cho cùng một điểm. v8 → v9 đọc ra +0.0079 = đúng 8 câu. Nó là phép đếm chính xác tới 1 câu.

**Một lần chạy 1012 câu mất khoảng 2 giờ.** Đo trực tiếp trên 16 câu, cùng bộ id, cùng cấu
hình:

| workers | wall | trừ ~120s nạp index | suy ra 1012 câu |
|---|---|---|---|
| 8 | 317s | 197s | 3.5 giờ |
| 24 | 214s | 94s | **1.7 giờ** |

vLLM chưa bão hoà ở workers=8. Giây solver tích luỹ là 2120s cho 16 câu, tức workers=24 cho
tốc độ gấp 6.7 lần so với workers=1 (bản v7 chạy 30 giờ ở workers=1). Chưa thử quá 24.

Hệ quả: nút thắt của tuần này không phải lượt nộp, không phải nhiễu tập eval, không phải
compute. Nó là **số giả thuyết đáng thử**.

## Việc số 0, đang chạy: baseline ở HEAD

v9 ở 0.334 **là lần chạy v7 ngày 19/08 vá tại chỗ hai lần, không chạy lại LLM**. Từ đó tới
nay có 13 commit vào `src/`, và không commit nào từng được đo trên bài thi:

| commit | nội dung |
|---|---|
| `71890ce` | sửa `LLM_MODEL` mặc định; trước đó mọi call 404 và mọi câu trả 0.0 |
| `119729d` | đưa cờ solver mặc định về đúng cấu hình đã nộp |
| `ebbe531` | dựng lại header hai tầng bằng lặp lá |
| `9e7bcf6` | chấm dòng theo đúng từ mà câu hỏi yêu cầu |
| `fa90985` | chấm trục cột và dòng tổng trên bằng chứng, không trên hình dạng bảng |
| `34e791a` | xen bảng của codegen theo công ty |
| `26de9ca` | `project_year` nhìn qua lớp `round()` |
| `5fa0a1d` | trả độ lớn khi hiệu là giữa hai công ty (chính là luật dấu của v9) |

Nên con số 0.334 không nói được gì về code hiện tại. Việc đầu tiên là chạy HEAD trên 1012 và
nộp, không viết thêm gì.

Hai bản vá làm nên +30 câu của v8 và v9 đều đã nằm trong code path của lần chạy mới, đã kiểm:
luật dấu ở `apply_units` (`execute.py:296`), và `round(...,2)` là **mặc định** của
`build_submission.py`, cờ `--no-round-final` mới là arm đối chứng. Không mất gì.

```
artifacts/runs/full1012_head.jsonl   commit 18a8b89, workers=24, không env override
```

Kết quả này có thể thấp hơn 0.334. Nếu thế thì nó là thông tin đắt nhất trong tuần, vì nó có
nghĩa một trong 13 commit là hồi quy và mọi thứ xây trên đó sẽ xây trên nền lún.

## Việc số 1: quét cờ, mỗi cờ một lần chạy

Sáu tới chín cơ chế **đã viết xong, đang tắt**, và mỗi cái bị giết trên n = 29 tới 40 với sàn
nhiễu 4 tới 6 câu. Trên 1012 câu leaderboard đếm chính xác. Mỗi cái là một biến môi trường
cộng hai giờ.

| cờ | số đã đo | ghi ở đâu |
|---|---|---|
| `SOLVE_SCREENING` | 2/29 so với baseline 4/29 | `answer_signatures` §cuối |
| `SOLVE_STRUCTURED_FACTS` | 4/29, mốc chốt trước 8/29 | `gate_screening_structured.out` |
| `SOLVE_DECOMPOSE` | 3/34 | `config.py:388` |
| `SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS` | chưa đo | `config.py:177` |
| `SOLVE_METRIC_HINTS` | chưa đo | `config.py:282` |
| `SOLVE_TABLE_PROFILES` | chưa đo | `config.py:290` |
| `SOLVE_PROFILE_VALIDATE` | chưa đo | `config.py:298` |
| `SOLVE_METRIC_LOOKUP` | chưa đo | `config.py:313` |
| `SOLVE_REPAIR_HISTORY` | chưa đo | `config.py:418` |

Phải nói rõ giới hạn của việc này: `SOLVE_SCREENING` có lập luận cấu trúc chống lại nó,
không chỉ có con số nhỏ. Truy vấn sàng lọc đọc 6 tới 12 ô, mỗi ô phải đúng dòng, đúng cột,
đúng đơn vị; ở tỉ lệ đọc đúng một ô 51% thì `0.51^8` ≈ 0.5%. Lập luận đó không phụ thuộc n,
nên khả năng cao nó vẫn chết. Vẫn đáng một lần chạy vì giá bây giờ là 2 giờ, không phải một
tuần.

## Việc số 2, và tôi cho đây là cái lớn nhất còn lại: đổi model

Toàn bộ việc đọc bảng đang do **Qwen3.5-9B** làm. Tỉ lệ đọc đúng một ô 51% là một con số về
dung lượng model, và nó chặn mọi thứ cùng lúc: lớp tra một ô ở 51%, lớp sàng lọc ở `0.51^8`.
Số của chính BTC cùng chiều, oracle CoT 87% tụt xuống 64% khi phải tự truy hồi.

Nếu 51% lên 70% thì lớp tra một ô lên trực tiếp, **và** lớp sàng lọc lên `0.70^8` = 5.8%, gấp
12 lần. Đó là lần duy nhất trong cả dự án một thay đổi tác động lên cả hai khối.

Nó cần đúng ba biến môi trường, không một dòng code:

```
LLM_ENDPOINT=https://api.deepinfra.com/v1/openai/chat/completions
LLM_MODEL=<model lớn>
LLM_API_KEY=...
```

Nhánh DeepInfra đã viết và đã dùng (`core/llm.py:55-69`, thinking bật bằng tiền tố
`/no_think` thay vì `chat_template_kwargs`).

Ẩn số duy nhất là chi phí, và nó đo được từ chính lần chạy đang diễn ra: đếm token vào và ra
trên 1012 câu, nhân đơn giá. Phải đo trước khi bật, vì solver stack gọi model nhiều lần một
câu chứ không một lần.

**Trước khi dùng key: `DEEPINFRA_API_KEY` đã bị in ra transcript ở một phiên trước và cần
được rotate.** Không đọc `.env` để lấy nó; export trong shell rồi chạy.

## Việc số 3, tụt xuống cuối: trọng tài PoT/CoT

Vẫn là đường duy nhất có tiền lệ đo được dương mà chưa dựng: hai arm đồng thuận thì đúng
32/32 qua hai lần chạy, khoanh đúng 25/40 câu không đáng tin, 15 trong số đó đã có đáp án
đúng ở một trong hai arm, trần oracle 52 → 60/73.

Nó tụt xuống cuối vì hai lý do. Nó là món duy nhất cần viết code mới. Và kỳ vọng của nó,
tính đầy đủ, nhỏ hơn một lần đổi model.

Số học đầy đủ, gồm phần ghép với `EXECUTION_ACCURACY` mà tôi mới xác định: `EXECUTION` bằng
`ANSWER` trừ đúng 2 câu ở cả ba lần nộp, nên nó là "chạy lại truy vấn có ra đúng số đã nộp",
không phải "truy vấn chạy được". Trên 25 câu lệch nhau, PoT đúng 7, CoT đúng 8, cả hai sai
10. Ghi đè mà thắng thì được +1 `ANSWER` và 0 `EXECUTION`, vì câu đó vốn sai cả hai. Ghi đè
mà thua thì mất −1 ở **cả hai**. Bất đối xứng đó chữa được bằng một ràng buộc:

> Trọng tài chỉ được ghi đè khi nó kèm được một `pandas_query` chạy ra đúng số nó chọn.

Có ràng buộc đó thì thắng và thua cùng giá, và mốc trở lại McNemar 10 thắng / 2 thua.

## Việc không làm, và ghi lại lý do

**Mở rộng tập eval 119 → 400: bỏ.** Nó đúng ba tuần trước và sai bây giờ. Nó tốn 2 trong 7
ngày, không sinh điểm nào, và thứ nó mua là khả năng phân giải cho một thước đo mà leaderboard
vừa thay thế hoàn toàn với độ phân giải tốt hơn và giá bằng không.

**Dò `TABLES_F2MACRO`: đóng, giữ nguyên kết luận cũ.** 12 lượt nộp đã tiêu, kỷ lục 0.0035, và
hệ đánh số của repo không bao giờ khớp gold được (`docs/tables_metric_probes.md`).

**Đường thứ mười ở codegen: không thiết kế.** `docs/evidence_reachable_2026-08-23.md` đã đo:
với câu v9 sai, thứ codegen được nhìn thấy chạm gold ở mức ngẫu nhiên. Trần của cả nhóm đó
bị chặn bởi thứ vào prompt, không bởi cách prompt được xử lý.

## Điểm không quay lại

Bản v9 ở 0.334 là bảo hiểm. Ngày 6 phải nộp bản tốt nhất đang có và dừng, để ngày 7 làm dự
phòng cho sự cố. Mọi thứ trên đây đều có thể bỏ giữa đường mà không mất gì, vì không món nào
sửa vào đường đi mặc định trước khi nó đo được điểm.
