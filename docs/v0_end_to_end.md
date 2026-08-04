# V0 End-to-end — runner và baseline kết hợp

Nhật ký của khối nối retrieval và planner thành một luồng. Khối retrieval được ghi
riêng ở `docs/v0_retrieval_pipeline.md`; ở đây chỉ nói về phần *nối* và về những
failure chỉ xuất hiện khi nối.

## Runner

`src/finance_qa/pipeline/run.py`, entrypoint `scripts/run_pipeline.py`.

```text
questions_enriched.jsonl
  → CandidateRetriever.build_pools    (hard filter + BM25 + dense + RRF + primary)
  → CandidateRetriever.select         (LLM judge chọn bảng evidence)
  → planning.generator.generate       (symbolic plan → pandas → answer)
  → submission_item                   (shape của submission_rule.txt)
  → execution.query.validate          (schema + chạy lại query, so với answer)
```

Không có logic retrieval/planning nào được viết lại trong runner; nó chỉ gọi API và
ghi lại chuyện gì xảy ra ở stage nào.

Ba quyết định của runner:

- **Per-stage errors, không chết cả batch.** Mỗi câu ghi `status` ∈
  `ok`/`invalid`/`error` cộng `stage` (`retrieve`/`plan`/`validate`) và text
  exception. `invalid` tách khỏi `error` có chủ ý: `invalid` là *đã ra item* nhưng
  item đó không qua được schema — việc phải sửa khác hẳn.
- **Resume append-only.** Đọc JSONL lấy record **cuối** cho mỗi id, nên retry chỉ
  cần append; `--retry-failed` chạy lại các id có record cuối không `ok` mà không
  phải sửa file tay. Không có `--resume` thì runner từ chối overwrite.
- **Concurrency lễ độ.** Query encode của GPU batch trên main thread (một
  `build_pools` mỗi chunk 32 câu); chỉ LLM call fan-out, ở đúng mức 4 workers mà
  các thí nghiệm judge dùng, vì vLLM là service dùng chung.

Judge trả `[]` được coi là **call fail, không phải "không có bảng nào liên quan"**,
nên fallback về thứ tự retrieval thay vì submit item không có evidence; record giữ
cờ `judge_fallback` để không lẫn với một judge thành công.

`relevant_tables` là mọi bảng đưa cho planner, còn `evidence` chỉ gồm frame mà query
thật sự đọc (`validate` yêu cầu evidence ≡ biến của query). Retrieval được chấm
riêng, nên bỏ một bảng retrieve đúng chỉ vì planner không dùng đến là tự bỏ recall.

Test: `tests/test_pipeline_run.py` (39 check, không data/GPU/LLM) — judge và planner
bị thay bằng stub để provoke từng failure mode trực tiếp.

## Baseline kết hợp trên 15 câu table-GT (2026-08-04)

`scripts/run_pipeline.py --ids <15 câu> --output artifacts/runs/pipeline_gt15.jsonl`,
mặc định (judge thinking, planner `thinking=False`, `verify=False` — giống
`evaluate_planner`, để số so được với baseline GT-table).

| | GT tables | Retrieved tables |
|---|---:|---:|
| correct | **15/15** | **7/15** (46,7%) |
| ra được item hợp schema | 15/15 | 12/15 |
| throughput | 6,2 s/câu (tuần tự) | ~20 s/câu (4 workers) |

Judge đưa trung bình 3,7 bảng/câu; có ít nhất một bảng GT trong input planner ở
10/15 câu, nhưng **đủ toàn bộ GT chỉ ở 8/15** — và đây mới là ngưỡng planner cần cho
câu multi-table, nên 8/15 là chặn trên thực tế của accuracy hiện tại, không phải
10/15. Trong 12 câu `ok`, 10 câu dùng symbolic planner và 2 câu rơi xuống
direct-code fallback — trên GT tables planner coverage là 100%, tức bảng lạ cũng đẩy
planner ra khỏi đường chính.

Lưu ý đọc latency: `mean_latency_seconds` trong summary là 40,5 giây — đó là *span
của từng câu*, đã gồm thời gian chờ trong pool 4 worker. ~20 giây/câu là throughput.
Ngoại suy thô cho 1.012 câu ở 4 workers: khoảng 5–6 giờ.

Vì planner giải đúng cả 15 khi có GT tables, toàn bộ 8 câu mất đều nằm ở khớp nối.
Nhưng chia ra thì **không phải cả 8 là lỗi retrieval**:

| qid | level | GT trong input | Chuyện gì xảy ra |
|---|---|---|---|
| 100 | L1.2 | 0/1 | bảng khác chứa **đúng** số; planner tự chia thêm 1e6 → 700,886434 thay vì 700886434 |
| 363 | L6.1 | 0/7 | judge miss hoàn toàn, planner không ra JSON |
| 524 | L6.2 | 3/5 | thiếu 2 bảng, binding trỏ vào ô rỗng |
| 582 | L3.2 | 0/2 | judge miss, ra số sai dấu và sai độ lớn |
| 752 | L4.1 | 0/2 | judge lấy `|78`/`|91` thay vì `|8`/`|8`; ra `3903526` khi đáp án là `-3903526` |
| 754 | L4.2 | 0/2 | judge miss, ra `6,01e-06` |
| 818 | L5.1 | **5/5** | đủ và đúng bảng, vẫn fail (xem dưới) |
| 820 | L5.2 | 4/5 | thiếu 1 năm → trung bình lệch |

### q818: cùng bảng, khác thứ tự, mất đáp án

q818 nhận **đúng 5 bảng GT, không có distractor nào** (`set(pick) == set(GT)`). Khác
biệt duy nhất so với run GT-table là thứ tự: judge trả 2020, 2021, 2018, 2023, 2024
còn eval set xếp chronological, nên `df1..df5` map sang bảng khác.

- run GT-table: `'Số cuối kỳ'` cho 2018 và `'Số cuối năm | Số cuối năm'` cho 4 năm
  còn lại, `.mean()`, rồi `/1e6` ⇒ 145,134 ✓
- run pipeline: chọn `'Số cuối năm | Số đầu năm'` — **số đầu năm thay vì cuối năm** —
  với `.iloc[9]`/`.iloc[13]`, tổng rồi `/5` và **không đổi đơn vị**. Hai trong năm ô
  đó rỗng (`df2.iloc[9]`, `df5.iloc[13]`) ⇒ `nan`.

Mọi cột trong query đó **đều tồn tại**; lỗi là chọn sai cột và sai hàng, không phải
bind vào cột không có. (Bản trước của ghi chú này nói cột `'Số cuối năm'` không tồn
tại — sai.)

Thí nghiệm có control để tách order-sensitivity khỏi nondeterminism của LLM: cùng
question text, cùng 5 bảng, chỉ đổi thứ tự, 3 lần mỗi thứ tự.

| thứ tự | kết quả |
|---|---|
| chronological (GT) | 145,134 — **3/3 đúng**, không lệch lần nào |
| judge trả về | **0/3**, `IndexError: single positional indexer is out-of-bounds` |

Biểu thức sai cụ thể đổi giữa các lần (`nan` trong run gốc, `IndexError` ở đây) nhưng
luôn vỡ. Vậy thứ tự bảng *là* nguyên nhân, không phải sampling.

Tức là **15/15 của baseline GT-table không robust**: permute cùng một tập bảng đã đủ
làm mất một câu. Đây là lý do cụ thể, không phải suy đoán, để mở rộng eval set trước
khi tune tiếp prompt (việc số 5 trong HANDOFF §7) — bộ 15 câu đang đo cả sampling
noise lẫn thay đổi thật.

### Hai class failure đáng sợ hơn miss

- **Sai im lặng.** q752 và q582 chạy được, ra scalar hữu hạn, qua `validate`, và
  sai. q752 còn ra đúng độ lớn chỉ lệch dấu. Không có tín hiệu nào ở phía runner để
  phát hiện — chỉ eval mới thấy.
- **Unit conversion trùng.** q100 chứng minh invariant "compiler sở hữu unit
  conversion" chưa được giữ chắc khi planner đọc bảng không phải bảng GT: nó thêm
  `/1000000.0` vào một ô đã ở đơn vị đồng.

Cả hai đều là failure mới, sinh ra từ luồng end-to-end, đúng loại tín hiệu mà
HANDOFF §7 nói hãy chờ trước khi làm decomposition planner. Chúng chỉ về phía
**bảng nào được chọn** và **binding/unit của planner**, không về phía decomposition.

### Đọc số này cho đúng

46,7% là baseline của *pipeline hiện tại trên 15 câu*, không phải kỳ vọng
leaderboard: bộ 15 câu được chọn vì có table-GT và numeric label, không phải sample
đại diện của 1.012 câu; và planner đã được tune trên chính 15 câu này.
