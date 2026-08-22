"""How much of the `dense_text` win survives the production reranker?

The gate that chose `dense_text` (gate_dense_text.py, docs §10.4) ran with `reranker=None`,
so what it measured was the *fused order*: top-3 +7 over 154 gold questions. Production runs
`reranker="qwen3-0.6b"`, and `CandidateRetriever._arerank` re-scores **the whole pool** and
replaces `pool.ranked` wholesale -- the fused order is discarded. So under the production
config the dense channel can only act through pool *membership*, never through order.

Two arms, because they answer different halves of that:

  (default)     membership only. Free: no reranker calls, and exact -- membership does not
                depend on the reranker (`_rerank_inputs`: "pool membership is unchanged, only
                the order moves"). This is the hard ceiling the reranker cannot recover from.
  --reranker    the actual production config. Measures gold rank in the *reranked* pool, so
                it captures the second-order effect membership alone cannot: a different 5
                tables in the pool changes what the cross-encoder ranks against, hence the
                top-20 window `judge_top_n` cuts on and the top-3 `codegen_max_tables` sends
                to codegen. Costs 154 HTTP calls per backend, ~1.6M tokens of Qwen3-Reranker-0.6B.

Run:
  PYTHONPATH=src:scripts .venv_bge/bin/python scripts/probe_dense_membership.py
  PYTHONPATH=src:scripts .venv_bge/bin/python scripts/probe_dense_membership.py --reranker
"""

import _bootstrap  # noqa: F401

import argparse
import asyncio

from finance_qa.modules.rag.candidates import CandidateRetriever
from finance_qa.modules.rag.retrievers.filters import load_tables

from gate_dense_text import load_gold94, load_unbiased60

BACKENDS = ("bge-m3", "bge-m3-dense-text")
# 20 is `judge_top_n` (what the judge is allowed to see) and 3 is `codegen_max_tables`
# (what reaches the solver). The others are context.
CUTOFFS = (1, 3, 5, 10, 20)


def membership(questions, backend, tables):
    """qid -> (frozenset(pool.ranked), gold_in_pool)."""
    retriever = CandidateRetriever(dense_backend=backend, tables=tables)
    out = {}
    for q, pool in zip(questions, retriever.build_pools(questions)):
        gold = set(q["gold_keys"])
        out[q["id"]] = (frozenset(pool.ranked), bool(gold & set(pool.ranked)))
    return out


def reranked(questions, backend, tables, reranker="qwen3-0.6b"):
    """qid -> best rank of any gold table in `pool.ranked`, None if absent.

    `reranker=None` gives the fused order through the exact same code path, which is what
    makes "does the rerank earn its place" answerable rather than a comparison across two
    scripts with two parquet paths.

    One retriever per backend, all 154 reranks in flight together -- the calls are IO and
    `abuild_pools` already gathers them.
    """
    retriever = CandidateRetriever(
        dense_backend=backend, reranker=reranker, tables=tables
    )
    pools = asyncio.run(retriever.abuild_pools(questions))
    out = {}
    for q, pool in zip(questions, pools):
        gold = set(q["gold_keys"])
        out[q["id"]] = min((i for i, k in enumerate(pool.ranked) if k in gold), default=None)
    return out


def report_membership(label, questions, base, treat):
    n = len(questions)
    same = [q["id"] for q in questions if base[q["id"]][0] == treat[q["id"]][0]]
    diff = [q["id"] for q in questions if base[q["id"]][0] != treat[q["id"]][0]]
    gained = [q for q in diff if treat[q][1] and not base[q][1]]
    lost = [q for q in diff if base[q][1] and not treat[q][1]]
    print(f"\n=== {label} membership (n={n}) ===")
    print(f"  identical membership   {len(same):>3}/{n}   differs {len(diff)}")
    print(
        f"  gold in pool           doc_text {sum(1 for v in base.values() if v[1]):>3}"
        f"   dense_text {sum(1 for v in treat.values() if v[1]):>3}"
    )
    print(f"  of the {len(diff)} that differ:  gold gained {len(gained)}  lost {len(lost)}")
    if gained:
        print(f"    gained: {gained}")
    if lost:
        print(f"    lost:   {lost}")
    if diff:
        sizes = sorted(len(base[q][0] ^ treat[q][0]) for q in diff)
        pools = sorted(len(base[q][0]) for q in diff)
        print(
            f"  symmetric difference   median {sizes[len(sizes) // 2]} tables "
            f"of a median {pools[len(pools) // 2]}-table pool"
        )


def _hits(ranks, cut=None):
    if cut is None:
        return sum(1 for v in ranks.values() if v is not None)
    return sum(1 for v in ranks.values() if v is not None and v < cut)


def report_order(label, arms):
    """arms: list of (name, qid->rank). Full 2x2 -- backend x rerank on/off."""
    n = len(arms[0][1])
    print(f"\n=== {label} order of pool.ranked (n={n}) ===")
    head = f"  {'arm':<28}{'pool':>6}" + "".join(f"{f'top-{c}':>8}" for c in CUTOFFS)
    print(head)
    print("  " + "-" * (len(head) - 2))
    for name, ranks in arms:
        cells = "".join(f"{_hits(ranks, c):>8}" for c in CUTOFFS)
        print(f"  {name:<28}{_hits(ranks):>6}{cells}")
    print("  top-3 = codegen_max_tables, top-20 = judge_top_n")
    for i in range(0, len(arms), 2):
        (na, a), (nb, b) = arms[i], arms[i + 1]
        moved = [(a[q], b[q]) for q in a if a[q] != b[q]]
        better = sum(1 for x, y in moved if x is None or (y is not None and y < x))
        print(
            f"  {na} -> {nb}: {len(moved)}/{n} moved, "
            f"{better} better, {len(moved) - better} worse"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reranker", action="store_true", help="also run the paid production arm")
    args = ap.parse_args()

    tables = load_tables()
    u60 = load_unbiased60()
    g94 = load_gold94(exclude={q["id"] for q in u60})
    for label, questions in (("unbiased60", u60), ("gold94", g94)):
        runs = {b: membership(questions, b, tables) for b in BACKENDS}
        report_membership(label, questions, runs[BACKENDS[0]], runs[BACKENDS[1]])
        if args.reranker:
            arms = []
            for rr in (None, "qwen3-0.6b"):
                tag = "fused" if rr is None else "reranked"
                for b in BACKENDS:
                    col = "doc_text" if b == "bge-m3" else "dense_text"
                    arms.append((f"{tag}, {col}", reranked(questions, b, tables, rr)))
            report_order(label, arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
