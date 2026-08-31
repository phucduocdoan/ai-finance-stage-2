# Đánh giá khả thi — Phương án 6: rà soát slide/thể lệ cho định dạng chấm điểm

Điều tra read-only, không sửa code. Ngày 2026-08-30.

## Kết luận

- **Không tìm thấy root cause mới cho `TABLES_*=0.0`, và không nên dò thêm lượt nộp nào
  cho nó.** Chủ đề này đã được đóng bằng thực nghiệm từ trước (`docs/tables_metric_probes.md`,
  12 lượt submit, kết luận ngày 2026-08-22): không numbering scheme nào (ordinal `<table>` thô,
  `td_idx`, `ctd_idx`, `trtd`, `page`, `char_off`, 6 biến thể chuỗi) khớp được số vị trí gold, và
  quét rộng nhất cũng chỉ đạt trần `F2MACRO≈0.0035` — không đủ để đổi lấy một lượt nộp. Ba tài
  liệu đọc trong phiên này (2 slide deck + 1 file thể lệ scan ảnh) **không cung cấp bằng chứng
  nào bác bỏ kết luận đó**; ngược lại, một chi tiết mới (xem dưới) chỉ càng củng cố nó.
- **Deck được giao đọc sai mục đích khớp đề bài chấm điểm.**
  `_2026__R2AI___Stage2___Finance_Tabular_QA___Aug21 (1).pdf` (39 trang, "Day 2: Advanced
  Methods") là bài giảng phương pháp kỹ thuật thuần tuý: MultiHiertt benchmark, PAL/Binder,
  Numeric Masking, TableRAG, Multi-Agent, LLM serving, sandbox OS-level. Đọc hết 39/39 trang,
  **0 lần xuất hiện** bất kỳ từ khoá nào trong số `ANSWER_ACCURACY`, `EXECUTION_ACCURACY`,
  `TABLES_`, `DOCS_`, `submission`, `relevant_tables`, `evidence`, hay bất kỳ công thức/dung
  sai/làm tròn nào. Deck này không phải nguồn cho câu hỏi được giao.
- **Phát hiện một trích dẫn sai nguồn (không phải bug, chỉ là nhầm tên file) trong code hiện
  tại.** `scripts/build_submission.py:99` ghi chú quy tắc làm tròn dựa trên "Slide p35":
  > "Không làm tròn trung gian; chỉ làm tròn kết quả cuối 2 chữ số thập phân."

  Nhưng **trang 35 của deck được giao đọc nói về cách ly sandbox ở tầng hệ điều hành**
  (chroot/container/gVisor/microVM), không liên quan gì đến làm tròn. Trích dẫn thật nằm ở
  **trang 35 của một deck khác**: `docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf`
  (44 trang, "Aug 12"), mục "Ví dụ Prompting: Chain-of-Thought", nguyên văn khớp 100%:
  > "Rounding Rule: Không làm tròn trung gian; chỉ làm tròn kết quảcuối cùng 2 chữsốthập phân."

  Công thức trong code (`round_final()`) trích đúng nội dung, chỉ lẫn tên file nguồn trong
  comment — không cần sửa gì, nêu ra để tránh nhầm lẫn nếu ai tra lại sau này.
- **Deck AIGuru (44 trang) cũng không có công thức chấm điểm.** Nó là bài giảng
  preprocessing (OCR → HTML `<table>` → CSV chuẩn hoá) + retrieval (BM25/dense/reranker,
  bảng Recall@10 trên ViFinQA) + reasoning (PoT vs CoT, bảng lỗi 430 ca của
  DeepSeek-V4-Flash: 54.7% Numerical Extraction, 34.7% Insufficient Evidence, chỉ 0.9%
  Numerical Calculation — trang 40). Chi tiết lỗi này gián tiếp xác nhận hướng đầu tư nên vào
  answer/extraction hơn là tính toán, khớp với ghi nhận nội bộ hiện tại rằng
  `ANSWER_ACCURACY` còn nhiều đất hơn `TABLES_*` (`docs/tables_metric_probes.md`, dòng cuối).
  Không có gì mới cho câu hỏi TABLES.
- **Công thức chấm điểm CHÍNH THỨC nằm ở một file thứ ba, không phải 2 deck trên:**
  `docs/competition/Thể lệ Stage 2.pdf` — file scan ảnh (CamScanner), 9 trang, không extract
  được text bằng `pymupdf` (`page.get_text()` trả rỗng cả 9 trang) nên phải render ảnh
  (`pix = page.get_pixmap(dpi=150)`) rồi đọc trực tiếp. Mục **VII. TIÊU CHÍ ĐÁNH GIÁ** (trang 7)
  ghi rõ:
  1. **Truy hồi thông tin (50%)**: Precision = trung bình theo truy vấn của (số bảng truy hồi
     đúng / số bảng đã truy hồi); Recall = trung bình theo truy vấn của (số bảng truy hồi đúng /
     số bảng liên quan); **F2 = (5 × Precision × Recall) / (4 × Precision + Recall)**. Công thức
     này khớp **chính xác từng ký tự** với macro P/R/F2 mà team đã tự suy ra và dùng để đọc kết
     quả 12 lượt probe trong `tables_metric_probes.md` — xác nhận công thức nội bộ đã dùng đúng.
  2. **Answer Accuracy** = (số query khớp đáp án chuẩn, trong ngưỡng sai số) / (tổng số query).
     Văn bản ghi "trong ngưỡng sai số cho phép do Ban Tổ chức (BTC) công bố" nhưng **không nêu
     con số cụ thể nào** trong toàn bộ 9 trang — xác nhận lại đúng điều `p1_adaptive_k...md` đã
     note: dung sai chấm điểm chính thức "chưa biết", không suy luận thêm được từ tài liệu.
  3. **Execution Accuracy** = (số code chạy được và cho kết quả đúng) / (tổng số query).
  - **`MRR5` không được định nghĩa ở đâu cả trong cả 3 tài liệu.** Leaderboard hiện báo
    `TABLES_MRR5`/`DOCS_MRR5` nhưng mục "Tiêu chí đánh giá" chính thức chỉ liệt kê
    Precision/Recall/F2. Không có thêm manh mối nào về cách nó tính (có phụ thuộc thứ tự phần
    tử trong `relevant_tables`/`relevant_docs` hay không) — đây vẫn là một câu hỏi mở, không
    phải do thiếu đọc tài liệu mà do tài liệu thật sự không nói tới.
  - **Một chi tiết cần cân nhắc, nhưng đã bị đóng bởi dữ liệu thực nghiệm chứ không mở ra
    hướng mới**: mục V (trang 3, "Dẫn nguồn minh bạch") viết "Trích dẫn công ty, năm, tên báo
    cáo, tên bảng và **vị trí (trang/mục)** chứa số liệu gốc." Cụm "vị trí (trang/mục)" gợi ý
    "position" có thể là **số trang**, không phải ordinal bảng. Tuy nhiên giả thuyết "page" đã
    bị `tables_metric_probes.md` loại bỏ bằng đo đạc thật (mục "Kết luận chắc chắn" #7:
    "`page` và `char_off` bị loại làm đơn vị: p(≤300) = 1.000 và 0.000, cần ~0.142") — nghĩa là
    team đã thử đúng giả thuyết này bằng dữ liệu, không phải bỏ sót nó. Phát hiện trong tài liệu
    chỉ xác nhận đây là hướng suy luận "tự nhiên" nhất mà ai đọc thể lệ cũng sẽ nghĩ tới đầu
    tiên — và nó đã bị bác bỏ đúng cách.
  - Ví dụ format ở trang 6 của `Thể lệ Stage 2.pdf`: `"relevant_tables": ["VNM_01_2025|350"]`
    dùng lại **đúng con số "350"** như ví dụ `"AAA_financial_statements_2015_consolidated|350"`
    trong `docs/competition/submission_rule.txt:35,49`. Hai tài liệu độc lập cùng dùng "350"
    làm số minh hoạ — càng củng cố kết luận cũ (`tables_metric_probes.md` mục 6) rằng đây là
    con số ví dụ tái sử dụng giữa các bản thể lệ, không phải số liệu thật, không nên suy luận gì
    từ nó.

## Phát hiện phụ, không thuộc phạm vi TABLES nhưng đáng ghi lại

- `Thể lệ Stage 2.pdf` (trang 5-6) mô tả một schema nộp bài **đơn giản hơn** bản
  `submission_rule.txt` đang được implement: không có field `evidence` dạng list
  `[{variable, csv_path}]`, mà chỉ có một `csv_path: <string>` phẳng ở cấp item, và không có
  field `pandas_query` tách biệt theo kiểu evidence-narrow. Đây có khả năng là bản thể lệ
  cũ/nháp hơn `submission_rule.txt` (tài liệu này scan qua CamScanner, không rõ ngày, có cả một
  dòng lộ trình "Vòng 1: Build AI Legal Assistant" ở mục IX — rõ ràng lẫn nội dung từ một track
  khác của "Road to AI 2026", cho thấy tài liệu này bị copy-paste ẩu giữa các track/thời điểm).
  `submission_rule.txt` khớp đúng với những gì `build_submission.py`/`submission.py` đang tạo
  ra (field `evidence` list, biến DataFrame, v.v.), nên nhiều khả năng đó là spec đang có hiệu
  lực thật trên dashboard. Không đề xuất sửa gì — chỉ nêu để nếu có nghi ngờ leaderboard áp
  dụng thể lệ nào, đây là chỗ hai tài liệu lệch nhau.
- Mục XI của `Thể lệ Stage 2.pdf` liệt kê 2 đầu mối liên hệ Ban Tổ chức
  (nguyetntm@dagoras.io, linhvtt@dagoras.io) — kênh duy nhất có thể hỏi thẳng về ngưỡng sai số
  `ANSWER_ACCURACY` và công thức `MRR5`, vì không tài liệu nào trong 3 file đã đọc trả lời được
  hai câu hỏi này.

## Đề xuất

Không có đề xuất sửa code cụ thể nào cho `TABLES_*` — không tìm được bằng chứng bác bỏ kết
luận "đóng hướng TABLES" của `tables_metric_probes.md` (2026-08-22). Giữ nguyên khuyến nghị đó:
không dò thêm lượt nộp cho TABLES, dồn lượt nộp còn lại vào `ANSWER_ACCURACY`/
`EXECUTION_ACCURACY`, nơi công thức chính thức (trang 7, `Thể lệ Stage 2.pdf`) xác nhận có một
"ngưỡng sai số cho phép do BTC công bố" mà nội bộ team chưa biết con số — nếu có kênh liên hệ
BTC, đây là câu hỏi duy nhất từ phiên đọc tài liệu này đáng hỏi trực tiếp thay vì tiếp tục dò
qua submission thật.
