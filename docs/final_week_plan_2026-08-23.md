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

## v10: tập 119 câu chỉ HƯỚNG SAI, không chỉ sai độ lớn

Đo được ngày 2026-08-23, và nó đổi thiết kế quét nên đứng trước mọi mục dưới.

`full1012_head.jsonl` là lần chạy đầu tiên ở HEAD sau 13 commit chưa từng được đo trên đề
thật. Hai thước đo nói ngược nhau:

| | v9 | v10 | đổi |
|---|---|---|---|
| eval sạch 119 câu | 49/119 | 46/119 | **−3 câu** |
| ANSWER_ACCURACY (1012 câu) | 0.334 = 338 câu | 0.3478 = 352 câu | **+14 câu** |
| EXECUTION_ACCURACY | 0.332 = 336 câu | 0.3478 = 352 câu | **+16 câu** |

Tập 119 câu không chỉ thiếu độ phân giải. Nó **chỉ sai hướng** trên một thay đổi đáng +14 câu.
Tôi đã suýt kết luận 13 commit là vô ích dựa trên nó, và churn 11 câu với z = 0.9 lúc đó đúng
là lý do phải treo kết luận, nhưng lần này thì "treo" vẫn chưa đủ: dấu của nó cũng không tin được.

Lời giải thích thì tầm thường, và tôi đã đoán sai nó một lần trước khi tính: giả thuyết đầu của
tôi là tập eval lấy mẫu dày ở hai lớp yếu. **Sai.** `multi_company` chiếm 32% tập nhãn so với 31%
trên 1012, tỉ lệ 1.1, không có chệch nào đáng kể.

Nguyên nhân thật chỉ là số học của cỡ mẫu. +14 câu trên 1012 là +1.4%, tức kỳ vọng trên 119 câu
là **+1.7 câu**. Sàn nhiễu churn đo được là 11 câu, nên SE của hiệu ròng là `sqrt(11)` = 3.3.
Quan sát −3 nằm cách kỳ vọng 1.4 SE. Không hề bất thường, và **hoàn toàn có thể đổi dấu**, vì
tín hiệu 1.7 nhỏ hơn nhiễu 3.3.

Đó là phát biểu định lượng thay cho quy tắc §11.2 ("eval sạch phóng đại delta ~3 lần, chia cho 3").
Quy tắc đó chỉ dùng được khi thay đổi đủ lớn để vượt nhiễu: cần hơn ~7 câu trên 119, tức hơn
**~55 câu trên 1012**. Không đường nào trong hàng đợi có cỡ đó. Nên với mọi thứ tuần này định
làm, eval sạch không đọc được, kể cả dấu.

Chi tiết ăn khớp: lớp tra một ô đứng y nguyên 43/82 ở cả hai bản, toàn bộ −3 nằm ở sàng lọc
nhiều công ty (1/25 → 0/25) và hai tài liệu (5/12 → 3/12), tức 37 câu làm nền cho cả hiệu số.

### Hệ quả: bỏ hẳn cửa phủ quyết 119 câu, nộp thẳng từng arm

Thiết kế cũ là chạy arm rồi chấm 119 câu để quyết có nộp hay không. Cửa đó giờ có hại: nó vừa
suýt chặn một bản đáng +14 câu. Thay bằng:

> Chạy arm trên 1012 câu, nộp, đọc leaderboard. Không lọc bằng eval sạch.

Lượt nộp thoải mái nên cửa lọc không mua được gì mà chỉ thêm một nguồn sai hướng. Eval sạch còn
đúng một việc: **kiểm tra format và câu thiếu** trước khi nộp, tức `build_submission.py` báo đủ
1012 câu và schema hợp lệ. Không dùng con số của nó để quyết định nữa.

Việc này cũng làm hàng đợi quét đơn giản hơn hẳn. `head_b` vẫn cần vì sàn nhiễu run-to-run là
thật và đo được không tốn gì, nhưng bisect theo tầng (`all_on_a`, `all_on_b`) không còn phải chờ
`all_on` thắng mới chạy: nộp cả ba rồi đọc ba con số.

### `EXECUTION_ACCURACY` khớp `ANSWER_ACCURACY` lần đầu

v7, v8, v9 đều thấp hơn đúng 2 câu. v10 bằng nhau. Nghĩa là mọi truy vấn đã nộp chạy lại ra
đúng số đã nộp. Khớp với phép đo độc lập ở mục "việc số 3": 36/36 câu codegen tái tạo được đáp
án khi chạy lại `pandas_query` trên cùng bảng.

Còn hai câu vẫn rơi về hằng số, và lần này có thông báo lỗi rõ:

```
#408, #411: pandas_query literal fallback
            (TypeError: type numpy.bool doesn't define __round__ method)
```

Truy vấn trả về `numpy.bool` rồi `round_final` vỡ. Cả hai câu đều nằm trong rổ chắc chắn sai.
Đây là lỗi thật và sửa được bằng một dòng, nhưng nó chỉ đáng 2 câu nên không chen lên trước.

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

### Đo thật bằng `head_b`, và nó gần đúng con số đã dùng

`head_b` là lần chạy lại y nguyên cấu hình của `head`. Đây là lần đầu tuần này có một cặp
cùng cấu hình thật, nên sàn nhiễu không còn là suy diễn:

