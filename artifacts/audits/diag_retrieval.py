"""Throwaway diagnostic: for each of the 18(+2) gold questions whose gold table
never reached the judge's final table_ids, find the exact stage where it dropped
out of CandidateRetriever's chain.

Does NOT modify anything under src/. Imports the real retriever and calls its
internal pieces in sequence (shortlist -> bm25/dense channels -> RRF fuse ->
primary expansion -> reranker -> judge window -> judge -> service._evidence),
recording gold-table membership after each stage.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

sys.path.insert(0, "/home/ding/ai-finance-stage-2/src")

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.rag.candidates import (
    CandidateRetriever,
    add_primary_statements,
    assemble_pool,
    rrf_fuse,
)
from finance_qa.modules.rag.retrievers.filters import shortlist
from finance_qa.modules.rag.service import _evidence

import numpy as np

QIDS_MISS = [166, 259, 280, 355, 488, 502, 521, 542, 553, 685, 744, 753, 759, 790, 856, 920, 955, 974]
QIDS_CUT = [525, 530]
ALL_IDS = QIDS_MISS + QIDS_CUT

GOLD_FILES = [
    "/home/ding/ai-finance-stage-2/data/eval/unbiased60_gold.jsonl",
    "/home/ding/ai-finance-stage-2/data/eval/manual15_gold.jsonl",
]
ENRICHED_PATH = "/home/ding/ai-finance-stage-2/data/metadata/questions_enriched.jsonl"
RUN_PATH = "/home/ding/ai-finance-stage-2/artifacts/runs/full1012_qwen35.jsonl"

TABLE_ID_RE = re.compile(r"[\w.\-]+\|\d+")


def load_gold() -> dict[int, dict]:
    out = {}
    for path in GOLD_FILES:
        with open(path, encoding="utf-8") as fh:
            for line in filter(str.strip, fh):
                row = json.loads(line)
                if row["id"] in ALL_IDS:
                    out[row["id"]] = row
    return out


def load_enriched() -> dict[int, dict]:
    out = {}
    with open(ENRICHED_PATH, encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            row = json.loads(line)
            if row["id"] in ALL_IDS:
                out[row["id"]] = row
    return out


def load_run() -> dict[int, dict]:
    out = {}
    with open(RUN_PATH, encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            row = json.loads(line)
            if row["id"] in ALL_IDS:
                out[row["id"]] = row
    return out


def gold_tables(row: dict) -> list[str]:
    field = row.get("evidence_table_id") or ""
    return TABLE_ID_RE.findall(field)


async def main():
    gold = load_gold()
    enriched = load_enriched()
    runs = load_run()

    missing_gold = [i for i in ALL_IDS if i not in gold]
    if missing_gold:
        print(f"!! ids missing from gold files: {missing_gold}")

    cfg = FinanceAgentConfig()  # production defaults: reranker=qwen3-0.6b, judge_top_n=20
    print(f"cfg: reranker={cfg.reranker} judge_top_n={cfg.judge_top_n} judge_thinking={cfg.judge_thinking}")

    understand_fn = make_understand(cfg)

    print("building retriever (bm25 + bge-m3 dense + doc_text + judge_text)...")
    retriever = CandidateRetriever(
        load_judge_text=True,
        reranker=cfg.reranker,
        judge_top_n=cfg.judge_top_n,
    )
    print("retriever built.")

    # ---- table metadata existence check (fifth possible verdict) ----
    all_keys = {f"{t['report_id']}|{t['table_pos']}" for t in retriever.tables}

    results = []
    for qid in ALL_IDS:
        grow = gold.get(qid)
        if grow is None:
            continue
        gtabs = gold_tables(grow)
        question_text = grow["question"]
        erow = enriched.get(qid, {})
        run_row = runs.get(qid, {})
        actual_table_ids = set(run_row.get("table_ids") or [])

        # existence check
        absent_from_corpus = [g for g in gtabs if g not in all_keys]

        # 1. live understand() call, same as the real graph
        state = {"question": question_text, "errors": []}
        u = await understand_fn(state)
        tickers, years, doc_type = u["tickers"], u["years"], u["doc_type"]

        qd = {"question": question_text, "tickers": tickers, "years": years, "doc_type": doc_type}

        # 2. hard filter
        cands = shortlist(qd, retriever.index, all_tables=retriever.tables)
        keys = [f"{t['report_id']}|{t['table_pos']}" for t in cands]
        survived_filter = [g for g in gtabs if g in keys]

        # 3. BM25 + dense channels (mirrors CandidateRetriever._fuse)
        query = retriever.query_for(qd)
        rankings = {}
        bm25_hits, dense_hits = [], []
        if keys and retriever.bm25 is not None:
            bm25_order = [k for k, _ in retriever.bm25.top_k(query, keys, k=retriever.channel_k)]
            rankings["bm25"] = bm25_order
            bm25_hits = [g for g in gtabs if g in bm25_order]
        if keys and retriever._dense is not None:
            qvec = retriever._encode([query])[0]
            vecs, row_of = retriever._dense
            rows = np.array([row_of[k] for k in keys])
            sims = vecs[rows].astype(np.float32) @ qvec.astype(np.float32)
            order_idx = np.argsort(-sims)[: retriever.channel_k]
            dense_order = [keys[i] for i in order_idx]
            rankings["dense"] = dense_order
            dense_hits = [g for g in gtabs if g in dense_order]

        # RRF fuse only (pre-primary-expansion), for the "post-RRF" column
        if len(rankings) >= 2:
            rrf_only = rrf_fuse(*rankings.values())
        elif len(rankings) == 1:
            rrf_only = list(rankings[list(rankings)[0]])
        else:
            rrf_only = list(keys)
        post_rrf_hits = [g for g in gtabs if g in rrf_only]

        # full pool assembly (RRF + primary-statement expansion) == what _fuse returns
        fused = assemble_pool(keys, list(rankings.values()), retriever.statement_types, expand_primary=True)
        added_by_primary = [g for g in gtabs if g in fused and g not in rrf_only]

        # 4. reranker over the fused pool, original (unstripped) question
        reranked = fused
        rank_of = {}
        if retriever.reranker is not None and fused:
            texts = [retriever.doc_texts[k] for k in fused]
            from finance_qa.modules.rag.retrievers.clients import arerank_order
            reranked = await arerank_order(retriever.reranker, question_text, fused, texts)
        for g in gtabs:
            if g in reranked:
                rank_of[g] = reranked.index(g) + 1  # 1-based

        # 5. judge window
        judge_top_n = retriever.judge_top_n
        window = reranked[:judge_top_n] if judge_top_n else reranked
        in_window = [g for g in gtabs if g in window]

        # 6. run the actual judge on the window
        items = [(k, retriever.judge_texts[k]) for k in window]
        picks = await retriever.judge.apick(question_text, items, thinking=cfg.judge_thinking)

        # 7. service._evidence: picks + unpicked primary-statement tables from the WHOLE fused pool
        class FakePool:
            pass
        fp = FakePool()
        fp.ranked = fused
        final_table_ids = _evidence(retriever, fp, picks)
        gold_in_final = [g for g in gtabs if g in final_table_ids]
        gold_in_actual_run = [g for g in gtabs if g in actual_table_ids]

        results.append(dict(
            qid=qid,
            gold=gtabs,
            enriched_tickers=erow.get("tickers"), enriched_years=erow.get("years"), enriched_doc_type=erow.get("doc_type"),
            live_tickers=tickers, live_years=years, live_doc_type=doc_type,
            absent_from_corpus=absent_from_corpus,
            survived_filter=survived_filter,
            bm25_hits=bm25_hits, dense_hits=dense_hits,
            post_rrf_hits=post_rrf_hits, added_by_primary=added_by_primary,
            rank_of=rank_of, pool_size=len(fused),
            in_window=in_window,
            judge_picks=picks, gold_in_final=gold_in_final,
            gold_in_actual_run=gold_in_actual_run,
            n_gold=len(gtabs),
        ))
        print(f"qid={qid} gold={gtabs} filt={survived_filter} bm25={bm25_hits} dense={dense_hits} "
              f"rrf={post_rrf_hits} +primary={added_by_primary} rank={rank_of} window={in_window} "
              f"final={gold_in_final} actual_run={gold_in_actual_run}")

    with open("/tmp/diag_retrieval_results.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print("wrote /tmp/diag_retrieval_results.json")


if __name__ == "__main__":
    asyncio.run(main())
