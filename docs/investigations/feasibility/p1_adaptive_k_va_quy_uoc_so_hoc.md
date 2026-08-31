# Đánh giá khả thi — Phương án 1: adaptive k và quy ước số học BTC

Điều tra read-only, không sửa code. Ngày 2026-08-21.

## Kết luận

- **Nhánh A (adaptive k) — trả lời dứt khoát câu hỏi "k nào":** r2ai không có khâu
  codegen/solve (repo refactor không có `solve/`/`verify/`), nên `k = 2×ndoc` của họ đo
  trực tiếp trên cái **sẽ được nộp**, không có khâu nào cắt tiếp sau nó. Ánh xạ đúng sang
  repo chính là **k của `table_ids`/`relevant_tables`** (đường judge → `_evidence()` →
  `state["table_ids"]` → `build_submission.py`), **KHÔNG phải `codegen_max_tables`**. Hai
  đường này tách nhau tường minh: `load_evidence()` chỉ cắt bản sao cục bộ để hiển thị cho
  codegen, không đụng `state["table_ids"]` — nguyên văn "Loading does not narrow
  `state['table_ids']`, which is what gets submitted: retrieval is scored on its own F2"
  (`src/finance_qa/agents/finance/graph.py:34-38`); `relevant_tables` trong file nộp lấy
  thẳng từ `table_ids` chưa cắt (`scripts/build_submission.py:78,90,215`), còn
  `codegen_max_tables` chỉ slice một biến cục bộ trong `generate_pandas`
  (`graph.py:114-131,136-144`). Vậy đề xuất "k=2×ndoc" và số đo "3→10 làm tệ hơn" của team
  lead là **hai lever khác nhau trên hai tầng khác nhau, không mâu thuẫn nhau** — nhưng
  đúng vì thế, nhánh A **không khả thi ở tầng nó thực sự áp dụng được (`table_ids`)**: tầng
  đó bị chấm bởi `TABLES_F2MACRO`/`TABLES_MRR5`, và `TABLES_F2MACRO` đã bị chốt là **0.0 do
  lệch hệ đánh số bảng với BTC, không phải do k** (`docs/leaderboard_and_strategy_2026-08-21.md:41-58`,
  11 lượt submit, kết luận "không dò thêm TABLES") — tăng/giảm hay làm thích ứng k của
  `table_ids` là tối ưu một số hạng đang bị nhân với 0. DOCS thì đã 0.9488 F2 / 0.9661 MRR5,
  gần bão hoà, còn rất ít khoảng vượt sàn nhiễu.
  Về phía `codegen_max_tables` — **không phải là nơi áp k=2×ndoc, và cũng không nên tăng
  thêm**: đã đo ngược hướng (3→10: coverage 37→47/73 nhưng tổng đúng giảm 33→29,
  `config.py:198-209`), và cơ chế "chọn tên" thay cho "nhồi grid" mà nhóm đã chọn
  (`common/lookup.py`, `find_rows`) **đã được thử làm đúng vai trò rescue nhóm bị cắt bởi
  cap và đo là không cứu được** — xem chi tiết ở dưới. Hai số đo độc lập này cùng chỉ một
  hướng: đừng chạm `codegen_max_tables*`.
- **Nhánh B (quy ước số học):** **khả thi, và một phần đã có bằng chứng cụ thể để sửa.**
  Quy ước số VN + số âm ngoặc đã cài đúng (`numeric.py`). Quy ước "không hướng → trị
  tuyệt đối" **chưa có code nào nhận diện** — `intent.py` có `DIFF_CUE_STRICT/LOOSE` cho
  "chênh lệch" nhưng không phân biệt có-hướng/không-hướng, và `structured_facts.py`
  operation `"diff"` luôn trả `a - b` theo thứ tự cố định, không bao giờ lấy abs. Đã xác
  nhận trên artifact: q526 là sign-flip thật (không phải suy đoán). Quy ước "làm tròn kết
  quả cuối 2 chữ số" **không được code nào thực thi mặc định** (`round_digits` là field
  optional do LLM tự set, mặc định `None`) — nhưng vì `score_gold75.py` dùng dung sai
  tương đối 1% (`TOL=0.01`), làm tròn hay không hầu như không ảnh hưởng số đo nội bộ; có
  ảnh hưởng đến điểm thật của BTC hay không là điều **chưa biết** (không có tài liệu nào
  nói dung sai chấm điểm chính thức).

