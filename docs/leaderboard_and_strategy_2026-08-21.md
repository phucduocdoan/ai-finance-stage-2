# Leaderboard v7, cấu hình solver, và định hướng theo slide BTC

Ngày 2026-08-21. Ghi lại ba thứ: kết quả submit v7, phát hiện về config default, và
những gì slide BTC (`docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf`, 44
trang) nói mà ta chưa dùng.

## 1. Kết quả leaderboard

`output/submission_solver_v7/submission.json` (build 2026-08-19 01:00 từ
`artifacts/runs/full1012_v7.jsonl`):

```
TABLES_F2MACRO  0.0       DOCS_F2MACRO   0.9488   ANSWER_ACCURACY    0.3043
TABLES_PRECISION 0.0      DOCS_PRECISION 0.9279   EXECUTION_ACCURACY 0.3024
TABLES_RECALL   0.0       DOCS_RECALL    0.9649
TABLES_MRR5     0.0       DOCS_MRR5      0.9661
```

So với bản trước (carrier của sổ dò TABLES):

| | trước | v7 | Δ |
|---|---|---|---|
| DOCS_F2MACRO | 0.9268 | 0.9488 | +0.0220 |
| DOCS_PRECISION | 0.9525 | 0.9279 | −0.0246 |
| DOCS_RECALL | 0.926 | 0.9649 | **+0.0389** |
| DOCS_MRR5 | 0.9631 | 0.9661 | +0.0030 |
| ANSWER_ACCURACY | 0.2628 | 0.3043 | **+0.0415** |
| EXECUTION_ACCURACY | 0.2628 | 0.3024 | −0.0019 vs ANSWER |

Hai điều đọc được:

- **DOCS đổi vì `_evidence` đổi.** `relevant_docs` là `dedupe_reports(_evidence(...))`,
  và `_evidence` = judge picks + primary statements của shortlist. Solver stack khác
  ⇒ `table_ids` khác ⇒ tập report khác. Recall +0.039 đổi lấy precision −0.025, đúng
  hướng F2 (β=2, recall nặng gấp 4).
- **`EXECUTION_ACCURACY` (0.3024) giờ thấp hơn `ANSWER_ACCURACY` (0.3043).** Trước
  đây hai số bằng nhau. Chênh 0.0019 ≈ 2 câu: có 2 câu answer đúng mà `pandas_query`
  chạy lại không ra đúng số đó. Đây là hệ quả của solver hẹp — chúng tính bằng Python
  deterministic rồi *sinh* một `pandas_query` mô tả lại phép tính. Cần audit.

### TABLES = 0.0 không phải bug format

Tôi đã đọc sai tín hiệu này lúc đầu. `docs/tables_metric_probes.md` ghi **11 lượt
submit** đã tiêu để dò đúng câu hỏi đó. Kết luận đã chốt ở đó:

- Dạng chuỗi `{report_id}|{số nguyên}` **là đúng** (bản D2 giết cả 6 biến thể
  `|table_N`, `_table_N.csv`, …).
- `relevant_tables` của ta = ordinal thẻ `<table>` thô, đã verify: 146.246 thẻ đếm lại
  từ 1.973 file OCR == 146.246 dòng metadata, 0 lệch trên 1.965 report.
- Số của gold **không bao giờ ≤ M** (M = max table_pos của report) và **không bao giờ
  là 0** ⇒ hệ đánh số của ta không thể khớp. ~87% số gold > 300.
- Ví dụ `AAA_..._2015_consolidated|350` trong `submission_rule.txt` là **số bịa** —
  report đó chỉ có 47 bảng.
- Trần thực tế nếu dò ra: ~0.11 TABLES_F2MACRO, đóng góp aggregate ~+0.02.

Sổ đó kết luận: sau H1/H2 không dò thêm lượt nào cho TABLES. **Giữ nguyên kết luận
đó.** H1/H2 đã build sẵn (`output/submission_probeH1_301_600.zip`,
`submission_probeH2_d1_plus_td.zip`) nhưng chưa nộp.

## 2. Config default đang bỏ mất 13/73 câu

Đo trên 73 câu gold (`scripts/score_gold75.py`), checkpoint `Qwen3.5-9B`, tree
2026-08-21. Sàn nhiễu = **2 câu** (run 08-18 chạy lại config y hệt: 54 → 52).

| arm | env | điểm | solver mix |
|---|---|---|---|
| default | — | **39/73** (53.4%) | codegen 73 |
| +4 solver | `SOLVE_CELL_LOCATOR`, `SOLVE_FORMULA_FACTS`, `SOLVE_RAW_TABLE_LINKER`, `SOLVE_SELECTION_FACTS` | **47/73** (64.4%) | rtl 9, cl 7, ff 6, sf 2, codegen 49 |
| +planner | thêm `SOLVE_RAW_TABLE_LINKER_PLANNER` | **52/73** (71.2%) | rtl 17, cl 8, ff 6, sf 2, codegen 40 |
| best lịch sử 08-18 | (như trên) | 54/73, repeat 52 | rtl 16 |

