"""Deterministic tests for the shared candidate-pool API (no data files, no GPU, no LLM).

The retriever is built over a 5-table synthetic corpus with injected doc_text /
judge_text, so every policy in candidates.py is checked on the mechanism it was
introduced for rather than on eval-set aggregates.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.rag.candidates import (
    BOILERPLATE,
    PRIMARY_STATEMENT_TYPES,
    CandidateRetriever,
    add_primary_statements,
    assemble_pool,
    company_name_tokens,
    rerank_with_picks,
    rrf_fuse,
    strip_entity,
    table_key,
)
from finance_qa.modules.rag.retrievers.filters import MIN_ROWS, has_content


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


# -- pure helpers -----------------------------------------------------------

check("boilerplate covers the generic issuer words", {"công", "ty", "cổ", "phần"} <= BOILERPLATE)
check("primary statements are the four main reports", len(PRIMARY_STATEMENT_TYPES) == 4)

real = {"num_rows": 20, "first_col_labels": ["Tiền và tương đương tiền"]}
check("an ordinary table has content", has_content(real))
check("a table at the row floor has none", not has_content({**real, "num_rows": MIN_ROWS}))
check("one row past the floor is kept", has_content({**real, "num_rows": MIN_ROWS + 1}))
check("no row labels means nothing to retrieve on", not has_content({**real, "first_col_labels": []}))

names = company_name_tokens([
    {"ticker": "AAA", "company_name": "CTCP Alpha Anpha", "report_id": "r", "table_pos": 1},
    {"ticker": "BBB", "company_name": None, "report_id": "r", "table_pos": 2},
])
check("company name tokens are per ticker", names["AAA"] == {"ctcp", "alpha", "anpha"})
check("missing company name is not an error", names["BBB"] == set())

stripped = strip_entity("Tổng tài sản năm 2020 của CTCP Alpha (AAA) là bao nhiêu?", names["AAA"])
check("year is stripped", "2020" not in stripped)
check("issuer name tokens are stripped", "alpha" not in stripped and "ctcp" not in stripped)
check("boilerplate is stripped", "của" not in stripped.split())
# "tổng" is in BOILERPLATE for "Tổng công ty", so "tổng tài sản" keeps only its
# discriminative half. Deliberate: the stoplist is global, and "tổng" appears in
# every report's total rows anyway, so its IDF is near zero.
check("the asked-about concept survives", stripped.split()[:2] == ["tài", "sản"])
check("ticker survives (it is not part of the name)", "aaa" in stripped.split())

# Only the "both channels agree" property is worth asserting: at k=60 the rank
# curve is nearly flat, so 1/61 + 1/63 already beats 2/62 and finer orderings
# between two mid-ranked items are not a policy anyone chose.
fused = rrf_fuse(["a", "b"], ["b", "c"])
check("an item both channels return beats a single-channel top hit", fused[0] == "b")
check("rrf keeps every candidate of both channels", set(fused) == {"a", "b", "c"})
check("rrf is deterministic on ties", rrf_fuse(["x", "y"], ["x", "y"]) == ["x", "y"])

statement_types = {
    "r|1": "note", "r|2": "note", "r|3": "balance_sheet", "r|4": "income_statement",
}
keys = ["r|1", "r|2", "r|3", "r|4"]
expanded = add_primary_statements(["r|2", "r|1"], keys, statement_types)
check("primary statements are appended, not promoted", expanded == ["r|2", "r|1", "r|3", "r|4"])
check(
    "an already-ranked primary is not duplicated",
    add_primary_statements(["r|3"], keys, statement_types) == ["r|3", "r|4"],
)

check(
    "no rankings means the shortlist order is the pool",
    assemble_pool(keys, [], statement_types) == keys,
)
check(
    "a single ranking is used as-is",
    assemble_pool(keys, [["r|2"]], statement_types, expand_primary=False) == ["r|2"],
)
check(
    "two rankings are fused then expanded",
    assemble_pool(keys, [["r|1"], ["r|2"]], statement_types) == ["r|1", "r|2", "r|3", "r|4"],
)

check(
    "judge picks go on top and the tail keeps retrieval order",
    rerank_with_picks(["a", "b", "c", "d"], ["c", "a"]) == ["c", "a", "b", "d"],
)
check(
    "an empty pick list degrades to the retrieval ranking",
    rerank_with_picks(["a", "b"], []) == ["a", "b"],
)


# -- retriever over a synthetic corpus ------------------------------------

REPORT = "AAA_financial_statements_2020_consolidated"
OTHER = "BBB_financial_statements_2020_consolidated"


def table(
    report_id: str,
    pos: int,
    ticker: str,
    statement_type: str,
    *,
    num_rows: int = 20,
    first_col_labels: list[str] | None = None,
) -> dict:
    return {
        "report_id": report_id,
        "table_pos": pos,
        "ticker": ticker,
        "year": 2020,
        "doc_type": "consolidated",
        "company_name": "CTCP Alpha" if ticker == "AAA" else "CTCP Beta",
        "statement_type": statement_type,
        # Read by `filters.has_content`; defaults describe an ordinary table.
        "num_rows": num_rows,
        "first_col_labels": first_col_labels if first_col_labels is not None else ["Tài sản"],
    }


TABLES = [
    table(REPORT, 1, "AAA", "note"),          # lexically closest to the question
    table(REPORT, 2, "AAA", "note"),
    table(REPORT, 3, "AAA", "balance_sheet"),  # the GT shape: no lexical overlap
    table(REPORT, 4, "AAA", "entity_info"),    # repeats the company name verbatim
    # Content-free OCR fragments, one of each shape has_content() drops. #5 is a
    # primary statement on purpose: the filter has to beat primary expansion, or
    # every report contributes its split balance-sheet headers to every pool.
    table(REPORT, 5, "AAA", "balance_sheet", num_rows=2),
    table(REPORT, 6, "AAA", "note", first_col_labels=[]),
    table(OTHER, 1, "BBB", "balance_sheet"),   # wrong ticker, must not be shortlisted
]
DOC_TEXTS = {
    f"{REPORT}|1": "thuyết minh tổng tài sản chi tiết tài sản",
    f"{REPORT}|2": "thuyết minh tài sản cố định tổng",
    f"{REPORT}|3": "bảng cân đối kế toán",
    f"{REPORT}|4": "thông tin doanh nghiệp ctcp alpha",
    f"{REPORT}|5": "bảng cân đối kế toán tài sản",
    f"{REPORT}|6": "thuyết minh tài sản",
    f"{OTHER}|1": "bảng cân đối kế toán",
}
JUDGE_TEXTS = {key: f"narrow::{text}" for key, text in DOC_TEXTS.items()}
QUESTION = {
    "question": "Tổng tài sản năm 2020 của CTCP Alpha (AAA) là bao nhiêu?",
    "tickers": ["AAA"],
    "years": [2020],
    "doc_type": "consolidated",
}


def retriever(**kwargs) -> CandidateRetriever:
    return CandidateRetriever(
        use_dense=False,
        tables=TABLES,
        doc_texts=DOC_TEXTS,
        judge_texts=JUDGE_TEXTS,
        **kwargs,
    )


# channel_k=2 keeps the balance sheet out of the ranking, which is the situation
# primary expansion exists for: on the real corpus the notes are ~71% of a report.
pool = retriever(channel_k=2).build_pool(QUESTION)
check("shortlist is scoped to the question's ticker", pool.keys == [f"{REPORT}|{i}" for i in (1, 2, 3, 4)])
check("a 2-row fragment is dropped even though it is a primary statement", f"{REPORT}|5" not in pool.ranked)
check("a table with no row labels is dropped", f"{REPORT}|6" not in pool.ranked)
check("retrieval query is the stripped one", pool.query == "tài sản aaa")
check("bm25 channel is capped at channel_k", len(pool.rankings["bm25"]) == 2)
check("the lexical winner is a note", pool.rankings["bm25"][0] == f"{REPORT}|1")
check("primary expansion rescues the balance sheet", f"{REPORT}|3" in pool.ranked)
check("expansion appends below the ranking", pool.ranked.index(f"{REPORT}|3") >= 2)
check("expansion does not pull in non-primary tables", f"{REPORT}|4" not in pool.ranked)

bare = retriever(channel_k=2, expand_primary=False).build_pool(QUESTION)
check("without expansion the balance sheet is lost", f"{REPORT}|3" not in bare.ranked)

raw = retriever(channel_k=2, strip_query=False).build_pool(QUESTION)
check("raw query keeps the company name", raw.query == QUESTION["question"])
check(
    "raw query lets entity_info outrank a real note",
    f"{REPORT}|4" in raw.rankings["bm25"] and f"{REPORT}|4" not in pool.rankings["bm25"],
)

items = retriever(channel_k=2).judge_items(pool)
check("judge sees the pool in pool order", [key for key, _ in items] == pool.ranked)
check("judge reads judge_text, not the indexed doc_text", items[0][1].startswith("narrow::"))

# judge_top_n narrows what the judge is *shown*; the pool keeps its tail so
# `rerank_with_picks` and the deeper Ks still measure the full ranking.
narrowed = retriever(channel_k=2, judge_top_n=2).judge_items(pool)
check("judge_top_n cuts the judge's view to the head of the pool", len(pool.ranked) > 2)
check("the cut is a prefix, not a resort", [key for key, _ in narrowed] == pool.ranked[:2])
try:
    retriever(judge_top_n=0)
    zero_accepted = True
except ValueError:
    zero_accepted = False
check("judge_top_n below 1 is rejected", not zero_accepted)

no_texts = CandidateRetriever(use_dense=False, tables=TABLES, doc_texts=DOC_TEXTS)
try:
    no_texts.judge_items(pool)
    judged_without_text = True
except RuntimeError:
    judged_without_text = False
check("judging without judge_text fails loudly", not judged_without_text)

batch = retriever(channel_k=2).build_pools([QUESTION, {**QUESTION, "tickers": ["BBB"]}])
check("batching keeps per-question pools separate", batch[1].keys == [f"{OTHER}|1"])
check("batch and single-question pools agree", batch[0].ranked == pool.ranked)

check("table_key matches the corpus id format", table_key(TABLES[0]) == f"{REPORT}|1")

print("tất cả PASS")