## Hiện trạng đã đọc được

### Nhánh A

**Judge / pool (repo chính):**
- `MAX_PICKS = 10` — cap số bảng judge được chọn — `src/finance_qa/modules/rag/judge.py:34`.
- `judge_top_n` là tham số của `CandidateRetriever.__init__`, mặc định `None` (judge đọc
  cả pool) — `src/finance_qa/modules/rag/candidates.py:202,236-239`. Giá trị **thực chạy**
  là **20**, đặt cứng trong `FinanceAgentConfig.judge_top_n: int = 20` —
  `src/finance_qa/agents/finance/config.py:34` — và truyền xuống qua
  `src/finance_qa/agents/finance/retrieve.py:20`. Đây là **hằng số cố định, không phụ
  thuộc số ticker/năm của câu hỏi** — đúng hình dạng "k cố định" mà r2ai đo là kém hơn.
- Sau judge, `_evidence()` nối thêm **vô điều kiện** mọi báo cáo chính (`balance_sheet`,
  `income_statement`, `cash_flow`, `equity_change`) trong pool mà judge chưa chọn —
  `src/finance_qa/modules/rag/service.py:82-90`. Đây là lý do đúng như đề bài nêu: k của
  judge (10, hoặc 20 cho những gì judge thấy) **không phải con số cuối** — độ dài
  `table_ids` cuối cùng phụ thuộc số báo cáo chính có trong shortlist, có thể phồng lên
  rất lớn (đo được ở dưới: max 84/73 câu).
- `add_primary_statements()` — cơ chế nối, không cắt — `src/finance_qa/modules/rag/candidates.py:120-137`.

**Khâu hiển thị bằng chứng cho codegen (khác khâu trên, ít người để ý — và tách biệt khỏi
`table_ids`/`relevant_tables` nộp bài, xem `graph.py:34-38` ở trên):**
- `codegen_max_tables: int = 3` (câu 1 năm) và `codegen_max_tables_multi_year: int = 5`
  (câu nhiều năm) — `src/finance_qa/agents/finance/config.py:211,221`. Chọn qua
  `state.get("multi_year")` — `src/finance_qa/agents/finance/graph.py:139-144`.
  `load_evidence()` chỉ cắt biến cục bộ `ordered = table_ids[:max_tables]`
  (`graph.py:123`), không viết lại `state["table_ids"]`.
- Đã **đo và ghi lại ngay trong comment** (`config.py:198-209`): nâng `codegen_max_tables`
  3→10 tăng coverage 37→47/73 nhưng **tổng điểm đúng giảm 33→29** vì mô hình lẫn giữa các
  bảng gần-trùng (cùng công ty/năm, khác note). Đây là bottleneck khác hẳn F2 IR-thuần mà
  r2ai đo: ở ta, thêm bảng làm downstream LLM **tệ hơn**, không chỉ trung lập.
- Với câu nhiều năm (period question), coverage vẫn thấp (19% ở k=3) và **bão hoà ở
  42-44% dù k=5, 12, hay cả pool** (`config.py:210-215`) — nghĩa là phần thiếu ở nhóm này
  không phải "không đủ chỗ", mà là bảng đúng không vào được tập được xếp hạng đưa tới đó
  ngay từ đầu — thứ mà tăng k không sửa được.
