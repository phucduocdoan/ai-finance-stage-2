# Kế hoạch tuần cuối: leaderboard làm thước đo (2026-08-23)

Hạn còn 7 ngày. Doc này thay thế phần "việc tiếp theo" của
`docs/evidence_reachable_2026-08-23.md`, và đã được viết lại một lần sau hai quyết định:
giữ model local, và đặt sàn nhiễu run-to-run lên trước mọi việc quét.

## Ba con số làm nền

**Lượt nộp thoải mái.** Nên thước đo tốt nhất không còn là tập 119 câu. Tập đó có 1 sigma
bằng 5.4 câu, và đó là lý do duy nhất chín đường vừa rồi không chứng minh được gì: mỗi đường
đáng 2-3 câu. Leaderboard chạy trên 1012 câu và chính xác tới 1 câu cho một submission cho
trước. v8 → v9 đọc ra +0.0079 = đúng 8 câu.

**Một lần chạy 1012 câu mất khoảng 3.1 giờ ở một process, và nút thắt là một core CPU.**
Con số 1.7 giờ trong bản trước sai, vì nó suy từ 16 câu đầu bộ id, mà bộ đề được nhóm theo
loại câu: id 0-399 lẫn nhiều `single_cell` (trung vị ~125s) còn id 400 trở lên là 100%
`derived` (trung vị 292-524s). Nên phép đo mồi chỉ thấy phần rẻ.

Số thật, đọc từ trường `seconds` của từng bản ghi trên 722 câu của lần chạy HEAD:

| | |
|---|---|
| trung vị / trung bình / p90 / max mỗi câu | 163s / 263s / 617s / 1162s |
| đồng thời thực tế | **23.7 / 24 slot** đều bận |
| CPU thread chính | **98% của MỘT core**, liên tục cả 2.2 giờ |
| CPU mỗi câu | 10.8s → trần một core = **5.5 câu/phút** |
| thông lượng quan sát | **5.4 câu/phút** |

Ba dòng cuối khớp nhau, nên chẩn đoán chốt: 24 worker đều bận nhưng **xếp hàng sau một core**,
còn GPU rảnh (0% qua nhiều mẫu) và vLLM trả một request tầm thường trong 0.146s. Đã loại:
pool HTTP (`core/http.py:30` cho `max_connections=256`), cache `load_frame` (9 lượt gọi trên
9 bảng khác nhau, 0% wall), và rò rỉ bộ nhớ (RSS phẳng ở 5.1 GiB).

Hệ quả: `--workers` cao hơn không chữa được, phải **chia process**. `scripts/sweep_queue.sh`
giờ chạy `SHARDS=4` process song song, chia so le theo `id % 4` để không lệch tải giữa khối
rẻ và khối đắt, mỗi shard vẫn giữ workers=24 vì tỉ lệ wall:CPU là 24:1. Ràng buộc: 32 core
(thừa), RAM còn 60 GB ở 5.1 GB/process (vừa ~8), nhưng **VRAM chỉ còn 5 GB** trên 81.5 vì
vLLM giữ 56.9 GB và 15.5 GB là của process người khác, nên shard thứ hai trở đi sẽ tự hạ BGE
về CPU theo `dense.py:48-51`. Đó là lý do chọn 4 chứ không phải 8.

Chưa đo: 4 shard có đạt gần 4x hay không. Và 10.8s CPU/câu chưa biết nằm ở hàm nào, vì
`py-spy` cần sudo (`ptrace_scope=1`); nếu tìm được hotspot thì nó rẻ hơn chia shard và có
lợi cho mọi cấu hình.

Kích cỡ hàng đợi theo con số này: 13 cấu hình × 3.1 giờ = **41 giờ ở một process**, xuống
khoảng 10-12 giờ nếu 4 shard đạt 3.5-4x. v7 chạy 30 giờ ở workers=1.

**Model giữ nguyên Qwen3.5-9B local.** Đã cân nhắc đổi sang model lớn qua DeepInfra và **đã
bỏ** theo quyết định của người dùng. Hệ quả tốt: mỗi lần chạy miễn phí về tiền và chỉ tốn GPU
đang rảnh, nên nút thắt chuyển sang lượt nộp và sự chú ý của người, không phải compute. Sáu
ngày là khoảng 90 lần chạy nếu chạy nối đuôi, tức năng lực đo nhiều hơn số giả thuyết đang có.