| | |
|---|---|
| đổi đáp án trên 1012 câu | 341 = **34%** |
| đổi ĐIỂM trên tập nhãn | **8/119 = 6.7%** |
| suy ra trên 1012 | ~68 câu |
| SE của hiệu ròng = `sqrt(68)` | **~8 câu = 0.81pp** |

34% là cận trên và nó vô dụng, vì phần lớn là sai → sai-khác-số, không đổi điểm. Con số phải
dùng là 6.7%, và nó nằm sát 0.94pp đã dùng để tính bảng z cả tuần, nên không kết luận nào
phải đảo. Hai hệ quả cụ thể: v10 hơn v9 **+14 câu** ở `z = 1.7`, tức vẫn chưa chứng minh; và
cùng một cấu hình cho 46 rồi 50 trên tập nhãn, nên ±5 câu ở đó là nhiễu thuần (SE ≈ 2.8).
Việc bỏ cửa phủ quyết 119 câu ở mục v10 vì thế được xác nhận từ hướng khác.

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

## Việc số 3: rổ "chắc chắn sai", cược duy nhất một chiều của tuần

Đo trên 888 câu đầu của lần chạy HEAD. Hai tiêu chí, cả hai không cần nhãn:

| tiêu chí | n trên 888 |
|---|---|
| đáp án `0.0` — mặc định bỏ cuộc ở `graph.py:1174` (`"answer": 0.0, "pandas_query": "0.0"`) | 44 |
| vượt biên độ suy ra từ `unit_hint`: `phần trăm`/`lần`/`nghìn tỷ` > 1e4, `tỷ` > 1e7, `triệu` > 1e10, `đồng` > 1e15 | 34 |
| **tổng** | **78 = 8.8% → ~89 câu trên 1012** |

Trên 16 câu của rổ có nhãn sạch: **báo oan 0**. Con số đó không phải phát biểu thống kê trên
n=16, nó gần như định nghĩa — một đáp án `unit_hint = phần trăm` bằng 2.3e13 không thể đúng,
và `0.0` là hằng số chương trình ghi ra khi mọi solver đã từ chối.

71 trong 78 câu là `codegen`. Đây là lý do trực giác "codegen vô dụng" vừa đúng vừa sai:
codegen mang **1/3 tổng số câu đúng** (13 trên 40 câu đúng của 106 câu có nhãn) và là fallback
cuối `SOLVER_CHAIN` nên tắt nó là 441 câu không có đáp án nào — nhưng **91% số đáp án chắc chắn
sai nằm trên nó**.

Vì sao nó xếp trên hàng đợi quét dù chưa đo: mọi arm cờ có thể **thua**, nên phải so với sàn
nhiễu `sqrt(C)` và cần z. Rổ này thì thay một đáp án chắc chắn sai bằng bất cứ gì đều không mất
điểm, nên nó không có mặt âm và **không cần sàn nhiễu để đọc**. Giá là ~25 phút với 24 worker
(trung vị 461s/câu, 10.1 giờ tuần tự).

Chỗ không được nói quá: **không lỗ không có nghĩa là sẽ lãi.** Lãi chỉ đến từ số câu sửa được
thật, và tỉ lệ đó CHƯA ĐO. Mọi con số kiểu "+18 câu" là giả định 20%, không phải phép đo. Đây
đúng chỗ đường thứ chín đã chết: phát hiện 7/7, chuyển đổi 0/7.

Và lần này có bằng chứng nói chuyển đổi sẽ khó: tỉ lệ lệch của 6 câu vượt biên độ có nhãn là
2.6e11, 3.4e13, 7.8e11, 3.65e11, 1.85e12, 8.5e9 — **không phải lũy thừa 10**. Nên nhân chia lại
thang không cứu được; model đã tổng hợp sai thứ, không chỉ sai đơn vị. Đường sửa duy nhất còn
lại là giải lại bằng cấu hình khác, không phải hậu xử lý số học.

Mốc đăng ký trước, trên ~16 câu của rổ nằm trong tập nhãn: **≥ 3 câu chuyển sai → đúng** thì
giữ, dưới mức đó thì rổ này cũng đóng như đường thứ chín. Ràng buộc giữ đáp án mới: chỉ thay
khi đáp án mới khác 0 **và** nằm trong biên độ đơn vị, và nó phải kèm `pandas_query` chạy ra
đúng số đó, vì `EXECUTION_ACCURACY` chạy lại truy vấn.

### Nhóm sai thang mà rổ này KHÔNG bắt được

14/108 câu có nhãn sai vì thang chứ không vì ô. Bốn câu trong đó **cùng mantissa, chỉ lệch lũy
thừa 10** — tức đã tìm đúng ô rồi quy đổi đơn vị sai:

| id | gold | nộp | tỉ lệ | unit_hint | solver |
|---|---|---|---|---|---|
| q139 | 3.1766e9 | 3.1766e6 | 1e-3 | đồng | cell_locator |
| q284 | 1.747e7 | 17.47 | 1e-6 | triệu | cell_locator |
| q748 | 913.29 | 9.1329e8 | 1e6 | triệu | raw_table_linker |
| q772 | 86.25 | 0.086253 | 1e-3 | tỷ | raw_table_linker |