- **Hướng đã chọn thay cho "nhồi thêm grid": `find_rows`/`search_rows`
  (`src/finance_qa/modules/solve/common/lookup.py:1-21`) — với tay tới bảng khác *bằng
  tên*, trả giá prompt chỉ cho dòng quay về.** Nhưng cơ chế này (vòng lặp tool-call trong
  `generate_pandas`, `codegen.py:236`) chỉ chạy khi `codegen_tool_turns > 0`, và **mặc
  định production là `codegen_tool_turns = 0`** (`config.py:293`) — nguyên văn "0, and
  measured: it did not work" — đã thử với `turns=3` trên 94 câu (43/94 so với 42/42 hai
  baseline, trong sàn nhiễu), và quan trọng nhất cho nhánh A: **6 câu bị cắt đúng bởi
  table cap không nhích được** — "the 6 questions whose gold table was cut by the table
  cap stayed exactly as they were (4 wrong, 3 of those after spending all 3 lookups)"
  (`config.py:282-292`). `codegen_show_grids` (bật mặc định, `config.py:311`) cũng đã đo
  ngược lại — ẩn grid để buộc dùng `find_rows` làm tệ hơn nhiều (25/94 so với 42/94,
  `config.py:301-310`).
  **Hệ quả cho đề xuất "tăng `codegen_max_tables_multi_year` thích ứng" ở mục Việc cần
  làm dưới đây:** đây là phép đo độc lập thứ hai (khác phép đo 3→10) cùng chỉ một hướng —
  cho nhóm câu bị cắt bởi cap, cả "cho xem tên hàng qua `find_rows`" và ngụ ý "cho xem
  toàn bảng qua nới cap" đều chưa có bằng chứng nào cứu được nhóm này; đề xuất đó cần hạ
  mức tin cậy xuống rõ ràng, không nên gọi là "khả thi có điều kiện" nữa mà là "chưa có cơ
  sở để tin sẽ thắng, nhưng đo mô tả (không sửa code) vẫn rẻ và nên làm trước khi quyết."

**r2ai (`ai-finance-stage-2-refactor`):**
- `PER_DOC = 2`, `k = 2 × n_docs` với `n_docs = len(DocSelection.docs)` —
  `src/r2ai/retrieve/topk.py:1-60`. `n_docs` đến từ **B1 — một khâu LLM riêng biệt**
  (`resolve/docselect.py`, đo doc accuracy ≥98%, thực tế 95,8%) đã resolve
  `(ticker, year, scope) → doc_id`, KHÔNG phải từ khâu xếp hạng B2. Ba biến thể đã thử và
  loại: chặn theo doc (0,6475, hoà), `a + 2×ndoc` (luôn tệ hơn), k theo số ô (mã,năm)
  (0,653, không đáng thêm khái niệm).
- Đơn vị "doc" trong r2ai = một báo cáo `(ticker, year, scope)` đã resolve — gần tương ứng
  với `len(tickers) × len(years)` mà `understand` node của ta đã có sẵn trong `state`,
  KHÔNG phải một khái niệm mới cần xây.
- Kết quả đo (`SPEC.md` quanh dòng "Đã dựng xong tầng 3+4"): pool BM25+primary-expansion
  recall 0,969; + judge → F2 0,673; + cấu trúc doc vào prompt → 0,725; + bù doc bị judge
  bỏ trắng → **0,742**, dưới cửa chặn 0,80. r2ai **không có TABLES_MRR5** trong bảng đo
  của B2 — MRR5 của họ chỉ đo ở B1 (doc-level), không phải bảng.

**Điểm khác biệt cấu trúc quan trọng nhất giữa hai repo (lý do chính sách không chuyển
thẳng được):** r2ai tách "chọn doc" (B1, LLM, đo doc-accuracy riêng) và "chọn bảng trong
doc" (B2, k=2×ndoc, đo F2). Repo chính không có khâu B1 tương tự — hard filter
(ticker×year×doc_type) đã làm việc đó nhưng không sinh ra một số "ndoc" tường minh được
truyền xuống bất kỳ nơi nào tính k; và `_evidence()` sau đó lại làm một việc r2ai không
làm: nối bù báo cáo chính **vô điều kiện, không theo tỷ lệ ndoc nào cả**.

### Nhánh B — 4 quy ước BTC (nguyên văn từ slide, `fitz` extract)

**p31:**
> "Định dạng số địa phương: Dấu chấm '.' làm phân cách hàng nghìn ('15.230.000'), dấu
> phẩy ',' làm số thập phân ('12,5%'). Giá trị âm dạng đóng ngoặc: '(500.000)' tương
> đương với '-500.000'. Đơn vị đo lường biến đổi: Triệu VNĐ, Tỷ VNĐ, USD thay đổi tùy
> theo từng bảng."

**p34 (CoT):**
> "Semantic Conventions: Chênh lệch không hướng → lấy giá trị tuyệt đối không âm; có
> hướng → giữ nguyên dấu. Rounding Rule: Không làm tròn trung gian; chỉ làm tròn kết quả
> cuối cùng 2 chữ số thập phân."

