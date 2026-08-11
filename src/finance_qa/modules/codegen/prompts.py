"""LLM prompt templates for code generation and calculation services."""

PLAN_PROMPT = """Bạn lập kế hoạch tính toán để trả lời câu hỏi tài chính từ các DataFrame.

CÂU HỎI: {question}

CÁC BẢNG (số ở lề trái là row_index dùng trong binding):
{tables}

Điền kế hoạch theo schema:
{{
  "bindings": [
    {{
      "id": "tên_gợi_nhớ",
      "variable": "df1",
      "row_index": 0,
      "column": "tên cột chính xác",
      "source_unit": "vnd",
      "meaning": "ý nghĩa ngắn gọn"
    }}
  ],
  "formula": "biểu thức trên các binding",
  "output_unit": "million_vnd",
  "explanation": "một câu kiểm tra logic"
}}

Ngôn ngữ formula:
- Toán tử: +, -, *, /, **; so sánh >, >=, <, <=, ==; `and`, `or`, `not`.
- Hàm scalar/list: abs(x), sum([...]), mean([...]), median([...]), min([...]), max([...]).
- Chọn nhãn: argmax({{"2021": x, "2022": y}}), argmin({{...}}).
- Lấy kết quả theo nhãn: select(key, {{"2021": a, "2022": b}}).
- Lọc: mean_where([values], [conditions]), sum_where, min_where, max_where.
- Argmax có lọc: argmax_where({{"A": x, "B": y}}, {{"A": cond_a, "B": cond_b}})
  (tương tự argmin_where).
- Đếm điều kiện đúng: count_true([conditions]).

Ví dụ cấu trúc (chỉ minh hoạ, không phải dữ liệu câu hỏi):
- lookup đổi ra triệu: bindings=[revenue], formula="revenue", output_unit="million_vnd"
- tăng trưởng: bindings=[old, new], formula="(new - old) / old * 100"
- trung bình tiền tệ: formula="mean([v2021, v2022])", output_unit="billion_vnd"
- lồng argmax rồi lấy chỉ tiêu khác:
  formula="select(argmax({{'2021': rank_2021, '2022': rank_2022}}),
                  {{'2021': answer_2021, '2022': answer_2022}})"

Ràng buộc:
- `id` là snake_case duy nhất. `variable`, `row_index`, `column` phải tồn tại đúng như bảng.
- `row_index` LUÔN là số ở LỀ TRÁI DataFrame (0, 1, 2...), không phải giá trị trong
  cột Mã số. Ví dụ Mã số 300 nằm ở lề trái 0 thì row_index là 0, tuyệt đối không phải 300.
- Mỗi binding phải có `source_unit`: vnd, million_vnd, billion_vnd, percent,
  percentage_point, count, ratio hoặc year.
- Plan phải có `output_unit`: vnd, million_vnd, billion_vnd, hundred_billion_vnd,
  trillion_vnd, percent, percentage_point, count, ratio hoặc year.
- Formula KHÔNG tự chia 1e6/1e9/1e11/1e12. Compiler tự chuẩn hoá tiền về VND từ
  source_unit rồi đổi sang output_unit đúng một lần.
- Chỉ binding những ô thực sự cần. Không chép giá trị ô hoặc đáp án thành hằng số.
- Hằng số trong formula chỉ dùng cho bản thân công thức, ví dụ nhân 100 khi tính
  phần trăm. Không dùng 1e6/1e9/1e11/1e12 để đổi đơn vị tiền trong formula.
- Với câu hỏi lồng/lọc, formula phải thể hiện đủ bước lọc/chọn; không nhảy thẳng tới kết quả.
- `trung bình` phải dùng mean; `tổng` dùng sum; tăng trưởng dùng (mới-cũ)/cũ*100.
- Với "chênh lệch A so với B" hoặc "giữa A và B", giữ thứ tự xuất hiện: A - B.
  Khi câu hỏi có nhiều công ty, xác định df nào ứng với công ty nào bằng ticker
  đầu tên bảng (ký tự trước dấu '_' đầu tiên trong tên bảng hiển thị ở header).
  Đặt `id` binding theo ticker: `acb_revenue_2022`, `mbb_service_net_2022`.
  Điều này giúp kiểm tra thứ tự trừ: binding ticker_A - binding ticker_B.
- Cột `Mã số`, `Thuyết minh`, `TM`, STT thường là mã tham chiếu, không phải số tiền.
  Chỉ dùng cột trong "Cột giá trị" để lấy số liệu.
- Khi cùng một chỉ tiêu xuất hiện ở cả bảng [main_report] lẫn bảng [note], luôn lấy từ
  bảng [main_report]. Bảng [note] chứa chỉ tiêu phân tích chi tiết, không phải con số tổng.
- Với bảng phân loại chi tiết (nhiều hàng phân mục con), giá trị tổng hợp thường có
  nhãn "Cộng" / "Tổng cộng". Không dùng row_index của một hàng phân mục con làm đại diện tổng.

Chỉ trả về dữ liệu theo schema, không giải thích ngoài schema."""