Artifact: `gold73_qwen35.jsonl`, `gold73_qwen35_flagson.jsonl`,
`gold73_qwen35_planner.jsonl`.

Head-to-head default vs +4 solver: 10 tốt hơn / 2 tệ hơn. +4 vs +planner: 6 tốt hơn /
1 tệ hơn. Cả hai vượt xa sàn nhiễu 2.

**Truy nguyên gap 47→52 bằng diag, không đoán:** router quyết định **giống hệt** hai
arm (`raw_table_linker: {"enabled": true, "attempt": true}`), nên linker *có* thử rồi
fail-closed. Lý do in ra:

- `"ratio raw linker requires planner"` — q355, 663, 685, 693, 955
- `"deterministic raw linker: slot-wise top candidates are not strong enough"` — q744,
  754, 833, 856

Bật planner là 9 câu quay lại `raw_table_linker`, mix khớp best lịch sử (17 vs 16).

Mọi flag trong `FinanceAgentConfig` mặc định `False` với ghi chú "opt-in while
measured". Hệ quả thực tế: ai chạy default nhận 39/73, và số đo tốt chỉ tồn tại trong
biến môi trường của người chạy. `full1012_v7` đã nộp có cả `raw_selection_linker` (30
câu) — flag này *không* có trong arm 52/73 ở trên.

**Đã làm (2026-08-21):** 5 flag đã đo thành default `True` trong
`src/finance_qa/agents/finance/config.py`, kèm cả bảng số đo trên vào comment. Verify
bằng cách dựng `FinanceAgentConfig()` không env: default giờ trùng khít arm 52/73.
`raw_selection_linker` **vẫn `False`** — và ghi rõ trong comment rằng đó là *thiếu số
đo*, không phải một số đo. `SOLVE_<NAME>=0` vẫn cho arm control cho mọi A/B sau này.

Toàn bộ test suite chạy theo đúng cách nó được thiết kế (mỗi file là một script
assertion độc lập) đều pass. `pytest tests/` vẫn lỗi collection ở
`test_table_linking_columns.py` — đã xác nhận **có sẵn từ trước**: lỗi y hệt khi export
5 flag về `0` để dựng lại default cũ, và file chạy riêng thì `tất cả PASS`. Đây là rò rỉ
state giữa các module trong cùng process pytest, không liên quan tới thay đổi này.

## 3. Checkpoint swap không giúp gì cho answer

| | top-3 retrieval (u60/g94) | answer 73 câu |
|---|---|---|
| `Qwen3.5-9B-Opus-Distilled-v2` | 26 / 54 | 38/73 (`full1012_qwen35`, all-codegen) |
| `Qwen3.5-9B` | 47 / 75 | 39/73 (`gold73_qwen35`, all-codegen) |

Retrieval top-3 tăng **+21 câu mỗi set**, answer tăng **1 câu** — dưới sàn nhiễu.
Xác nhận trực tiếp: **retrieval ordering không còn là bottleneck.**

## 4. Slide BTC — những gì ta chưa dùng

### 4.1 PoT vs CoT ở dưới 10B (p39) — dữ kiện quan trọng nhất

BTC đo 14 LLM. Với mọi mô hình <10B, **CoT thắng PoT**:

| model | PoT | CoT | Δ |
|---|---|---|---|
| Qwen3-4B-Instruct | 4.64% | 11.56% | **+6.92% CoT** |
| Qwen2.5-Coder-7B | 0.30% | 9.49% | **+9.19% CoT** |
| Granite-4.1-3B | 2.08% | 9.09% | **+7.01% CoT** |

Và: *"Mô hình nhỏ <10B → crash code: Tỷ lệ lỗi cú pháp PoT lên đến **99%**."*

Ta đang chạy **Qwen3.5-9B — dưới 10B — và 100% PoT**. Đã verify: không có một
reference nào tới CoT/direct-answer trong toàn bộ `src/finance_qa`.

Sắc thái phải nói rõ: PoT của ta **không** naive — có repair loop, verify_answer, và 5
solver deterministic. Nên ta đạt 0.3043 chứ không phải 2–5% như bảng trên. Nhưng
hướng thì rõ và chưa từng được đo ở repo này.

### 4.2 Embedder ta đang dùng là loại yếu nhất trong bảng của họ (p26)

Recall@10 table retrieval trên ViFinQA theo BTC:

| method | Recall@10 |
|---|---|
| BM25 | 47.41% |
| **BGE-M3** | **53.05%** ← ta đang dùng |
| Qwen3-Embedding-4B | 63.90% |
| Qwen3-Embedding-8B | 67.48% |
| Qwen3-Embedding-4B + Reranker | 80.19% |
| Qwen3-Embedding-8B + Reranker | 80.80% |

Chênh bge-m3 → Qwen3-Emb-8B là **+14.4 điểm recall@10**. Nhưng đối chiếu với đo lường
của chính ta (§10.5-10.6 của `retrieval_preprocessing_2026-08-21.md`): thay đổi
ordering dense bị reranker xoá sạch, và không convert end-to-end. Nên đây là ứng viên
đáng đo, không phải việc chắc thắng.