Luật biên độ **không** bắt được chúng, vì biên của `triệu`/`đồng` rộng tới 1e10/1e15. Đây là
nhóm rẻ nhất trong cả dự án về mặt cơ chế — đúng chữ số, sai số mũ — nhưng nó nằm ở solver hẹp
chứ không ở codegen, và phát hiện nó cần biết thang đúng của bảng nguồn, không chỉ `unit_hint`.
Chưa định giá.

Hai câu nữa (q842 gold 2022, q866 gold 2018) có gold là **một năm** mà nộp 1.5e12 và −1.37e11.
Sai kiểu đáp án, không sai thang.

### Chốt luôn một món nợ: giữ bản sửa của verify là net dương

`VERIFY_NARROW_SOLVERS_OBSERVE_ONLY = True` nên verify+revise chỉ chạy thật trên đường codegen,
tức toàn bộ chi phí của nó nằm trong 67.8% thời gian mà codegen chiếm. Nó nói "sai" trên 312/416
câu, và nhóm đó đúng 3/36 so với 10/12 của nhóm nó nói "đúng" — nhưng **hai số đó không đọc
được thành tác dụng của việc sửa**, chúng đo độ khó của câu.

Phép đo sạch không cần LLM: `diag.verify.before` lưu truy vấn gốc, chạy lại nó trên cùng bảng.
Map `dfN` → bảng không được lưu nên mỗi câu tự kiểm chứng — chỉ nhận map nào chạy lại truy vấn
**đã giữ** ra đúng con số đã nộp. 36/36 câu tái tạo được, không câu nào bỏ (nhân đây cũng là
bằng chứng `EXECUTION_ACCURACY` không mất điểm trên đường này).

Trên cùng 36 câu đó: **bản sửa đúng 3, bản gốc đúng 0**, và không câu nào bản gốc đúng mà bản
sửa làm sai. Nên nợ "`graph.py` giữ `arevise` chỉ vì nó chạy được, trái docstring" giờ có số:
tiêu chí giữ ấy lỏng nhưng **đáng giá tiền của nó**, không phải lỗi cần sửa. Kéo theo: arm
`no_verify` trong hàng đợi bây giờ được dự đoán **thua**, nên nó tụt xuống cuối.

Chi phí theo solver, cùng lần chạy 888 câu, để không quay lại tranh luận này:

| solver | n | trung vị | p90 | % thời gian | đúng/nhãn `derived` | đúng/nhãn `single_cell` |
|---|---|---|---|---|---|---|
| codegen | 441 | 362s | 882s | 67.8% | 12/52 | 1/2 |
| raw_table_linker | 201 | 150s | 597s | 18.6% | 8/23 | 3/7 |
| cell_locator | 131 | 99s | 147s | 4.6% | 2/3 | 12/15 |
| selection_facts | 43 | 197s | 593s | 4.1% | 1/5 | — |
| formula_facts | 54 | 130s | 453s | 3.3% | — | 1/1 |
| raw_selection_linker | 7 | 699s | 1288s | 1.7% | — | — |

23% so với 35% trên `derived` là chênh 12 điểm với SE 11.5 điểm, z = 1.0 — **không đọc được**.
Và 24% tổng của codegen phần lớn là vì nó nhận câu khó: 383/441 câu của nó là `derived`, còn
cell_locator có 101/131 là `single_cell`. Đúng confound đã giết trục chọn bảng.

Khe hở routing trên `single_cell` thì **đóng**: 58 câu `single_cell` rơi xuống codegen đều đã
được cell_locator xem thật và từ chối có căn cứ (26 dưới ngưỡng tin cậy, 15 ô nhập nhằng, 12
không thấy ô số). Lever ngưỡng đã định giá và loại ở `c461313`: trên 7 câu bị từ chối vì ngưỡng,
ô định trả về lệch ở 6, chỉ q360 đúng — hạ ngưỡng mua 1 mất 6.

## Việc số 4: đổi thang cho đáp án dưới sàn (`scripts/rescale_below_floor.py`)

Đây là chỗ tôi tự phủ định kết luận ở Việc số 3. Ở đó tôi viết "phát hiện không đồng nghĩa
sửa được", vì các câu **vượt trần** lệch 2.6e11 tới 3.4e13, không phải lũy thừa 10. Kết luận
đó đúng cho nhóm vượt trần và **sai nếu mang sang nhóm dưới sàn**. Nhóm dưới sàn lệch đúng
một lũy thừa 10, nên một phép nhân là đủ.

Sinh ra từ việc mổ 67 câu sai bền (sai ở cả `full1012_head` và `full1012_v7`) trên tập nhãn:

| nhóm | n | sửa được không |
|---|---|---|
| tính sai thật, con số trông hợp lý | 51 | không, đây là trần thực sự |
| bỏ cuộc, đáp án 0.0 | 10 | chỉ giải lại được (Việc số 3) |
| **sai thuần hệ số thang, mantissa đúng** | **5** | **có, một phép nhân** |
| lệch dấu, gold bằng 0 | 0 | |

Năm câu đó, và hai nguyên nhân khác nhau để lại cùng một dấu vết:

```
q1004  phần trăm  codegen           ta=0.0527    gold=5.27      tỉ số chưa ×100
q772   tỷ         raw_table_linker  ta=0.0862    gold=86.25     nhận sai đơn vị nguồn, chia quá 1e3
q284   triệu      cell_locator      ta=17.47     gold=1.747e7   chia 1e6 oan, bảng đã in bằng triệu
q139   đồng       cell_locator      ta=3.177e6   gold=3.177e9   chia 1e3 oan
q748   triệu      raw_table_linker  ta=9.133e8   gold=913.29    quên chia 1e6
```

Máy đổi đơn vị `modules/solve/common/units.py` đã có và đã nối vào 13 chỗ, nên đây không phải
thiếu tính năng mà là nhận sai đơn vị nguồn của bảng. Sửa gốc là sửa detection, đắt. Sửa hậu
kỳ là một luật sàn, rẻ.

**Sàn suy từ ngữ nghĩa, không khớp từ nhãn:** một khoản mục tài chính không bằng một phần
nghìn của chính đơn vị nó được hỏi. Kiểm chéo sau khi đặt: cả 82 đáp án vàng có `unit_hint`
đều nằm trên sàn của nó, thấp nhất là `trăm tỷ` 0.11 so với sàn 0.01. `đồng` không có sàn vì
đáp án vàng của nó xuống tới 3.375.

Đo trên `full1012_head`: gắn cờ **38/1012**, đổi được **34**. Trên 3 câu có nhãn trong nhóm:
**2 sai→đúng, 0 đúng→sai**, đạt mốc đăng ký trước (đúng→sai phải bằng 0).

Tôi đã ước sai một lần ở đây rồi sửa sau khi đọc query. Ban đầu tôi coi ~12 câu có đầu vào
đúng lũy thừa 10 (`1e-9`, `2e-12`) là rác. Đọc query thì chúng là nhóm **hứa hẹn nhất**:

```
q823   round((((df4.iloc[2][...] > 40e9) + (df5.iloc[2][...] > 40e9) + ...) * 1e-09) * 1e+09, 2)
q949   round(((((df1.iloc[6][...] > 1000000) + (df...)) * 1e-12) * 1e+12, 2)
```

Đó là **đếm boolean**, tức một con số không có đơn vị tiền, mà codegen vẫn nhân hệ số thang
tiền vào. Phép nhân của luật này hoàn tác đúng cái hệ số đó và trả lại số đếm. Sáu câu q823,
q913, q949, q963, q965, q966 đều đúng khuôn này. Không câu nào có nhãn nên chưa kiểm được,
nhưng cơ chế thì đúng và vẫn một chiều.

Ước lại: +10 tới +20, cùng khoảng nhưng lý do phân bố khác.

**Vì sao arm này là phép đo sạch nhất cả tuần:** nó dùng lại y nguyên file chạy v10 và chỉ
đổi 34 câu, nên delta trên leaderboard **không chứa nhiễu run-to-run**. Mọi arm cờ đều phải
so với `sqrt(C)`; arm này không.

`pandas_query` bị bọc cùng hệ số chứ không chỉ sửa `answer`. `EXECUTION_ACCURACY` chấm bằng
cách chạy lại query, nên sửa một mình con số sẽ làm hai chỉ số lệch nhau đúng như v7/v8/v9.

**Không bắt được** q284, q139, q748: chúng lệch lũy thừa 10 nhưng vẫn nằm trong dải vàng của
đơn vị chúng (`triệu` vàng chạy 18 → 1.563e8, `đồng` chạy 3.375 → 6.497e9). Muốn bắt phải so
đáp án với ô gốc trong `pandas_query`, tức code mới, để lại sau.

## Bỏ phiếu tự nhất quán: đóng, có số

Ý tưởng: compute miễn phí nên chạy một cấu hình k lần rồi lấy đáp án xuất hiện nhiều nhất.
Tiền đề của nó là từng câu phải có tính ngẫu nhiên. Đo trên tập nhãn 119 câu:

| cặp lần chạy | cả hai đúng | lệch | lệch nếu mỗi câu là đồng xu độc lập |
|---|---|---|---|
| head vs v7 | 40 | **12** | 56 |
| head vs cell_locator | 36 | 18 | 56 |
| cell_locator vs qwen35 | 34 | 13 | 54 |
| head vs qwen35 | 30 | 23 | 54 |

Under-dispersion nặng và nhất quán qua cả 6 cặp: ~90% câu là tất định, chạy lại ra đúng cùng
đáp án. Bỏ phiếu chỉ chạm được 10% còn lại, và trên khối cả-hai-sai thì hai đáp án sai trùng
nhau 51%, tức phiếu sai cũng dồn cục.

Với `p ≈ 0.5` trên khối ngẫu nhiên và `d = 0.51`, k=3 cho
`p³ + 3p²(1-p) + p(1-p)²(1-d) = 0.56` so với `0.50`, tức +6 câu trên 1012 = +0.6pp. Dưới sàn
nhiễu ~1.0pp, mà tốn gấp 3 wall clock cho mọi arm sau đó. Không làm.

Con số này cũng nói lại một chuyện đã biết theo cách mạnh hơn: 9% churn **không phải** tài
nguyên chờ khai thác, nó là toàn bộ phần ngẫu nhiên và nó nhỏ.