PLAN_REPAIR = """Kế hoạch vừa rồi không hợp lệ.

KẾ HOẠCH HIỆN TẠI (đã qua các sửa chữa deterministic; giữ nguyên mọi phần
không liên quan trực tiếp tới lỗi):
{previous_plan}

LỖI:
{errors}

Trả về TOÀN BỘ plan theo schema sau khi chỉ sửa binding/formula gây lỗi. Không dựng lại
các binding đã hợp lệ và không đổi row/column của phần không bị nêu trong lỗi.
Chỉ trả về dữ liệu đúng schema."""


FORMULA_SYSTEM = "Bạn là chuyên gia phân tích tài chính."

FORMULA_PROMPT = """\
Dữ liệu tài chính đã chuẩn hóa (các tỷ số đã tính sẵn, số liệu thô đơn vị VND):
{table}

Câu hỏi: {question}

Suy luận theo ĐÚNG thứ tự các bước của câu hỏi. Với câu hỏi lồng nhau (ví dụ
"năm có chỉ tiêu A cao nhất thì chỉ tiêu B là bao nhiêu"): trước hết chọn
năm/công ty thoả điều kiện lọc theo A, rồi mới lấy chỉ tiêu B cần trả lời của
đúng năm/công ty đó — không lấy giá trị lớn nhất/nhỏ nhất của chính chỉ tiêu B.

Trả lời đúng đơn vị câu hỏi yêu cầu (phần trăm nhân 100; "lần" giữ nguyên tỷ số;
tiền quy đổi từ VND). Kết thúc bằng một dòng: ĐÁP SỐ: <số>"""

EXTRACT_PROMPT = (
    "Trích đáp số cuối cùng (số thực) từ phân tích sau và gọi final_answer:\n\n"
)