### 4.3 Bottleneck theo BTC (p37, p40)

Oracle vs retrieved evidence:

| setting | CoT | PoT |
|---|---|---|
| Oracle (gold tables cho sẵn) | **87.0%** | 76.0% |
| Retrieved (k=10) | 64.0% | 62.0% |
| drop | −23.0% | −14.0% |

Phân tích 430 ca lỗi end-to-end (DeepSeek-V4-Flash, PoT):

| mã | loại | % |
|---|---|---|
| E | **Numerical Extraction** (đọc sai ô/dòng/cột) | **54.7%** |
| I | Insufficient Evidence (retriever thiếu bảng) | 34.7% |
| T | Technical/Syntax (crash code) | 9.3% |
| C | Numerical Calculation | 0.9% |
| F | Formula Application | 0.5% |

*"LLMs không dốt toán, vấn đề là chọn sai ô số liệu."* Và p42: *"Cơ chế Cell Grounding
là trọng tâm."* Solver `cell_locator` của ta chính là cái này, nhưng chỉ fire 8/73.

### 4.4 Phân tầng độ khó (p32, p38)

| level | count | share | mô tả |
|---|---|---|---|
| Easy | 361 | 35.7% | truy xuất 1 giá trị từ 1 bảng |
| Medium | 235 | 23.2% | 2 giá trị + 1 phép tính |
| Intermediate | 200 | 19.8% | >2 giá trị, nhiều phép tính/gom nhóm |
| Hard | 216 | 21.3% | multi-hop dependent: kết quả trung gian quyết định bảng/kỳ tiếp theo |

Accuracy tụt Easy 84.5% → Hard 32.9%. Ta không có routing theo độ khó.

### 4.5 Model collaboration (p41)

Planner (frontier) → Coder (code LLM) → Auditor (verifier). Ta có `understand` →
`generate_pandas` → `verify_answer`, cùng một mô hình cả ba vai. BTC tách vai bằng ba
model khác nhau.

### 4.6 Quy ước số học BTC nêu rõ (p31, p34, p35)

- Số VN: `.` phân cách nghìn, `,` thập phân; `(500.000)` = −500.000.
- Đơn vị đổi theo bảng (triệu/tỷ VNĐ/USD).
- **Chênh lệch không hướng → lấy trị tuyệt đối không âm; có hướng → giữ dấu.**
- **Không làm tròn trung gian; chỉ làm tròn kết quả cuối 2 chữ số thập phân.**

Cần đối chiếu 4 quy ước này với `verify_answer` và các solver — nhất là quy ước trị
tuyệt đối và làm tròn 2 chữ số, vì chúng ảnh hưởng trực tiếp tới so khớp đáp án.

## 5. Đo PoT vs CoT — giả thuyết p39 không tái lập được ở 9B

`scripts/gate_cot.py`. Phạm vi hẹp có chủ ý: 5 solver deterministic không viết code nên
PoT-vs-CoT không nói gì về chúng; chỉ **40 câu rơi xuống `codegen`** là tranh chấp.
Evidence được giữ **cố định** bằng cách replay `diag.evidence_tables` từ arm 52/73 — đúng
những table id mà codegen đã thấy, đúng thứ tự — nên biến duy nhất là chiến lược suy
luận. Arm PoT lấy free từ artifact. Prompt CoT theo đúng contract p34.

| arm | hit/40 | scraped | off-by-1000× |
|---|---|---|---|
| PoT (control) | **22** | 0 | 0 |
| CoT | **23** | 5 | 1 |
| CoT (lần 2) | **23** | 2 | 1 |

**Sàn nhiễu CoT-vs-CoT = 4 câu.** Chênh PoT→CoT là **1 câu**, tức nằm sâu trong nhiễu.
Kết luận: **ở checkpoint này CoT không thắng PoT.** Bảng p39 của BTC không tái lập —
gần như chắc vì PoT của ta không naive (repair loop + `verify_answer` + 5 solver), đúng
như sắc thái đã ghi ở §4.1. Và một submission all-CoT còn không có `pandas_query`, nên
`EXECUTION_ACCURACY` sẽ về ~0 (đang 0.3024). Gate này đo trần trả lời, không phải một
thay thế cắm-vào-là-chạy.

### 5.1 Nhưng hai chiến lược *bù* nhau, và "đồng thuận" là tín hiệu sạch

Trùng nhau chỉ 15/40. Union **30/40**: CoT đúng 8 câu PoT sai, PoT đúng 7 câu CoT sai.

| | agree | correct | precision |
|---|---|---|---|
| CoT lần 1 | 15/40 | 15 | **100%** |
| CoT lần 2 | 17/40 | 17 | **100%** |

**32/32, không một false positive nào ở cả hai lần chạy.** Khi PoT và CoT ra cùng một số
thì số đó đúng. Khi lệch nhau (25/40) thì là tung xúc xắc: PoT đúng 7, CoT đúng 8, cả
hai sai 10.