Lập luận cho việc đổi model vẫn ghi lại ở đây vì nó có thể quay lại nếu mọi thứ khác cạn: tỉ
lệ đọc đúng một ô 51% là con số về dung lượng model, và nó chặn cả hai khối cùng lúc, lớp tra
một ô ở 51% và lớp sàng lọc ở `0.51^8` ≈ 0.5%. Lên 70% thì lớp sàng lọc thành `0.70^8` = 5.8%.

## Sàn nhiễu run-to-run: cửa phải qua trước mọi việc quét

Leaderboard chính xác cho **một submission**, nhưng lần chạy sinh ra nó thì không xác định.
Repo đã ghi hai lần chạy baseline cùng cấu hình lệch **2 câu trên 94** (`config.py:334`,
ghi chú `codegen_tool_turns`). Nhân lên 1012 là khoảng 21 câu, tức **2.1 điểm phần trăm**,
lớn hơn gần như mọi đường trong hàng đợi quét.

Nguồn nhiễu, cả ba đều đã kiểm: temperature là 0.0 ở mọi caller nhưng vLLM với continuous
batching không xác định theo bit; `REPAIR_TEMPERATURE` là 0.3; workers=24 đổi thứ tự.

**Chỉ dấu sớm, và nó lớn hơn 2 câu nhiều.** Trên 89 câu có nhãn đã xong của lần chạy HEAD so
với v9: HEAD 36 đúng, v9 38, tức ròng −2, nhưng **churn là 3 được + 5 mất = 8 trên 89 = 9%**,
tức khoảng 91 câu trên 1012. Cảnh báo phải đi kèm: HEAD so v9 **không phải** hai lần chạy
giống nhau (v9 là commit khác cộng hai lần vá tay), nên 8 câu đó lẫn cả thay đổi thật lẫn
nhiễu, và nó là **cận trên**. Chỉ `head_b` tách được. Nếu 9% là thật thì SE của hiệu ròng là
`sqrt(91)` ≈ 9.5 câu ≈ 0.94pp, và đó chính là con số làm nên bảng z ở mục Việc số 1.

Bỏ qua chuyện này là lặp lại đúng cái đã giết chín đường trước, chỉ đổi sàn từ 5.4 câu sang
21 câu. Và nó đo được **miễn phí, không tốn lượt nộp nào và không cần nhãn**: chạy lại đúng
cấu hình mặc định rồi đếm câu đổi đáp án. Nên dòng đầu hàng đợi không phải một đường mới.

`scripts/compare_runs.py` tách hai cột có chủ ý:

- **đổi đáp án** trên 1012 câu là **cận trên** của nhiễu điểm, vì một câu sai ở cả hai lần
  chạy đổi số mà không đổi điểm.
- **đổi điểm** trên tập có nhãn là con số thật cần so, nhưng chỉ đo được trên 119 câu.

Mọi delta của hàng đợi phải so với con số đó, không so với 0.

## Vòng lặp hai tầng cho mỗi giả thuyết

- **Tập 119 câu làm cửa phủ quyết, không làm cửa quyết định.** Nó không chứng minh được một
  cái thắng 3 câu, nhưng nó bắt được một cái tụt lớn hơn 1 sigma, và tốn vài giây.
- **Leaderboard làm cửa quyết định.**

Nên mỗi giả thuyết: chạy ~3.1 giờ ở một process (ít hơn nếu 4 shard đạt gần 4x), chấm trên
119 miễn phí, nếu không tụt rõ thì nộp, đọc con số chính xác.

## Việc số 0, đang chạy: baseline ở HEAD

v9 ở 0.334 **là lần chạy v7 ngày 19/08 vá tại chỗ hai lần, không chạy lại LLM**. Từ đó tới
nay có 13 commit vào `src/`, không commit nào từng được đo trên bài thi:

| commit | nội dung |
|---|---|
| `71890ce` | sửa `LLM_MODEL` mặc định; trước đó mọi call 404 và mọi câu trả 0.0 |
| `119729d` | đưa cờ solver mặc định về đúng cấu hình đã nộp |
| `ebbe531` | dựng lại header hai tầng bằng lặp lá |
| `9e7bcf6` | chấm dòng theo đúng từ mà câu hỏi yêu cầu |
| `fa90985` | chấm trục cột và dòng tổng trên bằng chứng, không trên hình dạng bảng |
| `34e791a` | xen bảng của codegen theo công ty |
| `26de9ca` | `project_year` nhìn qua lớp `round()` |
| `5fa0a1d` | trả độ lớn khi hiệu là giữa hai công ty, chính là luật dấu của v9 |