## v11 lên bảng: đổi thang đáng +4 câu

| | ANSWER | EXECUTION |
|---|---|---|
| v10 | 0.3478 (352 câu) | 0.3478 (352) |
| v11 | **0.3518 (356)** | 0.3498 (354) |

+4 câu, và lần này không cần đọc qua sàn nhiễu: v11 dùng lại đúng lần chạy sinh ra v10 và chỉ
nhân hệ số cho 34 câu dưới sàn, nên **978/1012 câu giống v10 từng byte** và toàn bộ delta
thuộc về 34 câu đó. Tỉ lệ ăn 4/34 = 12%, khớp với 2/3 đo được trên tập nhãn ở mục trên.

Khe 2 câu giữa EXECUTION và ANSWER quay lại sau khi v10 đã đóng nó. **Không phải do bọc
query.** Tự chấm lại bằng chính `run_query` của repo (`modules/tools/python_exec.py:171`, đúng
hàm `build_submission.py` dùng để gác) trên cả v11 và v12: 0 câu không chạy được, 0 câu query
không tái tạo đáp án. Tôi từng báo v11 có 1 câu lệch và 6 câu gãy; con số đó sai, nó đến từ
một evaluator viết tay chặn builtins mà `SAFE_GLOBALS` cho phép và bỏ `_coerce_cell`. Nên khe
2 câu là chuyện của grader, không đọc được từ đây, và nó nhỏ hơn sàn nhiễu.

## Bảng điểm sáu arm của hàng đợi

Đọc trên tập nhãn 119 câu, nhớ SE ≈ 2.8 nên chỉ cột cuối là tín hiệu chắc:

| arm | nhãn /119 | đáp án 0.0 | rổ chắc chắn sai |
|---|---|---|---|
| `head` | 46 | 50 | 85 |
| `head_b` (chạy lại y nguyên) | 50 | 48 | 84 |
| `all_on` | 46 | **26** | **49** |
| `all_on_a` | 51 | 36 | 89 |
| `all_on_b` | 41 | 34 | 57 |
| `no_verify` | 43 | 47 | 109 |
| `qwen35` (cũ, để so) | 37 | 98 | 149 |

Không arm cờ nào tách khỏi nhiễu ở cột nhãn: cả bảy nằm trong ±2 SE của nhau trừ `qwen35`.
Cột "rổ chắc chắn sai" thì tách được, và `all_on` thắng rõ ở đó (49 so với 85). Đó là lý do
nó đứng thứ hai trong thứ tự ưu tiên của việc số 5.

## Việc số 5: lấp chéo giữa các arm (`scripts/fill_from_arms.py`)

Hàng đợi quét để lại **6 lần chạy đủ 1012 câu, tức 6 đáp án độc lập cho mỗi câu, đã trả tiền
GPU rồi**. Logic rổ chắc chắn sai tổng quát hóa sang đây với 0 GPU thêm: mỗi ô chắc chắn sai
của `head` lấy đáp án đầu tiên KHÔNG chắc chắn sai từ các arm khác, theo thứ tự ưu tiên
`retry` → `all_on` → `head_b` → `all_on_a` → `all_on_b` → `no_verify` (hai cái cuối xuống chót
vì cả hai đo được là tụt trên tập nhãn).

Ba tiêu chí "chắc chắn sai" giờ gộp lại một chỗ, cả ba không cần nhãn:

| tiêu chí | nguồn |
|---|---|
| `== 0.0` | hằng số bỏ cuộc, `graph.py:1174` |
| vượt trần đơn vị | `retry_pool.BAND` |
| dưới sàn đơn vị | `rescale_below_floor.FLOOR` |

Vì sao một chiều, lập luận không đổi: thay một đáp án chắc chắn sai bằng một đáp án sai khác
thì điểm y nguyên, nên arm này không có mặt âm và không phải so với `sqrt(C)`.

**v12 = đổi thang rồi lấp chéo.** Đo được:

| | |
|---|---|
| ô chắc chắn sai còn lại của `head_rescaled` | 89/1012 |
| lấp được | **77** (12 câu không arm nào cứu) |
| nguồn | retry 57, `all_on` 16, `all_on_b` 2, `head_b` 1, `all_on_a` 1 |
| trên các câu có nhãn | **3 sai→đúng, 0 đúng→sai**, 13 sai→sai |
| tổng câu đổi so với v11 | 77 |
| tập nhãn | **51/119** so với 46 của `head` |

Cộng 34 câu đổi thang của v11 là 111 câu bị chạm, với 5 thắng 0 thua trên 19 câu có nhãn
trong đó. Ngoại suy hai tỉ lệ ấy ra 111 câu cho khoảng +20 tới +25 câu, tức trên hẳn sàn
0.81pp. Mốc đăng ký trước: `đúng→sai` phải bằng 0, có câu nào tụt là tiêu chí báo oan.

Thứ tự có đảo được: lấp-trước-rồi-đổi-thang cũng cho đúng 51/119. Chọn đổi-thang-trước vì lập
luận nhân quả mạnh hơn, nó hoàn tác đúng một hệ số cụ thể trong một query đã đọc, thay vì đổi
sang đáp án của solver khác.