Đọc kết quả này cho đúng: **agreement tự nó không cộng điểm** — trên các câu đồng thuận
PoT vốn đã đúng rồi. Giá trị nằm ở chỗ nó là **bộ phát hiện câu không đáng tin, chính xác
và rẻ**: nó khoanh đúng 25 câu (~34% của bộ 73) mà 15 câu trong đó *có* đáp án đúng nằm
sẵn ở một trong hai arm. Đó chính là nơi để tiêu một lượt gọi model mạnh làm trọng tài
(ý model collaboration p41), thay vì trải mỏng frontier-API lên toàn bộ 1.012 câu. Trần
oracle của cách này là 52 → 60/73.

Hai cảnh báo trước khi ai đó xây trên nó: n=32 là nhỏ, và agreement thiên vị câu dễ —
đó vốn là *lý do* nó hoạt động như thước đo độ khó, nhưng cũng có nghĩa 100% sẽ tụt khi
mở rộng bộ đo.

### 5.2 Hai bug đo lường đã sửa trong lúc gate (đáng ghi lại)

Cả hai đều làm CoT trông tệ hơn thực tế, và cả hai đều là lỗi *của gate*, không phải của
CoT:

1. **Parse số Việt Nam.** `Answer: 1.041.601` là 1041601, nhưng parser đầu tiên chỉ xử lý
   dấu `,` nên `float("1.041.601")` ném lỗi rồi rơi xuống nhánh scrape và lấy `1.0`. Sửa:
   ≥2 dấu `.` và không có `,` → phân cách hàng nghìn. Thêm vào prompt yêu cầu dòng cuối
   không dùng phân cách hàng nghìn. Riêng hai thứ này đưa smoke 6 câu từ 1/6 → 5/6.
2. **`max_tokens=1536` cắt ngang suy luận.** Mọi ca `scraped` đều dài 3.3–4.9k ký tự,
   tức hết token trước khi tới dòng `Answer:` — không ca nào là model phớt lờ format. Ở
   1536 tokens: arm 1 scraped 6/40 rồi arm 2 scraped 12/40 (19/40 vs 23/40, nhiễu ±4 do
   truncation). Lên **3072** thì scraped còn 5 và 2, và hai arm CoT khớp nhau ở 23/40.
   Bài học chung: CoT trên grid bảng tài chính cần ngân sách token gấp đôi PoT.

## 6. Thứ tự việc nên làm

1. ~~Đưa 5 flag solver thành default `True`.~~ **Xong** (§2).
2. ~~Đo một arm CoT.~~ **Xong** (§5): không thắng, nhưng lộ ra tín hiệu đồng thuận.
3. **Đo `raw_selection_linker` trên 73 câu.** Flag duy nhất còn `False` mà chưa có số đo;
   v7 đã nộp có nó (30/1012 câu).
4. **Audit 4 quy ước số học ở §4.6** so với `verify_answer` — lỗi làm tròn/dấu là lỗi
   im lặng, không crash.
5. **Audit chênh 2 câu `EXECUTION_ACCURACY` < `ANSWER_ACCURACY`** — solver hẹp sinh
   `pandas_query` không tái lập được đáp án.
6. **Mở rộng `cell_locator`** (đang 8/73) — đánh trực diện lớp lỗi 54.7%.
7. Trọng tài trên 25 câu PoT/CoT lệch nhau (§5.1), nếu chấp nhận gọi model ngoài.
8. Đo Qwen3-Embedding-4B/8B thay bge-m3, biết trước rằng reranker có thể xoá sạch.
9. Không dò thêm TABLES.


## 6. Khoảng cách 0.68 ↔ 0.30: gold của BTC làm tròn 2 chữ số, ta thì không

Ngày 2026-08-22. Đây là phát hiện lớn nhất từ trước tới nay của repo, và nó **đóng
được offline**, không tốn lượt submit nào.

### 6.1 Triệu chứng

Chấm chính `output/submission_solver_v7/submission.json` — đúng file đã nộp — trên
60 câu gold lấy mẫu ngẫu nhiên có seed:

| | điểm |
|---|---|
| `unbiased60` (ngẫu nhiên đều trên 1012) | **41/60 = 0.683** |
| `manual15` (hand-pick, có thiên vị) | 13/15 = 0.867 |
| leaderboard, cùng file | **0.3043** |

Không phải nhiễu: n=60, KTC 95% là [0.57, 0.80]; nếu accuracy thật là 0.3043 thì
thấy ≥41/60 là ~6.4 sigma.

### 6.2 Loại trừ

- **Đóng gói**: so từng câu `full1012_v7.jsonl` ↔ submission.json, **0 câu lệch**.
- **Nhãn gold ẩu**: 60/60 có `raw_cell_value` + `conversion` ghi tay, 53/60
  confidence `high`, đơn vị quy đổi đúng theo đơn vị câu hỏi. Người gán nhãn còn ra
  ngoài top-12 retrieval khi cần (q166 lấy `|71`, không có trong shortlist).
