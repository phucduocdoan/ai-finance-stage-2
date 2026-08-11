# Retrieval Pipeline

Active implementation:

```text
src/finance_qa/modules/rag/candidates.py
src/finance_qa/modules/rag/service.py
src/finance_qa/modules/rag/indexing/
src/finance_qa/modules/rag/retrievers/
src/finance_qa/modules/rag/rerankers/
src/finance_qa/modules/rag/judge.py
```

## Flow

```text
Question metadata
  -> hard filter: ticker/year/doc_type/content
  -> BM25 channel
  -> dense channel
  -> RRF ordering
  -> primary-statement expansion
  -> optional reranker
  -> LLM judge
  -> selected table ids
```

## Hard Filter

The filter tier uses structured metadata before semantic scoring:

- ticker: keep matching companies when resolved;
- year: keep matching report years when resolved;
- doc type: use explicit separate/consolidated scope when question says so;
- content: drop empty/junk tables;
- unknown scope: prefer consolidated reports softly when both scopes exist.

If ticker/year is missing in graph retrieval, `modules.rag.service` can fall back to the frozen
run cache when `FinanceAgentConfig.frozen_fallback=True`.

## Text Channels

Retrieval text is table-level, not chunk-level. Each table is one candidate.

Important metadata signals:

```text
statement_label
note_title
section_title
first_col_labels
header_flat
```

The judge uses a tighter view than the index where appropriate so prompt budget is spent on
discriminative labels instead of repeated headers.

## Candidate Policy

The retriever combines:

- BM25 top-k;
- dense top-k;
- RRF order for deterministic prompt ordering;
- primary statement expansion for `balance_sheet`, `income_statement`, `cash_flow`,
  and `equity_change`.

Primary expansion is structural recall insurance: these tables are sparse inside a report and
many finance formulas depend on them even when lexical matching favors notes.

## Reranking And Judge

Reranker backends are configured in `src/finance_qa/modules/rag/retrievers/clients.py`.
The graph default uses `reranker="qwen3-0.6b"` with `judge_top_n=20`.

The judge reads the question and candidate `judge_text`, then returns table picks. Empty picks
are treated as a retrieval failure by the batch runner and can fall back to retrieval order or
frozen ids depending on the caller.

## Evaluation

Retrieval-only diagnostics use `scripts/evaluate_retrieval.py`.

Common examples:

```bash
PYTHONPATH=src .venv_bge/bin/python scripts/evaluate_retrieval.py --stage filter
PYTHONPATH=src .venv_bge/bin/python scripts/evaluate_retrieval.py --stage bm25
```

Dense stages require the GPU/index environment. Judge/reranker stages require the configured
LLM/API backend.

## Current Guidance

- Do not hard-deduplicate continuation pages to a single table; continuation pages can hold the
  exact queried row.
- Do not add dormant metadata fields to hard filters without measured recall impact.
- Keep new dense experiments in separate index files.
- Treat report-tier retrieval and table-tier retrieval separately when debugging misses.