Số 0.0 còn lại tụt từ 50 xuống **7**, rổ chắc chắn sai từ 85 xuống **12**. Đường này gần như
đã cạn: muốn lấp thêm phải có arm mới, hoặc tiêu chí mới.

## v12 lên bảng, và trần của MỌI cách chọn giữa các arm

| | ANSWER | EXECUTION |
|---|---|---|
| v11 | 0.3518 (356 câu) | 0.3498 (354) |
| v12 | **0.3696 (374)** | **0.3676 (372)** |

**+18 câu**, và như v11 nó không cần đọc qua sàn nhiễu: 935/1012 câu giống v11 từng byte nên
+18 thuộc hết về 77 câu đã lấp. Tỉ lệ ăn 23%, dự đoán trước là +20 tới +25.

Rồi đo trần của cả hướng này, miễn phí, chỉ đọc lại các lần chạy đã có:

| | tập nhãn 119 |
|---|---|
| v12 | 51 |
| **ít nhất một arm đúng (oracle)** | **63** |

Chọn hoàn hảo giữa 7 arm chỉ còn +12 câu. Nên hướng chọn gần cạn, và hai phép đo dưới đây
xác nhận theo hai đường khác nhau.

**Bộ chọn theo phiếu: chết.** Thay đáp án của v12 khi nó lẻ loi và có cụm arm đông hơn:

| ngưỡng cụm | câu có nhãn bị chạm | sai→đúng | đúng→sai | ròng |
|---|---|---|---|---|
| ≥2 arm | 19 | 3 | 2 | **+1** |
| ≥3 arm | 6 | 1 | 2 | −1 |
| ≥4 arm | 3 | 0 | 1 | −1 |
| ≥5 arm | 2 | 0 | 1 | −1 |

Ngưỡng càng chặt càng tệ, tức "đông arm đồng ý" không mang thông tin về đúng sai. Khớp với
`d = 0.51` đã đo: đáp án sai dồn cục.

**Chồng đổi-thang + lấp-chéo lên từng arm nền.** Cột phải là cái quan trọng:

| nền | thô /119 | +thang +lấp |
|---|---|---|
| `head` | 46 | 51 (= v12) |
| `all_on` | 46 | 47 |
| `all_on_a` | 51 | **55** |
| `head_b` | 50 | 53 |
| `all_on_b` | 41 | 45 |
| `no_verify` | 43 | 47 |
| `voted` (đa số 7 arm) | 53 | **55** |

Hai kết luận. Một, hai lever cộng vào **mọi** nền, +1 tới +5, trung bình +3.3, nên chúng không
phụ thuộc nền. Hai, bỏ phiếu **không** hơn arm nền tốt nhất: cả hai đúng 55. Nên +4 của v13 so
với v12 là chuyện đổi nền, không phải chuyện bỏ phiếu, và mục "bỏ phiếu tự nhất quán" ở trên
vẫn đúng cả với bỏ phiếu giữa các cấu hình khác nhau, không chỉ giữa các lần chạy lại.

Và chú ý cái bẫy: `head` = 46 với `head_b` = 50 là **cùng một cấu hình**. Chênh 4 câu ở cột
"thô" là nhiễu thuần. Nên không được chọn nền bằng tập 119 câu. v13 nộp với nền `voted` vì nó
bằng điểm mà tiên nghiệm tốt hơn: nó không cược vào một arm nhiễu. Leaderboard quyết.

**v13** = bỏ phiếu → đổi thang (28 câu) → lấp chéo (23/34 ô). Đổi 258/1012 câu so với v12, và
trên 28 câu có nhãn bị chạm thì 5 sai→đúng, 1 đúng→sai. Đây là arm **hai chiều** đầu tiên từ
v10, nên nó có thể tụt, khác v11 và v12.

## v13 lên bảng, và hai chỗ tôi đọc sai phải sửa

| | ANSWER | EXECUTION |
|---|---|---|
| v12 | 0.3696 (374 câu) | 0.3676 (372) |
| v13 | **0.3893 (394)** | **0.3874 (392)** |

**+20 câu** từ một arm hai chiều. Hai sửa lại:

**Bỏ phiếu giữa các cấu hình khác nhau CÓ tác dụng**, đáng +20 trên 258 câu bị đổi. Tập 119
câu chỉ thấy +4 (z = 1.4) nên tôi đã gọi nó là chưa chứng minh được. Mục "bỏ phiếu tự nhất
quán: đóng" ở trên vẫn đúng cho cái nó nói tới, chạy lại **cùng** cấu hình, nhưng không được
suy sang bỏ phiếu giữa các cấu hình khác nhau. Hai chuyện khác nhau: cái đầu chỉ chạm 10% câu
không tất định, cái sau chạm mọi câu mà các cấu hình có ý kiến khác nhau.

**Trần oracle 63/119 là trần trên TẬP NHÃN, không phải trên đề.** Tập nhãn dễ hơn đề thật:
v12 ăn 42.9% ở đó so với 37.0% trên bảng. Quy tỉ lệ về 1012 câu thì oracle rơi vào khoảng 46%,
tức **còn khoảng 65 câu** đầu bàn cho hướng chọn, không phải 12. Câu "hướng chọn gần cạn" là
sai.

