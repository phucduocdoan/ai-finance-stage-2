# Thống kê extract bảng

- Số file OCR đã xử lý: **1,973**
- Tổng số bảng trích được: **146,246**
- Report có ít nhất 1 bảng: **1,965**
- Report không có bảng nào: **8**
- Thời gian chạy: **235.3s**

## Phân bố trạng thái parse

| Trạng thái | Số bảng | Tỉ lệ |
|---|---:|---:|
| `ok` | 146,246 | 100.0% |

## Phân bố số bảng / report

- Min: 1
- p50: 70
- p90: 108
- p99: 152
- Max: 248

## Phân bố kích thước bảng (chỉ tính bảng `ok`)

- Số dòng — p50: 8, p90: 21, max: 1008
- Số cột — p50: 3, p90: 6, max: 1954

## Ghi chú

- `page_number` là số trang xuất hiện trong marker `===== PAGE N =====` gần nhất trước bảng.
- Schema CSV giữ nguyên rows/cols từ HTML gốc, không normalize header.
- Bảng lỗi/rỗng vẫn được ghi CSV (file rỗng) để giữ liên kết `csv_path` hợp lệ.
