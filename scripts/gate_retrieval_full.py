"""Full retrieval A/B: the production path end to end, scored the way the leaderboard is.

Everything upstream of this gate measured `pool.ranked`, which no submission ever contains.
The submitted lists come from `service._evidence` -- judge picks first, then every primary
statement in the shortlist -- so the last two stages (judge, primary expansion) are exactly
where a change either converts or evaporates.

Three presets, `--arms`:

  backend    doc_text vs dense_text. Measured on `pool.ranked`, `dense_text` is top-3 +7
             before the reranker and a wash after it (docs §10.4-10.5); this asks whether it
             moves what gets submitted.
  control    the same config twice: the churn floor. The judge is an LLM, so a delta is only
             a result if two identical arms move less than it. vLLM's continuous batching is
             not bit-reproducible even at temperature 0, so this floor is not zero.
  reasoning  does letting the judge reason before it picks help? `judge_thinking=True` cannot
             answer that on the current checkpoint: the Qwen3 template leaves `<think>` open
             and Qwen3.5-9B reasons in plain prose without ever emitting `</think>`, so vLLM's
             reasoning parser buffers the whole budget and returns content=None,
             finish_reason=length, at 256 through 16384 tokens alike (docs §10.8). With
             `enable_thinking=False` the template closes the block itself and the model
             answers in 12 tokens. So the reasoning arm keeps thinking off and moves the
             reasoning into the reply: same pool, same candidates, one instruction changed
             from "chỉ in ra JSON, không giải thích" to a short rationale before the JSON,
             with the token budget raised to match.

Builds `CandidateRetriever` directly rather than calling `aretrieve_table_ids`, because a
judge instance cannot be threaded through `rag.service` -- but it applies the very same
`service._evidence`, and the `backend` preset reproduces the numbers the service path
produced, which is the check that the two are the same pipeline.

Costs per arm: 154 reranker calls (Qwen3-Reranker-0.6B, ~1.6M tokens) and 154 judge calls
against the local vLLM.

The judge model is whatever the local server has loaded. `LLM_MODEL`'s default
(`Qwen/Qwen3-8B-Instruct`) 404s against it, so it must be set explicitly, and the absolute
numbers are not comparable to the 0.9268 DOCS on the leaderboard -- that run used a different
model. Arms run back to back against the same server, so the delta between them is the readout.

Run:
  LLM_MODEL=Qwen3.5-9B PYTHONPATH=src:scripts .venv_bge/bin/python \
    scripts/gate_retrieval_full.py --arms backend|control|reasoning
"""

import _bootstrap  # noqa: F401

import argparse
import asyncio

from finance_qa.evaluation.retrieval import dedupe_reports, f2_score
from finance_qa.modules.rag.candidates import CandidateRetriever
from finance_qa.modules.rag.judge import PROMPT, Judge, build_prompt
from finance_qa.modules.rag.retrievers.filters import load_tables
from finance_qa.modules.rag.service import _evidence

from gate_dense_text import load_gold94, load_unbiased60

CUTOFFS = (1, 3, 5)

# The production prompt's last two lines forbid any output but the JSON, so raising the token
# budget alone changes nothing -- the model obeys and answers in 12 tokens. This is the
# smallest edit that lets it reason at all: same task, same candidates, same pick cap.
_BARE_JSON = 'Chỉ in ra JSON, không giải thích:\n{{"picks": [số, số, ...]}}'
_REASON_THEN_JSON = (
    "Trước khi chọn, viết ngắn gọn (tối đa 5 dòng) vì sao mỗi bảng bạn định chọn chứa số liệu\n"
    "cần thiết, và vì sao loại các bảng gần giống. Sau đó, ở DÒNG CUỐI CÙNG, chỉ in JSON:\n"
    '{{"picks": [số, số, ...]}}'
)


