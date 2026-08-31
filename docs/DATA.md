# Tài liệu mô tả dữ liệu

> **CẢNH BÁO — VIỆC CẦN LÀM TRƯỚC KHI NỘP BÀI**
> Dữ liệu gốc (raw) đã public sẵn trên HuggingFace, có link ngay bên dưới — không cần làm gì
> thêm. Nhưng **dữ liệu phái sinh (derived) do đội tự tính — `tables_metadata_v2.jsonl`,
> `tables_doc_text.parquet`, `tables_dense.npy`, tổng cộng ~618 MB — CHƯA được upload lên
> Google Drive/OneDrive nào cả.** Đây là bước duy nhất cần một người thật thao tác (agent
> không tự upload được). Xem mục "Việc cần làm thủ công" ở cuối file này.
>
> Link Google Drive/OneDrive cho dữ liệu phái sinh: **`[TODO: dán link Google Drive/OneDrive tại đây]`**

## 1. Nguồn dữ liệu

### 1.1. Dữ liệu gốc do BTC cung cấp

- **Tên**: ViFinQA — Vietnamese Financial Question Answering corpus.
- **Link truy cập (public, đã sẵn sàng)**: https://huggingface.co/datasets/AIGuruTinix/ViFinQA
- **Mô tả**: 1.012 câu hỏi tiếng Việt và 1.973 báo cáo tài chính OCR của 100 mã cổ phiếu niêm
  yết Việt Nam, giai đoạn 2015–2025. Chi tiết đầy đủ (bao gồm giới hạn của OCR, quy ước đơn vị,
  và điều khoản sử dụng có trách nhiệm) nằm trong bản mô tả gốc của BTC tại
  `docs/competition/data_source.txt` (đã có sẵn trong repo, không cần viết lại).
- **Bản gốc của nguồn này**: tập con 100 mã của kho TiniX Vietnam OCR Annual Financial
  Statements (18.231 báo cáo, 1.491 mã, ~194 GB), theo đúng mô tả trong `data_source.txt`.

### 1.2. Các tệp mà pipeline của đội thực sự đọc

Theo README (mục "Required inputs not in git"), pipeline chỉ cần 3 loại tệp từ bộ dữ liệu
gốc ở trên, đặt tại thư mục `ViFinQA/` ở gốc repo:

```
ViFinQA/
├── code_stock.csv
├── financial_statements/TICKER/YEAR/DOCUMENT/DOCUMENT_extracted.txt
└── questions/questions.jsonl
```

### 1.3. Dữ liệu phái sinh do đội tự tạo (không có trong bộ gốc của BTC)

Đội chạy pipeline trích xuất bảng + xây chỉ mục truy vấn (retrieval index) trên dữ liệu gốc ở
trên, sinh ra 3 tệp — đây là dữ liệu suy ra (derived), không phải dữ liệu mới, mọi giá trị đều
truy vết được về báo cáo OCR gốc qua `report_id`/`table_pos`/`csv_path`:

| Tệp | Vai trò |
|---|---|
| `data/metadata/tables_metadata_v2.jsonl` | Metadata của từng bảng đã trích xuất (146.246 bảng) |
| `data/indexes/tables_doc_text.parquet` | Văn bản mô tả từng bảng dùng cho BM25/dense retrieval |
| `data/indexes/tables_dense.npy` | Vector nhúng dense (bge-m3) của từng bảng |

## 2. Cấu trúc và định dạng dữ liệu

### 2.1. Dữ liệu gốc

- **`financial_statements/**/*.txt`**: văn bản OCR đầy đủ, UTF-8, giữ ranh giới trang
  (`===== PAGE N =====`) và mã hoá bảng dưới dạng HTML nội tuyến khi OCR nhận diện được bảng
  (`<table><tr><td>...</td></tr></table>`). Đường dẫn tệp cho biết mã cổ phiếu, năm báo cáo, và
  loại báo cáo (hợp nhất/consolidated hay riêng lẻ/separate).
- **`questions/questions.jsonl`**: JSON Lines, mỗi dòng `{"id": <int>, "question": "<câu hỏi
  tiếng Việt>"}`. 1.012 dòng, id liên tục từ 1.
- **`code_stock.csv`**: 2 cột — `Mã CK` (mã cổ phiếu), `Tên công ty`.
- Bộ gốc **không** chứa đáp án, chương trình thực thi, bảng CSV chuẩn hoá, hay nhãn độ khó —
  đội tự xây các phần này trong pipeline riêng (xem `src/finance_qa/pipelines/`).

### 2.2. Dữ liệu phái sinh (đã kiểm tra thực tế bằng pandas/numpy)

**`tables_metadata_v2.jsonl`** — 146.246 dòng, mỗi dòng 1 JSON object mô tả 1 bảng đã trích
xuất. Các trường chạy runtime dùng (đầy đủ danh sách trong `docs/metadata_audit.md`):

```
report_id, table_pos, csv_path, ticker, year, doc_type, statement_type,
statement_subtype, note_title, section_title, first_col_labels, header_flat,
company_name, num_rows
```

Ví dụ một dòng thực tế (rút gọn):

```json
{"report_id": "AAA_financial_statements_2015_consolidated", "table_pos": 2,
 "csv_path": "tables/AAA_financial_statements_2015_consolidated/table_2.csv",
 "ticker": "AAA", "year": 2015, "doc_type": "consolidated",
 "statement_type": "balance_sheet", "statement_subtype": "bs_assets", ...}
```