Bài học về dụng cụ đo, và nó là bài học đắt nhất tuần: **tập 119 câu không lái được hướng
chọn.** Ba lần nộp gần nhất đọc +4, +18, +20 trên bảng, trong khi tập nhãn lần lượt đọc +2,
+5, +4. Cùng dấu nhưng bé hơn một bậc về độ tin cậy. Cách dùng nó đúng là **so cặp** giữa hai
biến thể gần nhau, vì lúc đó SE là `sqrt(số câu lệch)` chứ không phải 2.8.

### Trọng số theo solver: đo được, không dùng được

Gộp 7 arm cho 833 cặp arm-câu, đủ N để xếp hạng solver:

| solver | đúng/nhãn | tỉ lệ | lượt trên mọi arm |
|---|---|---|---|
| `formula_facts` | 6/6 | 100% | 319 |
| `raw_selection_linker` | 3/3 | 100% | 170 |
| `cell_locator` | 78/103 | **75.7%** | 788 |
| `raw_table_linker` | 75/211 | 35.5% | 1373 |
| `codegen` | 111/352 | 31.5% | 2962 |
| `selection_facts` | 6/30 | 20.0% | 302 |
| `structured_facts` | **0/25** | **0.0%** | 243 |

Bốn luật chọn có trọng số, so cặp với v13:

| luật | nhãn /119 | đổi so v13 | thắng | thua |
|---|---|---|---|---|
| cụm đông nhất, đại diện theo ưu tiên arm (= v13) | 53 | 0 | - | - |
| cụm đông nhất, đại diện là solver tốt nhất trong cụm | 53 | 8 | 0 | 0 |
| bỏ cụm, lấy thẳng solver tốt nhất | 49 | 243 | 1 | **5** |
| trọng số cụm = tổng điểm solver | 51 | 84 | 0 | **2** |

**Cỡ cụm áp đảo chất lượng solver.** Đóng nhánh trọng số. Cảnh báo phải kèm: bảng xếp hạng
solver đo trên đúng tập dùng để chấm, nên điểm nhãn của ba luật dưới là **thiên vị lên**, mà
chúng vẫn thua.

## Việc số 6: `structured_facts` làm tiêu chí chắc chắn sai (v14)

0/25 với N = 25 là chặn trên 11% ở mức 95%. Solver này sinh **79 câu** trong v13. Thay chúng
bằng arm khác (trung bình ~35%) là EV dương rõ, và nó gần một chiều theo đúng nghĩa của các
lever v11/v12: nền gần như chắc chắn sai.

| | |
|---|---|
| ô `structured_facts` trong v13 | 79 |
| lấp được từ arm khác | **64** |
| trên các câu có nhãn | 6 câu bị chạm, **0 đúng→sai**, 0 sai→đúng |
| v14 đổi so với v13 | 63/1012 |

Nhãn không nói được gì ở đây (0/6 thắng, mà 35% × 6 kỳ vọng 2, nên `p = 0.075`: yếu). Lập
luận là EV, không phải phép đo. Thêm `selection_facts` (20%) vào tiêu chí không đổi gì, cùng
64 ô, nên giữ luật đơn giản.

Sau v14 thì rổ chắc chắn sai còn **11 ô** và không arm nào cứu được. Đổi thang còn 0 câu.
Đường hậu kỳ trên 7 arm hiện có đã cạn thật; muốn tiếp phải có **arm mới**.

## Header lệch cột: con số cũ của tôi sai gấp 6 lần

Tôi từng viết 187 câu bị lỗi lệch header. Sai. Bộ dò đó đọc CSV thô, nên nó đếm cả những
bảng repo đã sửa xong và đếm cột nhãn dòng `Unnamed: 0` bình thường như một khuyết tật.

Đo lại sau `load_frame`, tức là đúng chỗ mô hình nhìn thấy:

- Dấu hiệu cứng, câu hỏi tên một cột số mà nhận về chữ: **31/1012 câu**.
- Dấu hiệu cơ học, còn một cột `Unnamed:` ở vị trí > 0 vẫn mang dữ liệu: **145/1012 câu**,
  rải trên **171/1365 bảng** mà lượt v13 thực sự truy vấn.
- Trên tập nhãn, nhóm trích các bảng đó đúng 7/21 = 33%, phần còn lại 48/98 = 49%.
  Khoảng cách 16pp nhưng n = 21 nên sai số rất rộng.

171 bảng đó có hai hình dạng khác nhau, và mỗi hình cần một hàm riêng.

**Dòng 0 là hàng header thứ hai, các leaf dồn sát trái** (144 bảng, 117 câu).
`repair_shifted_multilevel_header` bỏ qua vì phép tìm biên nhóm của nó đòi leaf đầu lặp lại
đúng một lần cho mỗi cột có tên, tức là mọi cột có tên phải là một nhóm. Layout bất đối xứng
phổ biến lại là ba cột đơn cộng một nhóm. `repair_group_leaf_header` xử lý ca này.

**Dòng 0 là dữ liệu thật, mọi dòng lệch phải một ô** (26 bảng, 30 câu, hình của q214).
`repair_right_shifted_columns` xử lý ca này.