**p35 (PoT):**
> "Semantic Rules: Lấy giá trị tuyệt đối không âm khi tính toán chênh lệch giữa hai giá
> trị; có hướng → giữ nguyên dấu. Reliability Rules: ... không làm tròn số trung gian,
> gán đáp án số vào result."

Lưu ý: bản PoT (p35) không lặp lại chữ "không hướng" như bản CoT (p34) — câu PoT đọc như
"lấy tuyệt đối khi tính chênh lệch, [trừ khi] có hướng thì giữ dấu", cùng ý nhưng kém rõ
hơn CoT về việc *ai* quyết định câu hỏi có hướng hay không. Đây là quy ước BTC viết, không
phải điều ta suy ra.

**Đối chiếu với code:**

1. **Số VN + số âm ngoặc** — ĐÃ CÀI ĐÚNG. `parse_number()` xử lý `(500.000)` → âm, phân
   biệt `.`/`,` theo heuristic 3-chữ-số-nhóm — `src/finance_qa/modules/tools/numeric.py:12-38`.
2. **Đơn vị đổi theo bảng** — ĐÃ CÀI, khá kỹ. `src/finance_qa/modules/solve/common/units.py`
   phát hiện đơn vị từ banner/tên cột/khai báo trang, tách biệt "đơn vị bảng khai" và
   "đơn vị model tự nhận" (`resolve_source_unit`, dòng 187-201, cố ý không tin model đoán
   scale). `codegen.py` (CODEGEN_SYSTEM, dòng 101-104) cấm model tự nhân/chia đơn vị.
3. **Chênh lệch không hướng → trị tuyệt đối** — **KHÔNG CÓ AI XỬ LÝ**, ba mảnh liên quan:
   - `intent.py:65-66` có `DIFF_CUE_STRICT`/`DIFF_CUE_LOOSE` nhận diện câu "chênh lệch" —
     nhưng chỉ để định tuyến sang solver nào, **không có khái niệm hướng** (không có
     `DIRECTION_CUE` hay tương tự) trong toàn file (đọc hết `__all__`, không có).
   - `structured_facts.py:1146-1154` (operation `"diff"`) luôn tính `answer = a - b` theo
     thứ tự cố định (`tickers[0] - tickers[1]`, hoặc `years[-1] - years[0]`) — không có
     nhánh nào gọi `abs()` cho trường hợp không hướng.
   - Có một cơ chế `abs` khác trong `cell_locator.py:202-212` (`value_transform`,
     `_MAGNITUDE_METRIC`/`_SIGNED_METRIC`) — nhưng đó là cho **một ô đơn** (chi phí âm in
     trên báo cáo → đọc như giá trị dương), **không phải** cho chênh lệch giữa hai ô, và
     `build_request()` (dòng 224) tự loại các câu có `_DERIVED_MARKER` (so sánh/derived)
     khỏi solver này — nên cơ chế abs đó không bao giờ chạm vào câu "chênh lệch giữa hai
     giá trị". Với các câu chênh lệch rơi vào `codegen`, `CODEGEN_SYSTEM`
     (`src/finance_qa/modules/solve/codegen/codegen.py:64-118`) chỉ nói "một câu hỏi so
     sánh ... cần nhiều ô" — không có một dòng nào về dấu hay trị tuyệt đối. `verify.py`
     (`Verdict`) chỉ chấm ô/hàng/cột có đúng không, không chấm dấu.
4. **Không làm tròn trung gian, tròn kết quả cuối 2 chữ số** — **không được code enforce**.
   `structured_facts.py:1171-1172`: `round_digits` là field optional
   (`structured_facts.py:403,515`, `default=None`), chỉ tròn khi chính LLM đặt ra số chữ
   số — không có mặc định "=2" ở bất kỳ đường ra nào. `codegen.py` không có instruction
   nào về tròn số ở cả input (system prompt) lẫn output. `scale_expression`/`units.py`
   không tròn. **Không tìm thấy nơi làm tròn trung gian sai** (không có `round()` áp lên
   một bước tính trung gian trước bước cuối) — nên rủi ro "tròn quá sớm" hiện không xảy
   ra; rủi ro thực là "không tròn kết quả cuối" nhưng — xem phần đo — dung sai 1% nội bộ
   khiến điều này khó lộ ra ở `score_gold75.py`.