REPL_SYSTEM = """\
Bạn là trợ lý tính toán tài chính. Dùng run_code() để tính từng bước; khi đã có
đáp án hoàn chỉnh, gán result = <số> trong run_code (chương trình dừng khi thấy result).

Câu hỏi: {question}
Đơn vị đầu ra yêu cầu: {unit_hint}

Namespace đã có sẵn: {df_vars}, pd, np, canonical, get_metric, get_val.
TUYỆT ĐỐI KHÔNG viết "import ..." và KHÔNG đọc file (read_csv/read_excel/open) —
pd, np và các df đã nằm sẵn trong bộ nhớ.

Schema các DataFrame:
{schema_blocks}

Hàm tiện ích có sẵn:
  get_metric(metric_id, year, ticker=None) → CHỈ cho các chỉ tiêu TỔNG QUÁT chuẩn
    (net_revenue, gross_profit, net_profit, total_assets, total_debt, equity, ...).
    Tên canonical CÓ THỂ không khớp chữ trong câu hỏi — ví dụ short_term_debt là
    "Nợ ngắn hạn" (mã 310), KHÁC "Vay ngắn hạn" (mã 320 = short_term_borrowings).
    Khi câu hỏi nêu ĐÍCH DANH một khoản mục, ĐỪNG đoán metric_id theo tên.
  Ví dụ: get_metric("total_debt", 2022)          → float  (tìm trong tất cả df)
         get_metric("equity", 2022, "FPT")        → float  (chỉ df của FPT)
         get_metric("net_profit", 2021)           → float  (mã 60 = LNST)
  Pattern multi-year (L6):
    de = {{yr: get_metric("total_debt", yr) / get_metric("equity", yr)
           for yr in range(2016, 2021)
           if get_metric("total_debt", yr) and get_metric("equity", yr)}}
    max_yr = max(de, key=de.get)
  get_val(df, keyword, col=None) → tìm dòng chứa keyword (case-insensitive), trả giá trị từ col
  Ví dụ: get_val(df1, 'Lợi nhuận sau thuế', 'Năm 2024')  → float

Công thức VAS thường gặp (metric_id trong canonical):
  D/E       = total_debt / equity
  ROE       = net_profit / equity
  ROA       = net_profit / total_assets
  Lãi vay   = (profit_before_tax + abs(interest_expense)) / abs(interest_expense)
  Gross GM  = gross_profit / net_revenue
  Current   = current_assets / short_term_debt
  Lưu ý: interest_expense trong canonical là số ÂM (chi phí) → dùng abs()

Quy tắc:
- KHÔNG import. pd, np, get_val, get_metric, canonical, {df_vars} đã có sẵn.
- Với khoản mục nêu ĐÍCH DANH trong câu hỏi (vd "vay ngắn hạn", "người mua trả
  tiền trước", "quỹ khen thưởng phúc lợi", "lãi thuần từ hoạt động dịch vụ",
  "dự phòng phải thu khó đòi", "doanh thu hoạt động tài chính"): PHẢI tự tìm đúng
  dòng trên df gốc — print các dòng KHỚP (nhãn + cột 'Mã số' nếu có + giá trị) để
  XÁC NHẬN đúng khoản mục, rồi mới lấy số. KHÔNG tin get_metric() khớp theo tên.
- get_metric() chỉ dùng cho chỉ tiêu tổng quát (doanh thu, tổng tài sản, vốn CSH,
  LNST, tổng nợ) và cho aggregate multi-year/multi-company của các chỉ tiêu đó.
- get_val()/lọc chuỗi con có thể TRÚNG NHẦM dòng (vd "vay ngắn hạn" cũng khớp
  "phải thu về cho vay ngắn hạn"); luôn print dòng khớp để kiểm tra trước khi dùng.
- Dùng print() để kiểm tra giá trị trung gian TRƯỚC khi kết luận.
- Khi get_val trả None: thử keyword ngắn hơn hoặc col khác.
- ĐƠN VỊ (rất hay sai — làm cẩn thận): đáp án PHẢI đúng đơn vị "{unit_hint}".
  Số thô trong BCTC thường bằng ĐỒNG (độ lớn ~1e9–1e13); nhìn độ lớn số thô để
  biết nó đang ở đơn vị nào, rồi đổi sang đơn vị câu hỏi:
    tỷ đồng → /1e9 ; triệu đồng → /1e6 ; nghìn tỷ → /1e12 ;
    "%"/phần trăm → *100 nếu đang là tỷ số thập phân ; "lần"/tỷ số → giữ nguyên.
  BẮT BUỘC print CẢ số thô LẪN số đã đổi (ghi rõ chia/nhân 10^mấy) rồi mới gán
  result = <số đã đổi>. Nếu câu hỏi không nêu đơn vị thì giữ nguyên giá trị gốc.
- Viết code NGẮN, mỗi bước 1–3 dòng; KHÔNG lặp lại y hệt code bước trước. Nếu bước
  trước đã print ra số đúng, bước sau chỉ cần gán result = <số đó>.
- Với "chênh lệch A so với B" hoặc "giữa A và B", giữ thứ tự xuất hiện: A - B.
- result DÀNH RIÊNG cho đáp án cuối cùng — KHÔNG dùng result cho biến trung gian
  hay counter. Dùng tên khác cho biến tạm: total, ratio, val, max_val, v.v.
- CHỈ gán result = <biểu thức đã tính> sau khi đã print kiểm tra; result phải do
  code tính ra, tuyệt đối không gõ một con số bịa."""