Chốt an toàn cho phép gán leaf theo vị trí: **đúng một cột có tên được nằm trong vùng leaf**.
Hai cột trở lên nghĩa là các nhóm có bề rộng, và vị trí không còn nói được leaf nào thuộc nhóm
nào. `ACB_financial_statements_2019_separate|97` là phản ví dụ đã buộc tôi thêm chốt này: dòng
0 mang `Quá hạn`, `Trong hạn` và chú thích đơn vị `Đơn vị: Triệu VND`, còn `Quá hạn` thật ra
trải hai trong tám dải kỳ hạn. Không có chốt, nó sinh ra tên `Đơn vị: Triệu VND | Đến 1 tháng`.

An toàn kiểm ba đường. Hai hàm mới chỉ chạy sau khi hai hàm cũ từ chối, và cả hai đòi một cột
mang dữ liệu vẫn còn thiếu tên, nên bảng đang được sửa đúng thì không đổi. Đo trên cả 1365
bảng: 115 bảng đổi, và **không bảng nào** trong đó trước đây đã có tên cho mọi cột mang dữ
liệu. `scripts/build_submission.py:227` tự đóng gói `load_frame(tid).to_csv(...)` vào bài nộp,
nên người chấm chạy query trên đúng bảng đã sửa, đổi tên cột không thể gây `KeyError` lúc chấm.

Kiểm end to end trên q214: ô từng trả về chuỗi `'VI.1'` giờ trả `1.283930e+13`, và
`1.283930e+13 / 1e11 = 128.39` khớp gold đúng từng chữ số.

Hai test đổi kết quả nhưng là cải thiện, không phải hồi quy, và tôi đã kiểm bằng `git stash`
trước khi sửa test. Trên `NVL_financial_statements_2022_consolidated|8` cột so sánh từ
`Unnamed: 4` thành `Tại ngày 31 tháng 12 năm | 2021 VND`, nên `column_years` thôi suy năm
(nó cố ý trả `{}` khi mọi cột tiền đã tự mang năm) và `build_candidates` chỉ còn trả kỳ được
hỏi. Dòng header rác rời khỏi vị trí 0 nên chỉ số dòng lùi một.

Khuyết còn lại, ghi vào commit chứ không sửa: bản sửa của tôi kích hoạt trên
`FTS_financial_statements_2018|22` và gán tiền tố nhóm `Số đầu năm` cho 4 cột nó không sở hữu
(9 cột dữ liệu trên 5 tên header). Cả trạng thái cũ và mới đều không thỏa check đang fail sẵn ở
đó, nên đây không phải hồi quy, nhưng cũng chưa phải đúng.

Commit `73c1516`. Tham số nhiệt độ và seed (`LLM_TEMPERATURE`, `LLM_SEED`) commit `ed49141`.

### Phạm vi chạy lại, và mốc đăng ký trước khi xem số

Prompt hiển thị bản xem trước bảng dựng từ `load_frame`, nên mọi câu **truy xuất** một bảng đã
đổi đều có thể đổi đáp án, không chỉ 103 câu trích dẫn một bảng. Phạm vi thật là **385 câu**.

Chạy lại với env rỗng, tức đúng cấu hình của arm `head`, để so cặp sạch với
`full1012_head.jsonl`. Trên 385 câu đó: v13 có 5 ô đáp 0.0 và 8 ô chắc chắn sai, 55 câu có
nhãn, v13 đúng 21/55 (38%) và `head` đúng 17/55 (31%).

Mốc đăng ký trước, gọi D là số câu có nhãn mà tính đúng sai khác nhau giữa hai lượt, Net là
(sai thành đúng) trừ (đúng thành sai):

- Nhận đổi hai chiều toàn bộ 385 đáp án chỉ khi **Net ≥ √D**.
- Không đạt thì dùng một chiều qua `fill_from_arms.py`, chỉ lấp ô chắc chắn sai, cộng thêm
  lượt này làm một phiếu nữa trong bầu chọn đã sinh ra v13.
- Cửa không cần nhãn, hướng cứng: số câu có `errors` chứa `could not convert string to float`
  hoặc `KeyError` **không được tăng**. Tăng là bằng chứng bản sửa làm hỏng đường đọc bảng, bất
  kể điểm nhãn nói gì.

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

- `docs/l5_screening_cause_2026-08-23.md` chưa viết. 27 id lớp L5 đã có. Tôi từng đoán q214 và
  q336 bị heuristic phân tier theo text gán sai; với q214 thì đoán đó sai, nguyên nhân thật là
  header lệch phải một ô, đã sửa ở `73c1516`. 26 id còn lại chưa truy nguyên.
- `tests/test_query_execution.py` có 2 lỗi có sẵn, chưa đối chiếu với `ebbe531`. Đã xác nhận
  giống nhau từng byte trước và sau công việc phiên này.
- `docs/CELL_LOCATOR_STATUS.md` còn khuyến nghị "giữ cờ OFF", lạc hậu từ `119729d`.
- `graph.py` giữ kết quả `arevise` mỗi khi nó chỉ cần chạy được, trái với docstring của chính
  nó. Chờ quyết định.
- `DEEPINFRA_API_KEY` đã bị in ra transcript ở một phiên trước và cần rotate, dù giờ không
  dùng tới nữa.
- `/home/ding/.config/last30days/.env` đang 644, nên là 600.