- **Nhiễm tập đo**: có thật nhưng không đủ — **27/75 id gold bị hardcode đích danh**
  trong `src/`, `tests/`, `scripts/` (q45 đẻ ra `units.py`; q86/q263/q280/q526 nằm
  thẳng trong `test_solve_units.py`). Đủ để thổi phồng vài điểm, không đủ 38 điểm.

### 6.3 Luật chấm nào tái lập được 0.3043

Thử 9 luật trên đúng 60 câu đó. Chỉ **một** luật khớp:

| luật chấm | unbiased60 | gộp 75 |
|---|---|---|
| rel 1e-2 / 1e-4 / round2 hai phía / \|Δ\|≤1 | 0.683 | 0.720 |
| so bằng chuỗi, hai phía thô | 0.533 | 0.533 |
| **ta thô vs gold đã làm tròn 2 chữ số** | **0.250** | **0.280** |

Leaderboard = **0.3043**. Mọi luật lỏng hơn đều ở 0.53–0.68.

Khớp với slide BTC p35, quy ước đã ghi ở §4.6 mà chưa ai đối chiếu với output:
*"Không làm tròn trung gian; chỉ làm tròn kết quả cuối 2 chữ số thập phân."*

Cơ chế: **690/1012 (68.2%) đáp án của ta mang hơn 2 chữ số thập phân**, tất cả đều là
sản phẩm của một phép quy đổi đơn vị (667 câu có ≥6 chữ số). `2077.869596655` không
bằng `2077.87`.

### 6.4 Sửa

`scripts/build_submission.py::round_final`, bật mặc định, arm control là
`--no-round-final`. Làm tròn ở khâu **đóng gói** — đó là chỗ duy nhất tôn trọng được
vế "không làm tròn trung gian".

`round` đi vào **`pandas_query`** chứ không chỉ vào con số, vì `EXECUTION_ACCURACY`
chạy lại chuỗi đó; làm tròn mỗi con số sẽ khiến hai metric lệch nhau. `abs(...)` đã
có sẵn trong 81 query của v7 và chạy được trên leaderboard, nên builtin dùng được.

Build `output/submission_v8_round2.zip` (9.9 MB, 10.921 CSV, format OK):

| | v7 | v8 |
|---|---|---|
| unbiased60, chấm theo luật §6.3 | 15/60 = 0.250 | **41/60 = 0.683** |
| gộp 75 | 21/75 = 0.280 | 54/75 = 0.720 |
| query là literal trần | 126 | **34** |

Số câu đáp án đổi giá trị: 690/1012. Chạy lại 12 query mẫu trên CSV đã đóng gói:
12/12 khớp **tuyệt đối** đáp án nộp.

### 6.5 Rủi ro, đã định lượng

Làm tròn 2 chữ số làm lệch >1% ở **57/1012** câu (|đáp án| nhỏ; phần lớn là rác sẵn:
1e-12, 1e-9). Đổi lấy ~380 câu. Và thế giới "gold đầy đủ độ chính xác + dung sai 1%"
đã bị chính con số 0.3043 loại bỏ — trong thế giới đó ta đã phải đạt 0.683 rồi.

**Dự đoán: ANSWER_ACCURACY 0.3043 → ~0.60-0.68.** Đây là dự đoán có thể sai và phải
được xác nhận bằng một lượt submit.

### 6.6 Hệ quả cho mọi số đo trước đó

Mọi A/B đo trên gold73 đều chấm bằng dung sai 1% — tức **không hề nhìn thấy lỗi làm
tròn**. Nên các kết luận so sánh *tương đối* (default 39/73 → +4 solver 47 → +planner
52; PoT ≈ CoT; retrieval không còn là nghẽn) vẫn đứng vững, nhưng mức *tuyệt đối* của
chúng chưa bao giờ là thứ leaderboard đang chấm.


## 7. Kết quả v8: +22 câu, và giả thuyết §6 bị bác bỏ

Nộp `output/submission_v8_round2.zip`:

```
ANSWER_ACCURACY    0.3043 -> 0.3261   (+0.0218, ~+22 câu)
EXECUTION_ACCURACY 0.3024 -> 0.3241   (+0.0217)
DOCS/TABLES        không đổi (đúng như thiết kế: chỉ đổi answer + query)
```

**Dự đoán ở §6.4 là 0.60-0.68. Sai, và sai lớn.** Làm tròn là một hiệu ứng thật nhưng
nhỏ: 22 câu, không phải ~380. Giả thuyết "làm tròn giải thích khoảng cách 0.68↔0.30"
**bị bác bỏ**. Sự trùng khớp 0.280 ≈ 0.3043 ở §6.3 là trùng hợp, không phải nhân quả.

Hai điều **được** xác nhận:

- `round(...)` nằm trong `pandas_query` hoạt động đúng: hai metric vẫn cách nhau đúng
  2 câu như trước (0.3261 vs 0.3241), không hề rời nhau.
- Sửa ở khâu đóng gói không làm hỏng retrieval: DOCS/TABLES y nguyên.

### 7.1 Nhưng kết quả này khoanh chặt nguyên nhân còn lại

