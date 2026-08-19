"""Where in the retrieval chain does the gold table fall out?

Read-only. Replays understand -> shortlist -> BM25/dense -> pool -> reranker ->
judge for the 60 cell-truth questions and reports the first gate that drops the
gold table. Touches no artifact: CandidateRetriever only reads them.
"""
from __future__ import annotations
import asyncio, json, collections, sys
from pathlib import Path
sys.path.insert(0, "src")

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.rag.service import get_retriever, _PRIMARY
from finance_qa.modules.rag.candidates import add_primary_statements

GOLD = [json.loads(l) for l in filter(str.strip, Path("data/eval/unbiased60_gold.jsonl").read_text().splitlines())]


async def main() -> None:
    cfg = FinanceAgentConfig()
    understand = make_understand(cfg)
    retriever = get_retriever(cfg.reranker, cfg.judge_top_n)
    out = []
    for g in GOLD:
        gt = [t for t in str(g["evidence_table_id"]).replace(";", " ").split() if "|" in t]
        st = await understand({"id": g["id"], "question": g["question"]})
        q = {"question": g["question"], "tickers": st.get("tickers") or [],
             "years": st.get("years") or [], "doc_type": st.get("doc_type") or "unknown"}
        if not q["tickers"] or not q["years"]:
            out.append({"id": g["id"], "stage": "0. understand không ra ticker/năm", "gt": gt}); continue

        pool = await retriever.abuild_pool(q)                # fuse + rerank
        shortlist = set(pool.keys)
        bm25 = set(pool.rankings.get("bm25") or [])
        dense = set(pool.rankings.get("dense") or [])
        fused = set(pool.rankings.get("fused") or pool.ranked)   # after primary expansion
        ranked = pool.ranked
        judge_in = [k for k, _ in retriever.judge_items(pool)]
        picks = await retriever.judge.apick(g["question"], retriever.judge_items(pool), thinking=cfg.judge_thinking)
        chosen = set(picks)
        primary_tail = [k for k in ranked if retriever.statement_types.get(k) in _PRIMARY and k not in chosen]
        final = picks + primary_tail

        hit = lambda s: any(t in s for t in gt)
        if not hit(shortlist):      stage = "1. HARD FILTER loại (ticker/năm/doc_type)"
        elif not hit(bm25 | dense): stage = "2. không lọt BM25@20 ∪ dense@20"
        elif not hit(fused):        stage = "3. mất khi gộp pool"
        elif not hit(set(judge_in)):stage = "4. RERANKER đẩy khỏi top-20 của judge"
        elif not hit(chosen):       stage = "5. JUDGE nhìn thấy mà KHÔNG chọn"
        elif not hit(set(final)):   stage = "6. mất ở bước ghép evidence"
        else:                       stage = "OK - có trong kết quả"
        rank_in_ranked = min([ranked.index(t) + 1 for t in gt if t in ranked] or [None]) if any(t in ranked for t in gt) else None
        out.append({"id": g["id"], "stage": stage, "gt": gt,
                    "n_shortlist": len(shortlist), "n_pool": len(ranked),
                    "in_bm25": hit(bm25), "in_dense": hit(dense),
                    "rank_after_rerank": rank_in_ranked, "n_picks": len(picks),
                    "n_primary_tail": len(primary_tail),
                    "rank_in_bm25": min([(pool.rankings.get("bm25") or []).index(t) + 1 for t in gt if t in (pool.rankings.get("bm25") or [])] or [None])})
        print(f"  [{g['id']}] {out[-1]['stage']}", flush=True)

    Path("artifacts/audits/diag_retrieval_stages.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n=== bảng gold rơi ở cửa nào (60 câu) ===")
    for s, n in sorted(collections.Counter(x["stage"] for x in out).items()):
        print(f"  {s:<45} {n:>3}")

asyncio.run(main())