## Bằng chứng đo được

**Phân bố `len(diag.evidence_tables)` — 73 câu, `artifacts/runs/gold73_qwen35_planner.jsonl`
(đo bằng script tạm, đọc trực tiếp field `diag.evidence_tables`):**

| số bảng đưa cho codegen | số câu |
|---:|---:|
| 0 | 8 |
| 1 | 17 |
| 2 | 4 |
| 3 | 23 |
| 4 | 1 |
| 5 | 20 |

Trung vị 3, trung bình 2,71, **20/73 (27%) chạm đúng nắp trần 5** (nhóm multi-year) — dấu
hiệu có thể đang mất bảng ở đuôi phân bố, nhưng không thể khẳng định thiếu bao nhiêu chỉ từ
số này (không biết ndoc thật của 20 câu đó).

**Phân bố `len(table_ids)` (bảng đã nộp/dùng để scoring TABLES/DOCS) — cùng file:**
trung vị 14, trung bình 18,21, **max 84** (câu id 17, một câu ngân hàng 1-ticker-1-year với
7 bảng trong ví dụ đọc tay). Khoảng cách giữa hai phân bố (3 vs 14 trung vị) là khoảng cách
giữa "bảng judge/pool trả về" và "bảng codegen được thấy" — hai khâu khác nhau, hai hằng số
khác nhau (không có k thích ứng ở khâu nào).

**Sign-flip trên 73 câu gold** (đo bằng script tạm, so `pred` trong
`gold73_qwen35_planner.jsonl` với `data/eval/{unbiased60,manual15}_gold.jsonl`,
`TOL=0.01` như `score_gold75.py`): 21 câu sai, đúng **1/21** là sign-flip sạch
(`abs(pred) == abs(gold)`, dấu ngược) — đó là **q526** (`pred=-83.790676915`,
`gold=83.790676915`). 20/21 câu sai còn lại không phải lỗi dấu.

**Đếm từ khoá thô trên 1.012 câu** (`ViFinQA/questions/questions.jsonl`, script tạm,
`norm()` copy từ `intent.py`) — **ước lượng thô, không phải nhãn tay:**

| cue | số câu khớp |
|---|---:|
| `DIFF_CUE_STRICT` (`chenh lech`/`hieu so`/`hon`) | 194 |
| `DIFF_CUE_LOOSE` (thêm `kem`, `so voi`) | 230 |
| chỉ `"chênh lệch"`/`"khác biệt"` (bỏ `hơn` — từ quá phổ biến, nhiều nghĩa khác) | 95 |
| trong số đó, không có từ chỉ hướng rõ (`tăng`/`giảm`/`cao hơn`/`thấp hơn`) đi kèm | 89 |

Đọc số này cẩn thận: 89/1.012 (~8,8%) là *cận trên thô* của "câu có thể thuộc dạng chênh
lệch không hướng" — dùng từ khoá tiếng Việt không phân biệt được ngữ nghĩa thật (một câu
có "chênh lệch" vẫn có thể ngầm có hướng qua ngữ cảnh khác). Không có nhãn tay nào xác nhận
tỷ lệ chính xác.

## Việc cần làm, ước lượng

### Nhánh A

1. **Không làm gì cho k của judge/`_evidence`** — đây chính là tầng mà `k=2×ndoc` của r2ai
   *sẽ* ánh xạ tới nếu áp dụng (xem Kết luận), nhưng trước khi biết chắc TABLES đã hết cách
   sửa thật (kết luận đã chốt trong `docs/leaderboard_and_strategy_2026-08-21.md`, không lặp
   lại điều tra). DOCS đã 0,9488 F2 — biên độ cải thiện tối đa khả dĩ nhỏ hơn sàn nhiễu của
   phép đo tổng hợp (aggregate leaderboard), khó tách bạch khỏi nhiễu submit-to-submit.
   **Verify nếu vẫn muốn thử:** đo trên `unbiased60`/`gold94` bằng
   `scripts/gate_retrieval_full.py` (không gọi model ngoài nếu `--arms` không chọn
   reranker/LLM) trước/sau khi đặt `judge_top_n` hoặc thêm hệ số theo
   `len(tickers)*len(years)`; đối chiếu delta F2/MRR5 với sàn nhiễu đã biết của công cụ đó
   (chưa đo — cần đo sàn nhiễu riêng của `gate_retrieval_full` trước khi đọc bất kỳ delta
   nào).