Làm tròn chỉ có thể **mất** độ chính xác, nên một grader dung sai rộng sẽ cho **+0**.
Nó cho +22 ⇒ **grader chấm chặt**. Mà grader chặt + nhãn của ta đúng 72% thì v8 phải
ra ~0.72. Nó ra 0.326.

Kết luận buộc phải rút ra: **gold của BTC lệch với nhãn ghi tay của ta trên khoảng 40%
số câu**, và lệch vì nội dung đáp án, không vì định dạng. Đây giờ là giả thuyết duy nhất
còn sống.

### 7.2 Hai ứng viên hệ thống, đã thử, không khớp

- *"Gold theo đơn vị gốc của bảng, không quy đổi"*: `diag.units.scaled` chia 1012 thành
  429 câu có quy đổi / 583 không. Nếu đúng thì toàn bộ điểm phải nằm trong nhóm 583,
  tức 308/583 = 53%. Nhưng nhãn của ta nói nhóm đó đúng **35/47 = 74%**. Không đóng được.
- *"Chia theo số chữ số thập phân"*: 322 câu ≤2 chữ số / 690 câu >2. Không trùng với
  phân nhóm `scaled`, và nhãn của ta cho **cùng 72%** ở cả hai nhóm. Không có tín hiệu.

### 7.3 Việc tiếp theo, 0 lượt submit

Không thể chẩn đoán tiếp bằng nhãn của chính ta, vì **nhãn của ta chính là nghi phạm**.
Phép thử quyết định: **gán nhãn lại độc lập một mẫu mới nhỏ** — đọc từ text OCR gốc của
report, không đọc từ CSV đã extract, và không đi qua đường mà pipeline đi.

- nếu nhãn độc lập **trùng** nhãn cũ ⇒ gold/grader của BTC làm điều ta chưa mô hình hóa;
- nếu **lệch ~40%** ⇒ nghẽn nằm ở tầng extract bảng, khớp đúng với taxonomy của chính
  BTC (E Numerical Extraction 54.7%, p40) và với việc §6.2 đã loại trừ mọi thứ khác.

Giữ `round_final` (mặc định bật): +22 câu là thật và độc lập với việc trên.

## 8. Gán nhãn lại độc lập: nhãn của ta đúng, tập eval bị nhiễm

Giả thuyết cuối §7 — "gold của BTC lệch nhãn tay của ta ~40% về nội dung" — **đã bị bác bỏ.**

### Thiết kế
Ba agent gán nhãn mù, mỗi agent một lát 10 câu, nguồn hợp lệ duy nhất là OCR thô
`ViFinQA/**/<report_id>_extracted.txt`. Cấm đọc `data/eval/`, `output/`,
`artifacts/runs/`, `data/tables/`, `data/metadata/`, `docs/`; cấm import bất cứ thứ gì
trong `src/finance_qa`. Mỗi nhãn phải kèm `raw_cell_value`, `row_label`, `column_label`,
`ocr_quote` nguyên văn, `table_unit`, `confidence`, và cờ `contaminated` tự khai.
Agent không biết đang kiểm chứng cái gì; phần so sánh do tôi làm sau.

- **Tầng A** = 15 id rút từ `unbiased60` → phép thử nhãn-đối-nhãn.
- **Tầng B** = 15 id mới, rút từ 905 câu không nằm trong bất kỳ file gold nào và không
  được nhắc tên ở đâu trong `src`/`tests`/`scripts` → ước lượng độ chính xác sạch.

### Kết quả

| phép đo | kết quả |
|---|---|
| Tầng A: nhãn mới vs nhãn cũ | **14/15 = 0.933** (chỉ q259 lệch; agent tự khai `confidence=low`) |
| Tầng A: v8 vs nhãn mới | 10/15 = **0.667** |
| Tầng B: v8 vs nhãn mới | 4/13 = **0.308** |
| Leaderboard v8 | **0.3261** |

Hai kết luận đóng lại:

1. **Nhãn tay của ta *tái lập được*.** Hai lượt gán nhãn độc lập đọc OCR thô hội tụ 93%.
   Giả thuyết §7 (nhãn ta sai 40% về nội dung) chết.
   **Đính chính (xem §10):** "tái lập được" không phải "đúng". Cả hai lượt gán nhãn đều do
   Claude làm, nên 93% đo tính nhất quán của một mô hình, không đo tính đúng so với gold do
   người của BTC lập. Sai lệch tương quan giữa hai lượt là không quan sát được từ phép đo này.
2. **Khoảng cách 0.68 ↔ 0.33 là do nhiễm tập eval, không phải bí ẩn ở grader.**
   Tầng A tái lập đúng 0.683 đo trước đây; tầng B tái lập đúng leaderboard. Cơ chế đã
   biết: 27/75 id gold nằm hardcode trong `src`/`tests`. Pipeline được tinh chỉnh vào
   chính tập đo nó.

**Độ chính xác thật của hệ thống là ~0.25-0.33, đúng như leaderboard.** Mọi số offline
đo trên `unbiased60`/`gold75` từ giờ phải coi là vô giá trị.

