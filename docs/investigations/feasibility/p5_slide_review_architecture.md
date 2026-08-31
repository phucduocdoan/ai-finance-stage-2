# Phương án 5 — Đọc slide deck ngày 21/8, góc nhìn kiến trúc/pipeline

Nguồn: `_2026__R2AI___Stage2___Finance_Tabular_QA___Aug21 (1).pdf` (39 trang, đọc toàn bộ
bằng trích text trực tiếp qua `pypdf`, không có `pdftoppm` nên không xem được hình minh
hoạ — nhưng nội dung là bullet point văn bản, không có bảng số nào cần xem hình để đọc).
Đối chiếu với `docs/HANDOFF.md`, `docs/feasibility/README.md` + p1-p4, và
`docs/tables_metric_probes.md` trước khi viết, theo đúng yêu cầu không lặp lại phát hiện cũ.

## Kết luận mở đầu, quan trọng hơn mọi đề xuất bên dưới

**Deck này không phải tài liệu luật chấm điểm.** Đây là một bài giảng phương pháp luận
("Day 2: Advanced Methods") tổng hợp 11 paper học thuật (MultiHiertt, HiTab, TAPAS,
TAT-QA, FinQA, PoT, PAL, Binder, Chain-of-Table, TableRAG, CLER) cộng thêm phần hạ tầng
serving (vLLM/TensorRT-LLM/SGLang, multi-LoRA, sandbox OS). **Không có một dòng nào** nói
về: dung sai so khớp số (tolerance), cách tính `TABLES_*`, định dạng `relevant_tables`,
quy ước làm tròn/đơn vị, hay phân bố loại câu hỏi của chính đề thi này. Toàn bộ ví dụ
trong deck (trang 4, 11, 12, 13) là ví dụ tự chế bằng tiếng Anh ("Operating Income
YoY", công ty X hư cấu), không phải câu hỏi thật của tập test. Việc dò `TABLES_F2MACRO
= 0.0` đã đóng lại sau 12 lượt nộp thật (`docs/tables_metric_probes.md`, kết luận
"không dò thêm lượt nào cho TABLES") — deck không cho manh mối gì để mở lại hướng đó,
**đừng tốn thêm lượt nộp nào cho TABLES vì slide này**.

Giá trị thật của deck nằm ở việc nó đặt tên tường minh cho các lỗi kiến trúc mà
`docs/tables_metric_probes.md` đã đo được nhưng chưa có khung lý thuyết: "codegen tự tay
chọn số thay vì để chương trình tổng hợp trên dữ liệu thật" đúng là triệu chứng "Hallucinated
Arithmetic" mà PAL (trang 10-11) được thiết kế để triệt tiêu, và "bảng song sinh cùng
metadata bị xếp sai" đúng là bài toán TableRAG/Hierarchical Schema (trang 8, 15) nhắm tới.
Ba đề xuất dưới đây bám theo đúng hai mạch đó — không lặp lại adaptive-k/cell_locator/tuple
planner/grid-port của p1-p4.

---

## Đề xuất 1 (ưu tiên cao nhất, an toàn trong 1.5 ngày): dạy codegen trả "năm nào" bằng idiom đã có sẵn, không phải bằng hậu xử lý

**Vấn đề, đã đo sẵn trong `docs/tables_metric_probes.md` mục "Câu hỏi 'năm nào': sai dạng
đáp án":** 53/1012 câu hỏi năm cực trị; đường `codegen` (28 câu) và `selection_facts` (7 câu)
trả về **giá trị của ô thắng**, không phải năm — sai theo định nghĩa dạng đáp án dù
`EXECUTION_ACCURACY` không phát hiện ra (query chạy lại vẫn ra đúng số đó). Note đã đo lại
xuống ước lượng thật ~9 câu (~+0.9 điểm `ANSWER_ACCURACY`) sau khi loại các case "bằng chứng
chỉ chạm 1 năm" (lỗi chọn bảng, không phải lỗi dạng) và case hoà/nhập nhằng thật.

Cách hiện có để *phát hiện* việc này (`scripts/gate_year_shape.py`) là hậu kiểm bằng một
lời gọi LLM thứ hai, trung tính, suy ngược năm từ `pandas_query` — tốn thêm 1 lượt LLM mỗi
câu và tự nhận trong log là "prototype bỏ trống 13/35". Đây đúng là bài học cốt lõi trang
10 của deck: "Decoupling — LLM đóng vai Planner, Python/Interpreter đóng vai Calculator."
Gate hiện tại làm ngược: LLM tự trả lời sai dạng trước, rồi một LLM khác đoán lại xem dạng
đúng là gì. Nên viết đúng dạng answer ngay từ trong biểu thức được thực thi, không đoán sau.

**Bằng chứng nó khả thi mà không phá nguyên tắc "one pandas expression"** (đã đo là ưu thế,
xem docstring `codegen.py:33-62`: cho phép model viết statement/chương trình đã đo là làm
*giảm* điểm 40/39→31 vì model dùng tự do đó để bịa placeholder chứ không tính toán) — vì
`raw_selection_linker.py:813` đã giải đúng bài toán này bằng một biểu thức Python hợp lệ,
một dòng, không phải chương trình nhiều bước:

```python
expr = f"({expr}) * 0 + {winning_slot.year}"
```

Đây là bằng chứng nó *chạy được* trong khuôn khổ "một biểu thức" — vấn đề của `codegen.py`
không phải giới hạn cú pháp, mà là **`CODEGEN_SYSTEM` (`codegen.py:64-118`) chưa từng dạy
model idiom này**. Không có dòng nào trong 55 dòng system prompt hiện tại nói "khi câu hỏi
hỏi NĂM NÀO, kết thúc biểu thức bằng `(<phần tính ô thắng>) * 0 + <năm>`, không trả về giá
trị của ô". `understand.py:32` (`AnswerShape = Literal["single_cell", "derived"]`) cũng
không phân biệt "trả năm" khỏi "trả giá trị" — không có nhãn nào đi từ `understand` xuống
`codegen` báo "đây là câu hỏi chọn-năm".

**Đề xuất cụ thể:**
1. Thêm một field `answer_shape` giá trị thứ ba (`"period"` hoặc tái dùng biến của
   `raw_selection_linker`: `selected_year`) vào `UnderstandIntent` (`understand.py:32`),
   gate bằng regex đơn giản trên các cụm "năm nào", "vào năm nào", "thời điểm nào" — đúng
   kiểu canonicalization rẻ tiền mà `HANDOFF.md` dòng 59-62 cho phép ("Regex acceptable for
   cheap canonicalization").
2. Khi cờ này bật, thêm một đoạn ngắn vào `CODEGEN_SYSTEM` (hoặc một block phụ lục nối
   thêm có điều kiện, theo đúng cách `_TOOLS_SYSTEM` đã làm ở `codegen.py:179-180` để không
   đổi byte nào của prompt khi cờ tắt): ví dụ 1 dòng mẫu
   `df1.iloc[7][["2019","2020","2021"]].astype(float).idxmax()` kèm câu "trả về NĂM (nhãn
   cột), không trả giá trị ô — dùng đúng idiom `(<biểu thức tính ô thắng>) * 0 + <năm>` nếu
   không viết được `idxmax` trực tiếp trên các cột năm".
3. Đo trên gold73/gold94 trước khi nộp — so `answer_shape` mới có làm hỏng câu nào đang
   đúng không (rủi ro: regex gate nhận nhầm câu "derived" thành "period").

**Chi phí:** thấp — 1 field enum, 1 regex gate, vài dòng prompt, không đụng retrieval/execute.
**An toàn trong 1.5 ngày:** có, miễn đo lại trên gold73 trước khi tốn 1 lượt nộp thật (còn
9/10 lượt/ngày, 267/310 lượt tổng). **Trần đo được, không phải ước lượng mới:** ≤9 câu/1012
theo phép đo đã có sẵn trong `docs/tables_metric_probes.md` — nhắc lại đúng số đã đo, không
phóng đại.

---

## Đề xuất 2 (trung bình, nên thử nhưng không chắc ăn — mức tin cậy thấp hơn hẳn đề xuất 1): báo cho judge biết khi hai ứng viên "song sinh" cùng report

**Vấn đề:** `docs/tables_metric_probes.md` mục "Nhóm 6 câu 'đúng tài liệu, sai bảng'" đã chỉ
ra case q530 (NAB): bảng cần `|30` (`note_title="CHO VAY KHÁCH HÀNG"`) và bảng bị chọn nhầm
`|26` (`note_title="TIỀN GỬI TẠI VÀ CHO VAY CÁC TCTD KHÁC"`) — **note_title đã đúng và phân
biệt được**, judge (`judge.py`) vẫn chọn sai. Đã kiểm tra `first_col_labels` không phải bị
cắt còn dòng đầu: `enrich_csv` (`metadata_enrichment.py:213-236`) lấy tới 60 nhãn dòng phân
biệt (`MAX_LABELS = 60`, dòng 50) trên toàn bảng, không riêng dòng đầu — nên giả thuyết ban
đầu của tôi ("judge chỉ thấy dòng đầu trùng nhau") **sai**, đã tự bác trước khi đề xuất.
Nguyên nhân thật: hai bảng phân loại nợ theo thông tư SBV (Nợ đủ tiêu chuẩn/Nợ cần chú
ý/.../Nợ có khả năng mất vốn) dùng chung đúng một bộ 5 nhãn dòng chuẩn cho MỌI bảng phân
loại tín dụng trong ngân hàng — dù là "cho vay khách hàng" hay "cho vay TCTD khác" —
nên `first_col_labels` của hai bảng gần như trùng y hệt nhau theo đúng cấu trúc chuẩn, và
`note_title` là tín hiệu phân biệt DUY NHẤT. Đây đúng là lỗi ranking thuần của LLM judge khi
đọc một danh sách 10-30 dòng văn bản nén, không phải lỗi thiếu dữ liệu.

**Liên hệ deck:** trang 8 (Hierarchical Schema Encoding — gán mỗi ô với toàn bộ đường dẫn
phân cấp `[RowPath, ColPath]`) và trang 15 (TableRAG — tách "Schema Retrieval" thô khỏi
"Cell-targeted Pointers" tinh). Bài học chung: khi hai ứng viên có schema/row-label gần
giống hệt nhau, **đừng bắt tầng lọc thô (judge, chỉ đọc text nén) phân xử** — tầng đó vốn
được thiết kế cho recall, không phải cho phân biệt cặp song sinh. Để tầng đọc nội dung thật
(codegen, đọc `.iloc` trên dữ liệu thô) làm việc đó, vì nó có bối cảnh nhiều hơn hẳn (toàn
bộ ô, không phải một dòng text nén).

**Đề xuất cụ thể (thăm dò, không phải giải pháp chắc):**
- Tại bước dựng pool cho judge (`modules/rag/candidates.py` hoặc `service.py` — cần đọc kỹ
  hàm build pool trước khi sửa, tôi chưa lần theo hết), phát hiện các cặp ứng viên **cùng
  report_id** có `first_col_labels` trùng nhau trên ngưỡng Jaccard cao (vd. >0.6) nhưng
  `note_title` khác nhau. Với các cặp này, nới `max_picks` cục bộ hoặc ép cả cặp cùng đi
  qua nếu một trong hai được chọn — tức "nếu chọn 1 trong nhóm song sinh, gửi luôn cả nhóm"
  — để `codegen_max_tables=3` (nếu còn chỗ) hoặc một bậc mở rộng downstream có cơ hội đọc cả
  hai và tự phân xử bằng nội dung thật, thay vì judge phải chọn đúng ngay từ vòng 1.
- Rẻ hơn nhưng yếu hơn: thêm một câu vào `PROMPT` của `judge.py` (dòng 55-69): "Nếu hai ứng
  viên cùng report có nhãn dòng gần giống hệt nhau, đọc kỹ note_title/section_title để phân
  biệt — đừng chọn theo nhãn dòng trùng." Đây chỉ là một chỉ dẫn thêm, không có gì đảm bảo
  LLM tuân theo — cùng loại rủi ro "thêm hướng dẫn không chắc có tác dụng" mà chính đội đã
  từng đo âm ở nơi khác (`config.py:282-292`, `codegen_tool_turns=0`).

**Chi phí:** trung bình — cần đọc/sửa `candidates.py` (cấu trúc pool), không chỉ prompt.
**Trần đo được:** chỉ có 1 case cụ thể đã soi tay (q530); mẫu quá nhỏ để khẳng định đây là
một lớp lỗi lặp lại hay một ca đơn lẻ. **Việc cần làm trước khi code:** đếm trên toàn bộ
146k bảng (không chỉ gold73) có bao nhiêu cặp cùng report/cùng `statement_type=note` có
Jaccard `first_col_labels` > 0.6 nhưng khác `note_title`, và trong số đó bao nhiêu câu hỏi
thật sự retrieve nhầm — nếu con số nhỏ (dưới sàn nhiễu 2 câu như mọi phương án khác trong
p1-p4), không đáng xây. **Không an toàn để thử trong 1.5 ngày nếu chưa đo offline trước** —
đây là thay đổi ở tầng retrieval, rủi ro cao hơn đề xuất 1 (retrieval đang ở `DOCS_F2MACRO
0.9488`, đã bão hoà, rất dễ làm giảm điểm nếu sửa sai chỗ).

---

## Đề xuất 3 (không phải lever tăng điểm — cảnh báo rủi ro, chi phí kiểm tra thấp): tầng sandbox ngôn ngữ mới vá vẫn chưa phải ranh giới an toàn thật theo đúng khung của deck

**Bối cảnh:** commit gần nhất trên nhánh (`b799b22`, "Deny import and dunder-attribute
access in the sandboxed query compiler") vá `_compile_query` trong
`src/finance_qa/modules/tools/python_exec.py` bằng một AST denylist (chặn `import`/
`importfrom` và truy cập thuộc tính dạng `__xxx__`). Đây là vá đúng **tầng ngôn ngữ**
(Language Layer) theo đúng cách deck phân loại ở trang 34-36: "Tầng ngôn ngữ chỉ nên là lớp
lọc sơ bộ, rẻ/nhanh. Tầng hệ điều hành mới là ranh giới an toàn thật, chịu trách nhiệm
chính" — và trang 35 minh hoạ đúng kiểu escape mà một AST denylist không chặn hết được:
chuỗi truy cập thuộc tính đi qua các module *đã import sẵn* trong namespace (`pandas→numpy→
numpy.ma.core→inspect→sys→sys.modules→os→os.system(...)`) mà **không nhất thiết đi qua tên
dunder ở mọi bước** và không cần từ khoá `import` nào — nó tận dụng việc `pandas`/`numpy` đã
có sẵn trong `SAFE_GLOBALS` và mọi submodule của chúng là **thuộc tính thường (không phải
dunder)** có thể đi tới `sys`, `os` qua các con đường tham chiếu nội bộ đã có sẵn trong
package, không phải mọi con đường đều bị chặn bởi denylist `_DUNDER_ATTR` mới thêm.

Đây **không phải một lỗ hổng đã xác nhận** — tôi chưa viết payload thật để kiểm chứng, chỉ
đọc code + đối chiếu với ví dụ nguyên văn của deck. Nhưng deck cũng nêu đúng động cơ tại
sao việc này liên quan tới đề thi cụ thể này (trang 33): "Dữ liệu vào hệ thống có nguồn OCR
từ bên thứ ba → có thể chứa chỉ thị ẩn dụ LLM sinh code độc (indirect prompt injection)" —
corpus của đề thi đúng là 146,246 bảng OCR từ báo cáo tài chính thật, nguồn ngoài, đúng
class dữ liệu deck cảnh báo.

**Đề xuất cụ thể:** viết 2-3 payload thử nghiệm mô phỏng đúng chuỗi trang 35 (không cần
đúng y hệt module path, chỉ cần cùng ý tưởng "đi qua submodule đã import sẵn không qua
dunder") chạy qua `_compile_query`/`SAFE_GLOBALS` hiện tại, xem có lọt không. Việc này độc
lập với LLM, không tốn API, không tốn lượt nộp — thuần kiểm thử offline.

**Vì sao xếp thấp nhất, không phải vì không quan trọng:** đây là rủi ro bảo mật/vận hành,
**không phải một lever tăng `ANSWER_ACCURACY`**. Nhiệm vụ được giao là tìm cách tăng điểm;
mục này không tăng điểm, chỉ tránh một sự cố tiềm ẩn (nếu hạ tầng chấm điểm của BTC thực thi
lại `pandas_query` mà chúng ta nộp, và nội dung bảng OCR nào đó khiến model sinh ra một
biểu thức vượt sandbox). Ghi lại vì deck đặt tên đúng rủi ro này và vì nó rẻ để kiểm tra
trong lúc chờ đo đề xuất 1, không phải vì nó cạnh tranh ngân sách 1.5 ngày còn lại với hai
đề xuất trên.

---

## Xếp hạng tổng hợp

| # | Đề xuất | Tầng | Trần đo được | Chi phí | An toàn cho 1.5 ngày còn lại |
|---|---|---|---|---|---|
| 1 | Idiom "năm nào" trong `CODEGEN_SYSTEM`, tái dùng pattern đã chạy ở `raw_selection_linker.py:813` | `understand` + `codegen` | ~9/1012 (~+0.9 `ANSWER_ACCURACY`), đã đo sẵn trong note khác | Thấp | Có — miễn đo lại gold73/94 trước khi nộp |
| 2 | Nới pool judge cho cặp bảng song sinh cùng report | `retrieve`/judge | Chưa đo diện rộng, 1 case soi tay (q530) | Trung bình | Không, trừ khi đo offline trước — retrieval đang bão hoà cao (0.9488), rủi ro làm giảm |
| 3 | Kiểm chứng sandbox ngôn ngữ vs. ranh giới OS theo đúng khung deck trang 34-36 | `tools/python_exec.py` | Không phải lever điểm — rủi ro vận hành | Rất thấp (chỉ viết payload thử) | Có, không cạnh tranh ngân sách với #1/#2 |

Không đề xuất nào ở đây lặp lại adaptive-k/cell_locator/tuple-planner/grid-port của p1-p4.
Đề xuất 1 là mục duy nhất có trần đo được từ trước (không phải ước lượng mới của tôi) và là
mục nên làm trước nếu chỉ chọn một.