class ReasoningJudge(Judge):
    """`Judge` that asks for a rationale before the pick list.

    Only the closing instruction differs; `parse_picks` already regexes `"picks": [...]` out
    of prose, so nothing downstream changes. `max_tokens` has to rise with it: the default 256
    is sized for the bare-JSON reply and would truncate the rationale before the JSON, leaving
    `parse_picks` to scrape digits out of half a sentence.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("max_tokens", 1536)
        super().__init__(**kwargs)

    def build_prompt(self, question: str, pool: list[tuple[str, str]]) -> str:
        assert _BARE_JSON in PROMPT, "judge PROMPT changed; re-derive the reasoning variant"
        rendered = build_prompt(question, pool, self.max_picks)
        return rendered.replace(
            _BARE_JSON.replace("{{", "{").replace("}}", "}"),
            _REASON_THEN_JSON.replace("{{", "{").replace("}}", "}"),
        )


SERVICE = "service path"


def arms_for(preset):
    """(name, dense_backend, judge factory or None) per arm."""
    if preset == "backend":
        return [("doc_text", "bge-m3", None), ("dense_text", "bge-m3-dense-text", None)]
    if preset == "control":
        return [("doc_text", "bge-m3", None), ("doc_text (again)", "bge-m3", None)]
    if preset == "equiv":
        return [("doc_text", "bge-m3", None), (SERVICE, "bge-m3", None)]
    return [
        ("bare json", "bge-m3", None),
        ("reason then json", "bge-m3", ReasoningJudge),
    ]


async def _run_service(questions, backend):
    """The same arm through `rag.service`, to show this gate is that pipeline.

    `frozen_fallback=False` so a failure shows up as a failure instead of being backfilled
    from the frozen cache -- a fallback would make the arms converge on cached ids.
    """
    from finance_qa.modules.rag.service import aretrieve_table_ids

    results = await asyncio.gather(
        *(
            aretrieve_table_ids(
                q["question"],
                int(q["id"]),
                list(q.get("tickers") or []),
                list(q.get("years") or []),
                str(q.get("doc_type") or "unknown"),
                reranker="qwen3-0.6b",
                judge_top_n=20,
                frozen_fallback=False,
                judge_thinking=False,
                dense_backend=backend,
            )
            for q in questions
        )
    )
    # n_picks is None, not len(ids): the service returns `_evidence` output only, so the
    # judge's own pick count is not observable from here.
    return {q["id"]: (ids, None) for q, (ids, _short, _err) in zip(questions, results)}


async def _run(questions, backend, judge_cls):
    """qid -> (submitted table_ids, n_picks). The production chain, one arm."""
    retriever = CandidateRetriever(
        load_judge_text=True,
        reranker="qwen3-0.6b",
        judge_top_n=20,
        dense_backend=backend,
        judge=None if judge_cls is None else judge_cls(thinking=False),
    )
    pools = await retriever.abuild_pools(questions)
    picks = await asyncio.gather(
        *(
            retriever.aselect(q, pool, thinking=False)
            for q, pool in zip(questions, pools)
        )
    )
    return {
        q["id"]: (_evidence(retriever, pool, sel["picks"]), len(sel["picks"]))
        for q, pool, sel in zip(questions, pools, picks)
    }


def _prf(submitted, gold):
    """Precision/recall of one question, on the tier `submitted` and `gold` are in."""
    if not submitted:
        return 0.0, 0.0
    hit = set(submitted) & set(gold)
    return len(hit) / len(submitted), len(hit) / len(gold)


def report(label, questions, runs, arms):
    n = len(questions)
    print(f"\n=== {label} full retrieval, submitted lists (n={n}) ===")
    head = (
        f"  {'arm':<18}{'empty':>6}{'picks':>6}{'|list|':>8}"
        f"{'T-P':>7}{'T-R':>7}{'T-F2':>7}{'D-P':>7}{'D-R':>7}{'D-F2':>7}"
        + "".join(f"{f'top-{c}':>7}" for c in CUTOFFS)
    )
    print(head)
    print("  " + "-" * (len(head) - 2))
    ranks = {}
    for name, _backend, _judge in arms:
        res = runs[name]
        empty = sum(1 for _ids, npk in res.values() if npk == 0)
        tp, tr, dp, dr, sizes, n_picks = [], [], [], [], [], []
        rank_of = {}
        for q in questions:
            ids, npk = res[q["id"]]
            gold = set(q["gold_keys"])
            p, r = _prf(ids, gold)
            tp.append(p)
            tr.append(r)
            p, r = _prf(dedupe_reports(ids), {k.rsplit("|", 1)[0] for k in gold})
            dp.append(p)
            dr.append(r)
            sizes.append(len(ids))
            if npk is not None:
                n_picks.append(npk)
            rank_of[q["id"]] = min(
                (i for i, k in enumerate(ids) if k in gold), default=None
            )
        ranks[name] = rank_of
        mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
        med = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
        cells = "".join(
            f"{sum(1 for v in rank_of.values() if v is not None and v < c):>7}"
            for c in CUTOFFS
        )
        print(
            f"  {name:<18}{empty:>6}{med(n_picks) if n_picks else '-':>6}{med(sizes):>8}"
            f"{mean(tp):>7.3f}{mean(tr):>7.3f}{f2_score(mean(tp), mean(tr)):>7.3f}"
            f"{mean(dp):>7.3f}{mean(dr):>7.3f}{f2_score(mean(dp), mean(dr)):>7.3f}{cells}"
        )
    a, b = ranks[arms[0][0]], ranks[arms[1][0]]
    moved = [q for q in a if a[q] != b[q]]
    better = sum(1 for q in moved if a[q] is None or (b[q] is not None and b[q] < a[q]))
    print(f"  ranks moved {len(moved)}/{n}: {better} better, {len(moved) - better} worse")
    print("  T = TABLES tier, D = DOCS tier, empty = questions the judge picked nothing for")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--arms", default="backend", choices=("backend", "control", "reasoning", "equiv")
    )
    args = ap.parse_args()
    arms = arms_for(args.arms)

    load_tables()  # warm the parse once; every retriever below reads its own copy
    u60 = load_unbiased60()
    g94 = load_gold94(exclude={q["id"] for q in u60})
    for label, questions in (("unbiased60", u60), ("gold94", g94)):
        runs = {
            name: asyncio.run(
                _run_service(questions, be)
                if name == SERVICE
                else _run(questions, be, judge)
            )
            for name, be, judge in arms
        }
        report(label, questions, runs, arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