### 9 câu sai ở tầng B — phân loại

| dạng lỗi | id | biểu hiện |
|---|---|---|
| Sai ô / lệch chỉ số dòng | 940, 664, 784 | đúng bảng, đúng khái niệm, sai dòng. q940 lấy nhầm dòng nên ra 772.96 thay vì 273013.36 |
| Thiếu hẳn một tài liệu | 746, 590 | q746 lấy cả hai `df` từ KHG, không hề chạm tới DXS → ra 0.0. q590 hỏi 2025 vs 2021 nhưng chỉ mở báo cáo 2021 |
| Câu sàng lọc nhiều công ty | 443 | không tính nổi chỉ số nên trả về một ô VND thô: 45.078.644 cho một câu hỏi "%" |
| Sai ô, biên độ nhỏ | 146 | 3.23 vs 4.35 trăm tỷ (nhãn `confidence=medium`) |
| Nhân đơn vị hai lần | 24 | bảng đã ở "Ngàn VND", câu hỏi hỏi "nghìn đồng", ta vẫn nhân `1e-3` |

### Quét toàn bộ 1012 câu: 23% mang dấu hiệu sai tự tố cáo

| dấu hiệu | số câu |
|---|---|
| `evidence` rỗng | 136 (13.4%) |
| `pandas_query` chỉ là một hằng số | 102 (10.1%) |
| `answer` đúng bằng 0.0 | 73 (7.2%) |
| câu hỏi %/tỷ lệ/hệ số mà \|answer\| > 1000 | 57/312 (18.3%) |
| câu hỏi "bao nhiêu lần/vòng" mà \|answer\| > 1000 | 16/51 |
| **hợp** | **234 (23.1%)** |

Phân theo số mã cổ phiếu trong câu hỏi:

| lớp | số câu | có dấu hiệu sai |
|---|---|---|
| 1 mã | 808 | 149 (18%) |
| 2 mã | 41 | 15 (37%) |
| 3+ mã (sàng lọc nhóm) | 163 | 70 (43%) |

Lớp "3+ mã" là 163 câu = 16.1% toàn đề; 32 câu không có bằng chứng nào, 63 câu chỉ có
đúng một bảng cho một câu hỏi cần đọc 3-6 công ty. Đây là lớp hỏng nặng nhất và hiện
không có solver nào nhắm vào nó.

### Hai nhãn bị loại khỏi phép đo

- **q785** — câu hỏi so HUT với "CTCP Dịch vụ Hoàng Huy", agent không tìm được nguồn cho
  vế thứ hai nên để `answer: null`. Loại.
- **q416** — câu hỏi nêu "Bình Sơn, PLX, PVT". BSR **có** trong corpus, nhưng danh sách
  `candidate_ocr_files` tôi dựng cho probe bỏ sót nó vì tôi trích mã bằng regex chữ hoa,
  còn "Bình Sơn" là tên tiếng Việt. Nhãn 0.86 vì thế chỉ so 2/3 công ty → không dùng
  được. Lỗi ở probe của tôi, không phải ở agent.

Sau khi loại hai nhãn này, tầng B = **4/13 = 0.308**, khớp leaderboard 0.3261.
Chỉ 4 câu đúng: 53, 123, 705, 743. q397 nộp `-0.0` — lại rơi vào lớp "answer bằng 0".

### Kiểm chứng phụ: gọi công ty bằng tên tiếng Việt

Lỗi probe ở q416 gợi ý pipeline có thể hỏng cùng chỗ. Đo lại: 577 câu (57.0%) gọi công ty
bằng tên tiếng Việt, trong đó **328 câu (32.4%) không kèm bất kỳ mã nào có trong corpus**.
Nhưng chỉ 38 câu trong số đó có `evidence` rỗng — tra cứu theo tên phần lớn **có** trả về
bảng. Vậy đây *không* phải nút thắt lớn như tôi tưởng lúc đầu.

Cảnh báo: "có evidence" ≠ "đúng công ty". Phần này chưa đo được nếu không gán nhãn thêm.

## 9. Tập eval sạch (đang dựng)

Mọi số offline cũ đã hỏng, nên dựng lại từ đầu.

- **Pool sạch 891 câu**: bỏ 94 id nằm trong file gold, 41 id được nhắc tên trong
  `src`/`tests`/`scripts`, 30 id đã dùng cho probe §8.
- **Mẫu 120 câu** ngẫu nhiên đều, seed 20260823, không phân tầng — để phản ánh đúng phân
  bố đề thật (trong đó 23 câu sàng lọc nhiều mã).
- Gán nhãn bởi 10 agent độc lập, 12 câu mỗi agent, cùng ràng buộc như §8.
- Cộng 13 nhãn sạch sẵn có từ tầng B → khoảng 133 câu. Ở mức p≈0.33 thì SE ≈ 4%.

