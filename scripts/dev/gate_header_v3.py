"""Retrieval gate for the header_flat v3 experiment (docs/retrieval_preprocessing_2026-08-21.md §6).

Builds a `CandidateRetriever(reranker=None, judge_top_n=20)` over the 60
`data/eval/unbiased60_gold.jsonl` questions (joined to `questions_enriched.jsonl` for
tickers/years/doc_type), once against the v2 `tables_doc_text.parquet` and once against the
staged v3 `tables_doc_text_v3.parquet`, and reports where each question's gold table(s) land:
shortlist (hard filter) / pool (post BM25 + primary-statement expansion) / head-20
(`pool.ranked[:20]`, the judge's window) / top-3 (`pool.ranked[:3]`, `codegen_max_tables`).

`evidence_table_id` is `;`/`&`-separated when a question needs several tables (22/60 rows);
CONTEXT.md calls the group atomic. A question counts as a hit at a cutoff if ANY of its gold
tables is present there (matches how `docs/retrieval_preprocessing_2026-08-21.md` §0 derives
33/60 top-3 from "rank of the gold table" -- one rank per question, best case over its group).

Run:
  PYTHONPATH=src .venv_bge/bin/python scripts/gate_header_v3.py            # BM25 only
  PYTHONPATH=src .venv_bge/bin/python scripts/gate_header_v3.py --dense    # BM25 + dense RRF
"""

import _bootstrap  # noqa: F401

import json
import re

from finance_qa.core.paths import DATA_DIR, EVAL_DIR, INDEXES_DIR, METADATA_DIR
from finance_qa.modules.rag.candidates import CandidateRetriever, table_key
from finance_qa.modules.rag.retrievers.filters import load_tables


GOLD_PATH = EVAL_DIR / "unbiased60_gold.jsonl"
QUESTIONS_PATH = METADATA_DIR / "questions_enriched.jsonl"

DOC_TEXT_V2 = INDEXES_DIR / "tables_doc_text.parquet"
DOC_TEXT_V3 = INDEXES_DIR / "tables_doc_text_v3.parquet"
METADATA_V3 = METADATA_DIR / "tables_metadata_v3.jsonl"

DENSE_PROD = INDEXES_DIR / "tables_dense.npy"
DENSE_V2_REBUILT = INDEXES_DIR / "tables_dense_v2rebuilt.npy"
DENSE_V3 = INDEXES_DIR / "tables_dense_v3.npy"

_KEY_RE = re.compile(r"^([A-Za-z0-9_]+\|\d+)")


def parse_gold_keys(evidence_table_id: str) -> list[str]:
    keys = []
    for frag in re.split(r"[;&]", evidence_table_id):
        m = _KEY_RE.match(frag.strip())
        if m:
            keys.append(m.group(1))
    return keys


def load_questions() -> list[dict]:
    gold = [json.loads(line) for line in GOLD_PATH.open(encoding="utf-8")]
    gold = [g for g in gold if g.get("evidence_table_id")]
    by_id = {g["id"]: g for g in gold}

    enriched_by_id = {}
    with QUESTIONS_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            if rec["id"] in by_id:
                enriched_by_id[rec["id"]] = rec

    out = []
    for qid, g in by_id.items():
        q = dict(enriched_by_id[qid])
        q["gold_keys"] = parse_gold_keys(g["evidence_table_id"])
        out.append(q)
    return out


def load_doc_texts(parquet_path) -> dict[str, str]:
    import pandas as pd

    df = pd.read_parquet(parquet_path, columns=["report_id", "table_pos", "doc_text"])
    keys = (df["report_id"] + "|" + df["table_pos"].astype(str)).tolist()
    return dict(zip(keys, df["doc_text"]))


def build_retriever(
    *,
    doc_texts: dict[str, str],
    tables: list[dict] | None = None,
    reranker: str | None = None,
) -> CandidateRetriever:
    return CandidateRetriever(
        use_bm25=True,
        use_dense=False,
        reranker=reranker,
        judge_top_n=20,
        tables=tables,
        doc_texts=doc_texts,
    )


