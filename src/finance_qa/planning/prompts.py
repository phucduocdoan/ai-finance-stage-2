"""LLM prompt templates for the planning and code-generation stages."""

PLAN_PROMPT = """Bạn lập kế hoạch tính toán để trả lời câu hỏi tài chính từ các DataFrame.

CÂU HỎI: {question}

CÁC BẢNG (số ở lề trái là row_index dùng trong binding):
{tables}

Trả về một JSON object theo schema:
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

Chỉ in JSON, không markdown."""

PLAN_REPAIR = """Kế hoạch vừa rồi không hợp lệ.

KẾ HOẠCH HIỆN TẠI (đã qua các sửa chữa deterministic; giữ nguyên mọi phần
không liên quan trực tiếp tới lỗi):
{previous_plan}

LỖI:
{errors}

Trả về TOÀN BỘ JSON plan sau khi chỉ sửa binding/formula gây lỗi. Không dựng lại
các binding đã hợp lệ và không đổi row/column của phần không bị nêu trong lỗi.
Chỉ in JSON đúng schema."""

PROMPT = """Bạn viết biểu thức pandas để trả lời một câu hỏi tài chính từ các bảng cho sẵn.

CÂU HỎI: {question}

CÁC BẢNG (đã nạp sẵn thành DataFrame đúng tên biến ghi ở đầu mỗi bảng):
{tables}

Yêu cầu:
- Trả về MỘT biểu thức pandas duy nhất trên một dòng, không gán biến, kết quả là một SỐ.
- Chỉ dùng các biến DataFrame ở trên và `pd`. Không import, không đọc file.
- Các cột số đã được chuẩn hoá thành float (không còn dấu chấm phân cách nghìn).
- Tên cột phải copy CHÍNH XÁC như liệt kê, kể cả tên dạng 'Unnamed: 0' hay 'Số lượng.1'.
- Có thể lấy dòng bằng `.iloc[n]` theo đúng số thứ tự hiển thị ở lề trái bảng.
- Cột `Mã số`, `Thuyết minh`, `TM`, STT hoặc số La Mã thường chỉ là mã tham chiếu,
  KHÔNG phải giá trị tiền. Phải lấy cột số liệu đúng năm/kỳ.
- OCR có thể làm header nhiều dòng bị lệch. Khi một tên cột chứa chữ thay vì
  số, hãy suy ra cột số thực tế từ toàn bộ hàng, các cột `Unnamed:*`, và quan hệ
  cộng/trừ của bảng; không máy móc tin tên header.
- Khi câu hỏi có nhiều công ty, xác định biến df nào ứng với công ty nào bằng
  ticker đầu csv_path (ký tự trước '_' đầu tiên, ví dụ ABB_... → ABB).
  Với "chênh lệch A và B" hoặc "A so với B", tính A_df.value - B_df.value
  theo đúng thứ tự câu hỏi, không phụ thuộc thứ tự evidence.
- Chú ý ĐƠN VỊ: nếu câu hỏi hỏi "triệu đồng"/"tỷ đồng" mà bảng ghi bằng đồng thì phải chia.
- Quy đổi: triệu = chia 1e6, tỷ = chia 1e9, trăm tỷ = chia 1e11,
  nghìn tỷ = chia 1e12. Nếu bảng đã ghi `Triệu đồng` thì không chia lần nữa.
- Tăng trưởng = (mới - cũ) / cũ * 100; giá trị trung bình = tổng / đúng số mốc.
- Tỷ suất lợi nhuận ròng = LNST / doanh thu thuần * 100.
- D/E = nợ phải trả / vốn chủ sở hữu. Khả năng thanh toán lãi vay =
  (lợi nhuận trước thuế + |chi phí lãi vay|) / |chi phí lãi vay|.
- Với câu hỏi lồng nhau (tìm năm lớn nhất rồi lấy chỉ tiêu khác), biểu thức
  phải thực hiện cả bước chọn đó từ các DataFrame, không được nhảy thẳng
  tới con số cuối chỉ vì đã nhìn thấy bảng nào lớn nhất.
  Có thể viết một biểu thức điều kiện dạng
  `(giá_trị_cuối if pd.Series([các_giá_trị], index=[các_năm]).idxmax() == năm_đích
  else float('nan'))` để vừa chứng minh bước argmax vừa trả số cuối.
- Khi hỏi `tổng` của một bảng chi tiết, lấy đúng dòng mang nhãn `Cộng`/`Tổng`;
  không dùng cùng một `.iloc` cho nhiều năm vì số dòng chi tiết có thể thay đổi.
- Giá trị trong `Unnamed: 0` hay cột nhãn đầu tiên là NHÃN DÒNG (row label), không phải
  tên cột. Không dùng chúng làm tên cột trong `.loc[]` hay `[]`.

Chỉ in ra JSON, không giải thích:
{{"pandas_query": "..."}}"""

REPAIR = """Biểu thức vừa rồi chạy lỗi.

BIỂU THỨC: {query}
LỖI: {error}

Sửa lại dựa đúng vào các bảng ở trên. Chỉ in ra JSON:
{{"pandas_query": "..."}}"""

VERIFY = """Biểu thức sau đã chạy được, nhưng chạy được chưa có nghĩa là đúng.

BIỂU THỨC: {query}
KẾT QUẢ CHẠY: {answer}

Hãy kiểm tra lại từ đầu theo CÂU HỎI và CÁC BẢNG:
1. Đúng dòng chỉ tiêu, đúng công ty/năm/kỳ và đúng cột giá trị; không lấy nhầm
   `Mã số`, `Thuyết minh`, `TM`, STT hay số La Mã.
2. Đúng phép tính, thứ tự trừ, số mốc khi lấy trung bình, và mọi bước chọn
   trung gian của câu hỏi lồng nhau.
3. Đúng đơn vị đích. Đặc biệt: `trăm tỷ` chia 1e11, `nghìn tỷ` chia 1e12;
   cột đã ghi `Triệu đồng` thì không chia 1e6.
   Nếu câu hỏi nói `trung bình` N mốc thì biểu thức bắt buộc `.mean()` hoặc chia N.
4. Nếu header OCR bị lệch, dùng các giá trị trong hàng và quy luật cộng/trừ để
   xác định cột thực, kể cả khi cột đó mang tên `Unnamed:*`.

Nếu biểu thức đúng thì trả lại nguyên văn; nếu sai thì sửa. Chỉ in JSON:
{{"pandas_query": "..."}}"""

REPL_START = """Bạn là trợ lý tính toán tài chính. Mỗi lần chỉ trả về MỘT trong hai JSON:
  {{"code": "..."}}           — code Python/pandas để thực thi (dùng print() để xem kết quả)
  {{"final_answer": <float>}} — đáp số cuối cùng là số thực

Không trả về văn bản, giải thích hay markdown — chỉ JSON thuần.

---
Câu hỏi: {question}

DataFrame đã load ({df_vars}) — chỉ có schema, KHÔNG có số sẵn:
{schema_blocks}

{planner_context}Quy tắc:
- Biến tồn tại giữa các lần. Không import thêm. Không hardcode số từ đầu.
- Dùng print() để xem giá trị thực: print(df1[df1['Mã số']==100]['Năm 2024'].values)
- Suy ra đơn vị từ giá trị thực (VND/triệu/tỷ), chia đúng theo câu hỏi.
- Chỉ trả final_answer sau khi đã xem và tính xong."""

REPL_CONTINUE = """
{history_block}

--- Bước {step}/{max_steps} ---
Tiếp tục khám phá hoặc trả final_answer. JSON của bạn:"""