`csv_path` trỏ tới bảng đã chuẩn hoá dạng CSV (trích xuất trực tiếp từ file OCR gốc) — đây là
cầu nối truy vết ngược từ mỗi bảng CSV dùng để trả lời câu hỏi về đúng báo cáo/trang OCR gốc
của BTC, đúng yêu cầu "có thể truy vết về nguồn dữ liệu" trong `final_submission.md`.

**`tables_doc_text.parquet`** — kiểm tra bằng `pandas.read_parquet`: 146.246 dòng x 5 cột:

| Cột | Kiểu | Nội dung |
|---|---|---|
| `report_id` | str | khớp với `tables_metadata_v2.jsonl` |
| `table_pos` | int64 | khớp với `tables_metadata_v2.jsonl` |
| `doc_text` | str | văn bản mô tả bảng dùng cho BM25 + dense encoder mặc định |
| `dense_text` | str | biến thể văn bản cho dense encoder thay thế (bỏ header_flat) |
| `judge_text` | str | văn bản rút gọn hiển thị cho LLM judge chọn bảng cuối cùng |

**`tables_dense.npy`** — kiểm tra bằng `numpy.load`: shape `(146246, 1024)`, dtype `float16`.
Đây là vector nhúng dense (bge-m3, CLS pooling, L2-normalize) của cột `doc_text` ở trên. Thứ tự
hàng khớp 1-1 với thứ tự hàng của `tables_doc_text.parquet` (khoá là cặp
`report_id`/`table_pos`) — theo đúng docstring trong
`src/finance_qa/modules/rag/indexing/dense.py`.

**Lưu ý quan trọng**: `data/metadata/` và `data/indexes/` trên máy đội còn chứa nhiều tệp biến
thể thử nghiệm khác (`tables_metadata_v3.jsonl`, `tables_dense_v3.npy`,
`tables_dense_noheader.npy`, v.v. — tổng cả hai thư mục ~3 GB). **Chỉ 3 tệp liệt kê ở mục 1.3
là bắt buộc để chạy lại pipeline** (đúng theo README, mục "Required inputs not in git" và
`docs/DECISIONS.md` mục 8 "Protected Artifacts"); các tệp còn lại là log thử nghiệm nội bộ,
không cần upload.

## 3. Kích thước dữ liệu cần chia sẻ

Đo trực tiếp bằng `du` trên 3 tệp bắt buộc:

| Tệp | Kích thước |
|---|---:|
| `data/metadata/tables_metadata_v2.jsonl` | ~286 MiB (299.599.509 bytes) |
| `data/indexes/tables_doc_text.parquet` | ~47 MiB (49.268.849 bytes) |
| `data/indexes/tables_dense.npy` | ~286 MiB (299.511.936 bytes) |
| **Tổng** | **~618 MiB (~648 MB)** |

Con số này nhỏ hơn nhiều so với ước tính ban đầu ~3 GB (ước tính đó tính cả thư mục
`data/metadata/` và `data/indexes/` bao gồm các tệp biến thể thử nghiệm không cần thiết — xem
mục 2.2). Chỉ cần upload đúng 3 tệp bắt buộc để tiết kiệm thời gian.

## 4. Hướng dẫn truy cập / sử dụng dữ liệu

### 4.1. Dữ liệu gốc (public, HuggingFace)

```bash
# Cách 1 -- huggingface_hub CLI
pip install huggingface_hub
huggingface-cli download AIGuruTinix/ViFinQA --repo-type dataset --local-dir ViFinQA

# Cách 2 -- git
git lfs install
git clone https://huggingface.co/datasets/AIGuruTinix/ViFinQA ViFinQA
```

Đặt thư mục `ViFinQA/` ngay tại gốc repo (`ai-finance-stage-2/ViFinQA/`) — đúng vị trí README
yêu cầu.

### 4.2. Dữ liệu phái sinh (đội tự tạo — cần link ở đầu tài liệu này)

1. Tải 3 tệp từ link Google Drive/OneDrive (mục cảnh báo ở đầu tài liệu).
2. Đặt đúng đường dẫn:
   - `data/metadata/tables_metadata_v2.jsonl`
   - `data/indexes/tables_doc_text.parquet`
   - `data/indexes/tables_dense.npy`
3. **Không tự build lại được từ đầu**: `tables_dense.npy` được build từ một phiên bản metadata
   v1 (`tables_metadata.jsonl`) không còn tồn tại trên máy đội (xem `docs/DECISIONS.md` mục 8
   và README mục "Required inputs not in git"). Vì vậy 3 tệp này bắt buộc phải lấy từ bản sao
   lưu (link ở trên), không thể chạy lại pipeline để tái tạo.
4. Sau khi có đủ `ViFinQA/` (mục 4.1) và 3 tệp phái sinh (mục này), làm theo README
   ("Reproducing A Run") để chạy pipeline.

## Việc cần làm thủ công (không thể tự động hoá)

- [ ] Upload 3 tệp ở mục 3 (~618 MiB) lên Google Drive hoặc OneDrive, bật chia sẻ ở chế độ
      "Anyone with the link can view".
- [ ] Dán link chia sẻ vào phần cảnh báo ở đầu tài liệu này (thay `[TODO: ...]`).
- [ ] Kiểm tra lại link hoạt động từ một trình duyệt ẩn danh (không đăng nhập) trước khi nộp,
      đúng khuyến nghị cuối `final_submission.md`.
