# Metadata Audit

Current corpus metadata lives in `data/metadata/tables_metadata_v2.jsonl`.

## Snapshot

| Item | Value |
|---|---:|
| Tables | 146,246 |
| OCR reports | 1,973 |
| Enriched questions | 1,012 |
| Main metadata file | `data/metadata/tables_metadata_v2.jsonl` |
| Retrieval text/index files | `data/indexes/tables_doc_text.parquet`, `data/indexes/tables_dense.npy` |

## Fields Used By Runtime Code

Runtime retrieval and loading use these table metadata fields:

```text
ticker
year
doc_type
table_pos
report_id
note_title
first_col_labels
statement_type
statement_subtype
section_title
csv_path
num_rows
header_flat
company_name
```

Question metadata used by runtime:

```text
id
question
tickers
years
doc_type
unit_hint
```

## Fields To Treat Carefully

Some metadata fields are useful for analysis but are not part of the active hard-filter
contract:

```text
period_years
period_columns_raw
industry_segment
is_continuation
context_page_text
note_id
note_id_inherited
mau_tag
has_ma_so_column
statement_type_source
page_number
num_cols
```

Do not add these to hard filters without a measured retrieval impact. In particular,
continuation pages often contain the queried row, so dropping them structurally can lose
recall.

## Current Retrieval Contract

The active retrieval pipeline uses:

- hard filtering by ticker/year/doc_type when available;
- content filtering for empty/junk tables;
- soft consolidated preference when question scope is unknown;
- BM25 and dense channels over document text;
- primary-statement expansion for balance sheet, income statement, cash flow, and equity change;
- LLM judge over `judge_text`.

Metadata is enough for the current filter tier. The main remaining retrieval challenge is
selecting the correct table within an already-correct report, especially when notes and main
statements both contain related terms.

## Protected Artifacts

Do not overwrite these without a deliberate rebuild plan:

```text
data/metadata/tables_metadata_v2.jsonl
data/indexes/tables_doc_text.parquet
data/indexes/tables_dense.npy
```

If a new dense backend or metadata variant is needed, write a new file and update the code to
select it explicitly.