2. **`codegen_max_tables_multi_year` thích ứng — hạ xuống mức "đo mô tả trước, chưa đề
   xuất sửa code":** hai phép đo độc lập đã có (3→10 nói chung: điểm giảm 33→29,
   `config.py:198-209`; và `find_rows` — cơ chế "với tay bằng tên" đã được chọn thay grid —
   thử đúng trên nhóm bị cắt bởi cap và không cứu được, `config.py:282-292`) cùng chỉ ra
   rằng "cho model thấy nhiều hơn" ở khâu này chưa từng thắng. Vì vậy bước tiếp theo hợp lý
   không phải là sửa `codegen_max_tables_multi_year` ngay, mà là:
   - Đo trước (không sửa code): trong 73 câu gold, bao nhiêu câu multi_year có
     `ndoc_ước_lượng = len(tickers)×len(years) > 5`, và trong nhóm đó bao nhiêu câu **đã**
     từng được thử qua `find_rows` (`SOLVE_TOOL_TURNS>0`) mà vẫn sai — nếu trùng nhiều với
     6 câu ở `config.py:282-292`, đó là bằng chứng trực tiếp rằng nới cap cũng sẽ không cứu
     được nhóm này (cùng nguyên nhân: bảng gần-trùng gây nhiễu, không phải thiếu chỗ).
   - Chỉ nếu số đo trên cho thấy có câu KHÁC với 6 câu đã thử-và-thất-bại (tức còn câu chưa
     ai thử nới cap/tool cho) mới đáng cân nhắc một thử nghiệm nới cap, và phải giữ đúng kỷ
     luật cũ: chỉ chạy trên đúng nhóm câu đó, so với sàn nhiễu 2 câu, đo lại cả 73 câu để
     bắt hồi quy ở nhóm đơn-năm.
   - **Tiêu chí verify nếu vẫn làm:** lệch ≥3 câu đúng mới đáng giữ (vượt sàn nhiễu 2 câu
     có biên an toàn), không làm tệ nhóm đơn-năm.
   - **Rủi ro đã biết trước khi bắt đầu (không còn là suy đoán, là số đo trên chính nhóm
     mục tiêu):** cơ chế "nhiều bảng/thông tin hơn = mô hình lẫn" đã đo dương tính hai lần
     liên tiếp (grid rộng hơn nói chung, và find_rows trên đúng nhóm cap-cut) — nên kỳ vọng
     hợp lý cho nới cap trực tiếp là **thất bại giống hai lần trước**, không phải "chưa
     biết".

### Nhánh B

1. **Sign/direction cho "chênh lệch"** — việc rõ ràng nhất, phạm vi nhỏ nhất, có bằng chứng
   cụ thể (q526). Bước:
   - Thêm một cue trong `intent.py` phân loại câu "chênh lệch" có kèm từ chỉ hướng
     (`tăng/giảm/cao hơn/thấp hơn/tang truong`) hay không — tận dụng `GROWTH_CUE`,
     `DIFF_CUE_*` đã có, không hardcode câu hỏi/đáp án nào.
   - Ở `structured_facts.py` operation `"diff"` (dòng ~1146): khi câu hỏi không có cue
     hướng, bọc `answer = abs(a - b)`; khi có, giữ `a - b` như hiện tại.
   - **Verify đo được:** chạy lại 73 câu gold, so số đúng trước/sau — đặc biệt xác nhận
     q526 chuyển ĐÚNG và không câu nào trong 52 câu đang đúng bị hỏng (nguy cơ: một số câu
     "tăng/giảm" bị cue mới bắt sai thành không-hướng). Đối chiếu với sàn nhiễu 2 câu:
     nếu chỉ +1 (chỉ q526), đó nằm trong nhiễu và không đủ để khẳng định cue đúng — cần áp
     đúng logic cho câu hỏi khác có "diff" mà hiện đang đúng, xem có giữ đúng không (đo
     hồi quy, không phải suy đoán).
   - Việc **không làm được bằng dữ liệu hiện có:** không có nhãn tay "câu nào có hướng,
     câu nào không" ngoài q526 — nên không biết tỷ lệ lỗi thật trong 89 câu ước lượng thô
     ở trên. Muốn biết chắc phải đọc tay một mẫu (ví dụ 20-30 câu trong nhóm 89) rồi mới
     quyết định cue có đáng thêm hay không — đây là việc riêng, ngoài phạm vi "chỉ sửa
     q526".