def build_dense_retriever(
    *,
    parquet_path,
    index_path,
    tables: list[dict] | None = None,
    reranker: str | None = None,
) -> CandidateRetriever:
    """BM25 + dense RRF, both channels reading `parquet_path`.

    Two things `CandidateRetriever` does not expose as arguments have to be bent here, and
    both are deliberate in the production design rather than oversights:

    - `use_dense=True` reads `DOCUMENT_TEXT_PATH` directly, because the dense index carries
      no key column and is aligned to that parquet by row position. Passing a `doc_texts`
      dict would lose the order, so the module-level constant is patched instead -- which
      also guarantees BM25 and dense read the *same* text within an arm.
    - `index_path` belongs to the embedding client, not the caller, so that a query vector
      can never be matched against another encoder's index (clients.py docstring). Same
      encoder here, different index file, so overriding it on the instance is safe.
    """
    from finance_qa.modules.rag import candidates as candidates_mod
    from finance_qa.modules.rag.indexing.dense import BgeM3Embedder

    embedder = BgeM3Embedder()
    embedder.index_path = index_path

    original = candidates_mod.DOCUMENT_TEXT_PATH
    candidates_mod.DOCUMENT_TEXT_PATH = parquet_path
    try:
        return CandidateRetriever(
            use_bm25=True,
            use_dense=True,
            dense_backend=embedder,
            reranker=reranker,
            judge_top_n=20,
            tables=tables,
        )
    finally:
        candidates_mod.DOCUMENT_TEXT_PATH = original


def run_gate(label: str, retriever: CandidateRetriever, questions: list[dict]) -> None:
    n = len(questions)
    hits_shortlist = hits_pool = hits_head20 = hits_top3 = 0
    pools = retriever.build_pools(questions)
    for q, pool in zip(questions, pools):
        gold = set(q["gold_keys"])
        keyset = set(pool.keys)
        ranked = pool.ranked
        if gold & keyset:
            hits_shortlist += 1
        if gold & set(ranked):
            hits_pool += 1
        if gold & set(ranked[:20]):
            hits_head20 += 1
        if gold & set(ranked[:3]):
            hits_top3 += 1

    print(f"\n=== {label} (n={n}) ===")
    print(f"  gold in shortlist : {hits_shortlist}/{n} = {hits_shortlist / n:.1%}")
    print(f"  gold in pool      : {hits_pool}/{n} = {hits_pool / n:.1%}")
    print(f"  gold in head-20   : {hits_head20}/{n} = {hits_head20 / n:.1%}")
    print(f"  gold in top-3     : {hits_top3}/{n} = {hits_top3 / n:.1%}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reranker", default=None, help='e.g. "qwen3-0.6b"; default None')
    parser.add_argument("--dense", action="store_true", help="BM25 + dense RRF, 3 arms")
    args = parser.parse_args()

    questions = load_questions()
    print(f"Loaded {len(questions)} gold questions with evidence_table_id")
    label_suffix = f" + reranker={args.reranker}" if args.reranker else ""

    tables_v2 = load_tables()

    if args.dense:
        # A -> B isolates whether the shipped index is stale (it was built from a v1 text
        # that no longer exists on disk, so the two cannot be diffed directly);
        # B -> C isolates the header_flat change itself, same encoder, same builder.
        arms = [
            (f"A production: doc_text v2 + tables_dense.npy{label_suffix}", DOC_TEXT_V2, DENSE_PROD),
            (f"B v2 rebuilt: doc_text v2 + v2rebuilt.npy{label_suffix}", DOC_TEXT_V2, DENSE_V2_REBUILT),
            (f"C v3: doc_text v3 + v3.npy{label_suffix}", DOC_TEXT_V3, DENSE_V3),
        ]
        for label, parquet_path, index_path in arms:
            retriever = build_dense_retriever(
                parquet_path=parquet_path,
                index_path=index_path,
                tables=tables_v2,
                reranker=args.reranker,
            )
            run_gate(label, retriever, questions)
        return 0

    doc_texts_v2 = load_doc_texts(DOC_TEXT_V2)
    retriever_v2 = build_retriever(doc_texts=doc_texts_v2, tables=tables_v2, reranker=args.reranker)
    run_gate(f"v2 baseline{label_suffix}", retriever_v2, questions)

    doc_texts_v3 = load_doc_texts(DOC_TEXT_V3)
    retriever_v3 = build_retriever(doc_texts=doc_texts_v3, tables=tables_v2, reranker=args.reranker)
    run_gate(f"v3 (header_flat re-derived){label_suffix}", retriever_v3, questions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