### Bản đồ tên công ty → mã
Lỗi q416 ở §8 buộc phải giải bài toán này. Repo không có sẵn bản đồ. Hai cách thất bại:
trích tên từ đầu báo cáo rồi lọc văn xuôi (mất 43/100 mã, SJG ra tên sai); nới lỏng bộ lọc
(SSB dính vào gần như mọi câu). Cách dùng được: khớp cụm 2-5 từ của câu hỏi với 12 KB đầu
báo cáo của từng mã, giữ cụm chỉ thuộc 1-2 mã. Recall đủ, precision lỏng — bù bằng cách
nói rõ với agent rằng shortlist là tập thừa, phải tự loại bằng tên trên đầu báo cáo.
Artefact: `artifacts/relabel/ticker_blob.json`, `artifacts/eval_clean/tasks.jsonl`.

## 10. Kết quả tập eval sạch: 0.387

120 nhãn đã xong, 119/126 dòng truy ngược sạch về OCR bằng `scripts/audit_labels.py` (tra ngược
`report_id`, `raw_cell_value` và mọi con số trong `ocr_quote` về file gốc). 7 ca còn lại
đều giải thích được: giá trị dẫn xuất từ nhiều công ty, một câu `null` chính đáng (đề không
nêu năm), hai câu tổng do agent tự cộng vì OCR không có dòng tổng. **Không ca nào bịa số.**

| lớp câu hỏi | n | đúng | tỉ lệ |
|---|---|---|---|
| Tra một ô, một tài liệu | 82 | 42 | **51%** |
| Hai tài liệu (so sánh/chênh lệch) | 12 | 3 | **25%** |
| Sàng lọc/tổng hợp nhiều công ty | 25 | 1 | **4%** |
| **tổng** | **119** | **46** | **0.387** |

SE 0.045, KTC 95% **0.299-0.474**. Leaderboard v8 = 0.3261 nằm gọn trong khoảng.
Theo độ tin của nhãn: `high` 43/89 = 48%, `medium` 3/30 = 10%.

Dung sai không ảnh hưởng: khớp bit-for-bit 0.381, làm tròn 2 chữ số 0.390, tương đối 1% 0.390.

### Ba điều đã tuyên bố quá tay trong quá trình này, ghi lại để khỏi lặp
1. **"Nhãn tay của ta chính xác" (§8)** — sai từ ngữ. Hai lượt gán nhãn hội tụ 93% chỉ chứng
   minh *tái lập được*; cả hai lượt đều do Claude làm nên không đo được sai lệch tương quan
   so với gold do người lập.
2. **"Độ chính xác thật ~0.31" (§8)** — dựa trên tầng B n=13, quá nhỏ. Con số đúng là 0.387
   với n=119.
3. **"Khoảng cách 0.44 vs 0.326 cách nhau 2.4σ, cần giải thích bằng lệch Claude-vs-người"** —
   đo ở n=101. Khi mẫu đủ 119 thì còn 1.4σ và nằm trong KTC. Nhiễu mẫu là đủ; giả thuyết kia
   chưa cần đến. Cảnh báo về trần tin cậy của tự gán nhãn vẫn đúng, nhưng tôi đã cân nó nặng
   hơn mức bằng chứng cho phép.

Bài học chung: mọi con số dưới n≈100 trong dự án này đều đã dẫn tôi đi sai ít nhất một lần.

### Kiểm chứng tin cậy tình cờ
Sáu câu (552, 557, 559, 571, 573, 585) bị hai agent khác nhau gán nhãn trùng, do agent thứ
nhất chết vì tràn context sau khi đã ghi xong phần của nó. **Cả sáu khớp chính xác** —
150.6, 5.22, 4.19, 15.08, 1.83, 6717.66 — và đều thuộc lớp sàng lọc nhiều công ty, loại khó
nhất, nơi mỗi đáp án là kết quả của một chuỗi lọc rồi tính. Đây là phép kiểm tin cậy mạnh
nhất có được trong đợt này, và nó không hề được thiết kế.

### Điều vững chắc, bất kể chuyện nhãn
- **Sàng lọc nhiều công ty: 1/25 = 4%.** Khớp với quét toàn đề (§8: 163 câu = 16.1% đề,
  43% có dấu hiệu sai tự tố cáo). Trong mẫu 120 câu, lớp này chiếm 25 câu = 21%.
- **Hai tài liệu: 3/12 = 25%.** Dạng lỗi đã thấy ở q746 (lấy cả hai `df` từ cùng một công ty)
  và q590 (chỉ mở một trong hai năm).

Cộng lại 34/119 = 29% mẫu nằm ở hai lớp mà pipeline gần như không làm được gì, và hiện
không solver nào nhắm vào chúng. Đây là chỗ có dư địa lớn nhất.

### Công cụ để lại
- `artifacts/eval_clean/labels_*.jsonl` — 120 nhãn, mỗi nhãn kèm trích dẫn OCR nguyên văn.
- `scripts/audit_labels.py` — tra ngược nhãn về OCR, dùng lại được cho mọi đợt gán nhãn sau.
- `scripts/score_clean_eval.py` — chấm một submission, hoặc so hai submission và liệt kê
  chính xác câu nào được thêm / mất đi.
