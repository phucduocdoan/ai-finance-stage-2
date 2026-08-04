# Metadata Audit — ViFinQA Stage 2

**Ngày**: 2026-08-03  
**Input**: `data/metadata/tables_metadata_v2.jsonl` (146,246 bảng · 25 fields · 294 MB)  
**Mục tiêu**: Đánh giá xem metadata có đủ tổng quát cho retrieval BM25 + dense không, có bị fit cứng vào subset không.

## Verdict tổng thể

Metadata **đủ tổng quát cho ~85–90% câu hỏi**, **không cần redesign**. Cần vài fix incremental (Nhóm A + B dưới đây).

- Tier 1 hard filter (ticker/year/doc_type/industry_segment/statement_type) hoạt động tốt cho ~90% câu
- Tier 2 raw text (header_flat + first_col_labels + note_title + context_page_text) đủ signal cho BM25 route note đúng ~88% câu
- Phần còn lại (7–12%) là edge cases (multi-hop L6, column semantics, bảng bán niên/tiếng Anh) — không thể fix bằng metadata thuần

## Phương pháp

Delegate 2 sub-agent Sonnet chạy song song:
- **Agent A**: Stratified sample 68 bảng (cân bằng industry × statement_type), đọc CSV thật + metadata, đánh giá từng field có generalize không.
- **Agent B**: Sample 60 câu hỏi (20 manual_solutions verified + 40 random), phân tích 5 chiều mỗi câu (filter attributes / concept keyword / section routing / composability / missing signals).

Kết quả cross-verify bằng Python trên full metadata trước khi finalize.

## Real gaps (đã verify)

| # | Gap | Evidence | Fix |
|---|---|---|---|
| 1 | `statement_type=unknown` chiếm 10.2% (14,900 bảng) — ~4,461 thực chất là note bị miss classify; ~2,600 là maturity ladders bank; có bảng semi-annual (`30.6.2025VND \| 31.12.2024VND`) | Sample 68 bảng của Agent A | Rule: header có date-pattern + section chứa "thuyết minh" → gán `note` |
| 2 | BVH và insurance tickers đều `industry_segment=general` | Verified: 1,958/1,958 rows BVH = `general` | Ticker whitelist → thêm giá trị `insurance` |
| 3 | Securities 40% có `doc_type` empty (1,663/4,145) | Verified trực tiếp | Rule: `industry_segment=securities` + empty → `doc_type=securities` |
| 4 | `note_pivot_dim` thiếu cho bank — 3,101 bảng "CHO VAY KHÁCH HÀNG" chia thành 4-5 pivot (sector/quality/customer/maturity) nhưng cùng note_title | Manual_solutions Q#2, Q#591, Q#754 | LLM-derive từ `first_col_labels` |
| 5 | 11 câu hỏi có `tickers=[]` — không resolve từ tên công ty đầy đủ (VD "CTCP Tasco") | Verified 11/1012 | `company_name → ticker` dictionary từ `code_stock.csv` |
| 6 | `equity_change` chỉ có 51 bảng, toàn securities — B04-DN và B04-TCTD không được nhận diện | Sample Agent A | Cần điều tra: extraction miss hay dataset thực sự thiếu |

## Vấn đề nhỏ (accept hoặc fix tại indexing time)

- `header_flat` ~4.4% có chữ dính (`"nămVND"`, `"nayTriệu"`) do OCR paste liền không space. **Fix tại indexing time**, không cần regen: regex insert space giữa `[a-z]` và `[A-ZÀÁÂÃ]` trước khi tokenize BM25.
- `period_years` empty ~30% (44,043 bảng) — trong đó ~26,549 là continuation nên kế thừa kỳ; còn ~17,494 non-continuation thực sự thiếu context thời gian.
- ~2–5% bảng tiếng Anh (VD SAB có "CASH FLOWS FROM INVESTING ACTIVITIES") — VN-only embed sẽ miss. Cần `language` field nếu dùng monolingual model.
- 27+ bảng bán niên/quý (pattern `30.6.YYYY`) — `period_years` chỉ capture năm, mất Q2 information.
- `statement_subtype` chỉ điền cho general-BS (`bs_assets`/`bs_liabilities_equity`); CF và IS đều empty 100% — chưa cần vì `first_col_labels` phân biệt được `cash_flow_method` (trực tiếp/gián tiếp).

## False alarm (đã bác bỏ)

- **`period_years` serialization** — Agent B nghi ngờ được lưu dạng Python repr string, `json.loads()` fail. **Verify**: 100% rows là JSON list hợp lệ, non-empty 67.8% trong sample 20k → không có bug này. Skip.

## Đã ổn (không cần fix)

`ticker`, `year`, `doc_type` (trừ securities), `company_name`, `mau_tag` (chỉ 2 tag ngoài schema trong 146k), `industry_segment` (trừ insurance), `is_continuation`, `note_id_inherited`, `context_page_text` (98.6% non-empty, median 518 chars), `first_col_labels`, `has_ma_so_column`, `statement_type` cho BS/IS/CF/notes chính.

## Kế hoạch fix

### Nhóm A — quick fixes (~1 buổi)

1. Rule reclassify `statement_type=unknown` → `note` khi có date-pattern header + section text chứa "thuyết minh"
2. Whitelist insurance tickers (BVH, MIC, PVI, PTI, BMI...) → set `industry_segment=insurance`
3. Rule fix securities `doc_type` empty → `doc_type=securities`
4. Bổ sung `company_name → ticker` dictionary trong `enrich_questions.py`, regen `questions_enriched.jsonl` cho 11 câu
5. Normalize `header_flat` khi build BM25 index (regex insert space) — tại indexing time, không cần regen metadata

### Nhóm B — cần LLM/effort (~1-2 ngày, chỉ làm khi baseline lộ vấn đề)

6. `note_pivot_dim` — LLM-derive enum `{sector, quality, customer_type, maturity, currency, geographic, other}` từ `first_col_labels` cho bank note tables
7. Điều tra `equity_change` cho DN/bank — check dataset gốc xem có B04-DN/B04-TCTD không

### Nhóm C — deferred

- `language` (VN/EN)
- `is_semi_annual` / `period_quarter`  
- `cash_flow_method` (chỉ khi retrieval CF fail)

**Chiến lược**: Làm Nhóm A trước → build retrieval baseline → measure recall trên manual_solutions → chỉ đụng Nhóm B khi baseline có gap thực.

## Câu hỏi mở

1. `equity_change` cho DN/bank có thực sự trong dataset không, hay đã miss ở giai đoạn extract?
2. Bảng bán niên/quý (semi-annual) chiếm bao nhiêu và có câu hỏi nào cần không?
3. Dense embed model dùng loại nào — VN-only (`vietnamese-bi-encoder`) hay multilingual? Ảnh hưởng đến việc cần `language` field.
4. Với Nhóm B fix `note_pivot_dim`, dùng LLM nào — Sonnet cho 3,101 bảng bank + có thể mở rộng?

## Sub-agent references

- Agent A (metadata design audit): `agentId: ac9d296349ec7fdd2`
- Agent B (question coverage audit): `agentId: ab7e629a908ab2396`