2. **Rounding cuối 2 chữ số** — việc nhỏ, rủi ro thấp, lợi ích chưa rõ vì `TOL=0.01` nội
   bộ đã che phần lớn khác biệt do không-tròn. Bước nếu vẫn muốn làm: tại điểm build
   submission (`scripts/build_submission.py`), `round(answer, 2)` một lần, ngay trước khi
   ghi ra — không sửa bất kỳ bước tính trung gian. **Verify:** so `score_gold75.py` trước/
   sau, kỳ vọng delta = 0 (vì dung sai 1% đã che), nên đây là việc "làm cho đúng chính tả
   với đề bài" hơn là việc có thể đo được cải thiện nội bộ. Câu hỏi "có ảnh hưởng điểm thật
   của BTC không" — **không biết**, vì không có tài liệu về dung sai chấm điểm chính thức
   của BTC.

## Rủi ro và điều chưa biết

- **Không biết dung sai chấm điểm `ANSWER_ACCURACY` thật của BTC** (exact-match sau khi họ
  tự parse, hay có dung sai số?). Nếu là exact-match nghiêm ngặt theo 2 chữ số, việc không
  làm tròn có thể đang mất điểm âm thầm ở một số câu mà `score_gold75.py` (dung sai 1%)
  không bao giờ thấy được. Không có cách kiểm chứng bằng dữ liệu sẵn có — chỉ có thể đo
  qua một lượt submit thật, và team lead đã nói rõ không chạy gate tốn tiền/model trong
  việc điều tra này.
- **Không biết ndoc thật (số ticker×năm cần) của 20 câu multi-year chạm nắp 5** — chỉ đo
  được rằng chúng chạm nắp, chưa đo được chúng cần bao nhiêu. Việc ở Nhánh A #2 phải đo cái
  này trước khi sửa code, không suy đoán.
- **Ước lượng 89/1.012 câu "chênh lệch không hướng"** là đếm từ khoá thô, không phải nhãn
  ngữ nghĩa — số thật có thể thấp hơn (một số câu "chênh lệch" thực ra có hướng ngầm qua
  ngữ cảnh) hoặc cao hơn (một số câu không dùng chữ "chênh lệch"/"khác biệt" mà vẫn hỏi một
  khoảng cách không hướng, ví dụ "A và B khác nhau bao nhiêu"). Không nên dùng số này để
  định lượng tác động, chỉ để định lượng phạm vi cần đọc tay.
- **Nhánh A phần judge/`_evidence`**: mọi thay đổi ở đó đổi `relevant_docs`/`relevant_tables`
  — tức đổi cả DOCS_F2MACRO đang cao (0,9488) — rủi ro làm giảm một số đã tốt để đổi lấy
  một số đã chết (TABLES). Đây là lý do chính khiến khuyến nghị là **không đụng vào k của
  judge**. `codegen_max_tables_multi_year` là khâu tách biệt (không ảnh hưởng TABLES/DOCS
  scoring) nên an toàn hơn về mặt rủi ro-lan-toả, nhưng **không nên coi là lựa chọn dự
  phòng chắc thắng**: hai số đo độc lập đã có trên đúng loại thay đổi này (3→10 nói chung,
  và `find_rows` trên đúng nhóm cap-cut) đều âm tính — xem mục Hiện trạng/Nhánh A. Việc duy
  nhất nên làm ngay là đo mô tả (không sửa code) để biết nhóm 20 câu chạm nắp có trùng với
  6 câu đã thử-và-thất-bại hay không, trước khi cân nhắc bất kỳ thử nghiệm sửa code nào.
- **Chưa đọc `capability_router.py` / `raw_table_linker.py` / `raw_selection_linker.py`**
  trong phạm vi điều tra này — nếu các solver đó có logic diff/sign riêng (ngoài
  `structured_facts.py`), cue mới ở Nhánh B #1 cần áp cả ở đó, chưa kiểm tra.