Nên 0.334 không nói gì về code hiện tại. Việc đầu tiên là chạy HEAD trên 1012 và nộp, không
viết thêm gì. Kết quả có thể thấp hơn 0.334, và nếu thế thì đó là thông tin đắt nhất trong
tuần: một trong 13 commit là hồi quy, và mọi thứ xây trên đó đang xây trên nền lún.

Hai bản vá làm nên +30 câu của v8 và v9 **đều đã nằm trong code path** của lần chạy mới, đã
kiểm: luật dấu ở `apply_units` (`execute.py:296`), và `round(...,2)` là **mặc định** của
`build_submission.py`, cờ `--no-round-final` mới là arm đối chứng. Không mất gì.

```
artifacts/runs/full1012_head.jsonl   commit 18a8b89, workers=24, không env override
```

## Việc số 1: hàng đợi quét, một arm bật hết cờ

`scripts/sweep_queue.sh`, chạy nối đuôi, `SHARDS=4`, có `--resume` nên một lần bị ngắt
không mất cả lần chạy.

### Vì sao không phải 13 arm đơn lẻ

Bảng 14 cấu hình của bản trước sai về thiết kế, không chỉ sai về thời gian. So sánh theo
cặp: nếu churn run-to-run là `C` câu thì SE của hiệu ròng là ~`sqrt(C)`. Quy tắc §11.2 nói
một đường điển hình đáng **+8 câu trên 1012** (+3/119 trên eval sạch đã đọc ra +0.79pp).

| | hiệu ròng | SE | z |
|---|---|---|---|
| một cờ đơn lẻ | +8 câu | ~9.9 | **0.8** |
| bật hết cờ | +40 câu trở lên | ~11.4 | **3.5** |

13 arm đơn lẻ tốn 41 giờ rồi vẫn ở 0.8 sigma, tức lặp lại đúng cái đã giết chín đường
trước, chỉ đổi thước đo từ 5.4 câu sang 10 câu.

### Và các "tiên nghiệm âm" không sống nổi qua chính lập luận đó

Bản trước loại `metric_hints`, `structured_facts`, `decompose` khỏi chồng vì đã đo và thấp.
Nhưng `metric_hints` 38 so với 42 là chênh **4 câu trên 94**, `screening` 2/29 so với 4/29
là chênh **2 câu**. Đó đúng cỡ mẫu mà mục trên vừa nói không phân giải nổi ±8. Chúng là
nhiễu, không phải bằng chứng âm.

Ngoại lệ duy nhất là `screening`, vì lập luận của nó **cấu trúc** và độc lập với n: truy
vấn sàng lọc đọc 6-12 ô, mỗi ô cần đúng dòng, đúng cột, đúng đơn vị, nên ở 51% một ô thì
`0.51^8` ~ 0.5%. Nó vẫn được một arm riêng vì giá bây giờ chỉ là một lần chạy.

### Hàng đợi

| # | arm | vai trò |
|---|---|---|
| 1 | `head_b`, không đổi gì | **sàn nhiễu**, cửa phải qua trước mọi dòng dưới |
| 2 | `all_on`, 11 núm | arm tín hiệu mạnh nhất |
| 3-4 | `all_on_a` / `all_on_b` | bisect, chỉ chạy nếu arm 2 lệch khỏi sàn |
| 5 | `no_verify` | đối chứng, đứng riêng vì nó TẮT một bước |
| 6 | `screening` | lập luận cấu trúc nói nó chết, vẫn đo |

Bisect chia theo **tầng**, không chia bừa: `all_on_a` đổi thứ prompt được nhìn thấy
(`metric_hints`, `metric_lookup`, `table_profiles`, `profile_validate`, `multi_company=12`,
`sub_tables=12`, `tool_turns=3`), `all_on_b` đổi cách giải (`ratio_groups`,
`repair_history`, `structured_facts`, `decompose`).

`SOLVE_PROFILE_VALIDATE` là một núm chưa từng xuất hiện trong bảng nào trước đây.

### Ba núm thinking vỡ sẵn, đọc được từ code

Không cần probe. Mọi chỗ gọi truyền `thinking=` qua mà **không nâng** ngân sách token:

| chỗ gọi | `max_tokens` |
|---|---|
| `raw_table_linker.py:1601`, `:1633`, `:1827` | 768 |
| `raw_table_linker.py:1670` | 1024 |
| `formula_facts.py:433` | 768 |
| `structured_facts.py:1553-1554` | **8192** khi thinking bật |

