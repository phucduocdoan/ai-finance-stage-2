# Enrich v2 stats

- Input: `tables_metadata.jsonl`
- Output: `tables_metadata_v2.jsonl` (294.0 MB, post-strip of `parse_status`/`header_preview`/`csv_snippet`)
- Rows: **146,246**
- Time: **134.8s**
- CSV missing: 0
- Empty `first_col_labels`: 3862 (2.6%)
- Empty `context_page_text`: 1981 (1.4%)
- Reports with missing OCR: 9
- Tickers without company_name mapping: 0
- Empty `doc_type`: 2874 (2.0%)
- Empty `period_years`: 44043 (30.1%)
- `is_continuation=true`: 61165 (41.8%)

## industry_segment distribution

| Segment | Số bảng | Tỉ lệ |
|---|---:|---:|
| `general` | 102,909 | 70.4% |
| `bank` | 39,192 | 26.8% |
| `securities` | 4,145 | 2.8% |

## Fields added

**Tầng 1 derived**: `ticker`, `year`, `doc_type`, `company_name`

**Tầng 2 from CSV**: `header_flat`, `first_col_labels`

**Tầng 2 from OCR page**: `context_page_text` (cap 1500 chars, whitespace collapsed, `<table>` stripped)

**Semantic signals** (BA priorities 2/3/4): `industry_segment`, `period_years`, `is_continuation`