Chỉ chỗ cuối nâng. Và bằng chứng đã ghi: structured_facts bản thinking chết bằng
`LengthFinishReasonError` ở 2048 token trên cả 12 câu, cần 8192 mới parse được, rồi vẫn ra
selection plan sai; `codegen_thinking` để False vì reply rỗng ở mọi ngân sách. Nên
`SOLVE_RAW_TABLE_LINKER_PLANNER_THINKING` và `SOLVE_FORMULA_FACTS_PLANNER_THINKING` lỗi
mọi lần gọi. Chúng **vỡ sẵn**, không phải chưa đo. Hai dòng nâng `max_tokens` là sửa được,
nhưng đó là thay đổi code chứ không phải bật cờ.

## Việc số 2: trọng tài PoT/CoT

Đường duy nhất có tiền lệ đo được dương mà chưa dựng: hai arm đồng thuận thì đúng 32/32 qua
hai lần chạy, khoanh đúng 25/40 câu không đáng tin, 15 trong số đó đã có đáp án đúng ở một
trong hai arm, trần oracle 52 → 60/73.

Nó xếp sau hàng đợi vì là món duy nhất cần viết code mới. Với model local thì arm CoT trên đủ
1012 câu cũng miễn phí, nên nó rẻ hơn lúc tôi định giá lần đầu.

Số học đầy đủ, gồm phần ghép với `EXECUTION_ACCURACY`. Chỉ số đó bằng `ANSWER` trừ **đúng 2
câu** ở cả ba lần nộp, nên nó là "chạy lại truy vấn có ra đúng số đã nộp", không phải "truy
vấn chạy được". Trên 25 câu lệch nhau, PoT đúng 7, CoT đúng 8, cả hai sai 10. Ghi đè mà thắng
thì được +1 `ANSWER` và 0 `EXECUTION`, vì câu đó vốn sai cả hai. Ghi đè mà thua thì mất −1 ở
**cả hai**. Bất đối xứng đó chữa được bằng một ràng buộc:

> Trọng tài chỉ được ghi đè khi nó kèm được một `pandas_query` chạy ra đúng số nó chọn.

Có ràng buộc đó thì thắng và thua cùng giá, và mốc trở lại McNemar 10 thắng / 2 thua.

## Việc không làm, và lý do

**Đổi model:** bỏ theo quyết định người dùng, giữ Qwen3.5-9B local. Lập luận giữ ở mục trên.

**Mở rộng tập eval 119 → 400: bỏ.** Đúng ba tuần trước, sai bây giờ. Tốn 2 trong 7 ngày,
không sinh điểm nào, và thứ nó mua là độ phân giải mà leaderboard vừa cho miễn phí và tốt hơn.

**Dò `TABLES_F2MACRO`: đóng.** 12 lượt nộp đã tiêu, kỷ lục 0.0035, hệ đánh số của repo không
bao giờ khớp gold được (`docs/tables_metric_probes.md`).

**Đường thứ mười ở codegen: không thiết kế.** Với câu v9 sai, thứ codegen được nhìn thấy chạm
gold ở mức ngẫu nhiên; trần của cả nhóm đó bị chặn bởi thứ vào prompt, không bởi cách prompt
được xử lý (`docs/evidence_reachable_2026-08-23.md`).

## Điểm không quay lại

v9 ở 0.334 là bảo hiểm. **Ngày 6 phải nộp bản tốt nhất đang có và dừng**, để ngày 7 làm dự
phòng cho sự cố. Mọi thứ trên đây bỏ giữa đường được mà không mất gì, vì không món nào sửa
vào đường đi mặc định trước khi nó đo được điểm.

## Việc còn nợ, không nằm trong đường tới điểm

- `docs/l5_screening_cause_2026-08-23.md` chưa viết. 27 id lớp L5 đã có; tôi đã cảnh báo q214
  và q336 trông như câu tra một công ty bị heuristic phân tier theo text gán sai.
- `tests/test_query_execution.py` có 2 lỗi có sẵn, chưa đối chiếu với `ebbe531`. Đã xác nhận
  giống nhau từng byte trước và sau công việc phiên này.
- `docs/CELL_LOCATOR_STATUS.md` còn khuyến nghị "giữ cờ OFF", lạc hậu từ `119729d`.
- `graph.py` giữ kết quả `arevise` mỗi khi nó chỉ cần chạy được, trái với docstring của chính
  nó. Chờ quyết định.
- `DEEPINFRA_API_KEY` đã bị in ra transcript ở một phiên trước và cần rotate, dù giờ không
  dùng tới nữa.
- `/home/ding/.config/last30days/.env` đang 644, nên là 600.
