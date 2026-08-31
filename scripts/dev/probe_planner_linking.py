"""Score the LLM planner's cell choice against cell-level ground truth.

`probe_cell_ranking.py` measures the deterministic scorer, which only decides the
~15% of questions the deterministic gate claims. The other ~85% are decided by
`aplan_raw_search` + `aplan_raw_table_linker`, and that accuracy was never
measured. This replays exactly that path (same prompts, same `limit_per_slot=12`
as `aprepare_raw_table_linker`) and checks the chosen candidates against the
labeled cells in `data/eval/gold100_raw.jsonl`.

Differences from live, both stated rather than hidden:
  * no `retrieve` node, so `table_ids`/`shortlist` are empty. Candidates are
    scoped by ticker/year only - no retrieval ranking bonus, and no retrieval
    mistake either.
  * ratio questions take a different planner (`aplan_raw_ratio_linker` /
    ratio options), so they are counted separately, not scored here.

    PYTHONPATH=src .venv_bge/bin/python scripts/probe_planner_linking.py --unseen
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
from pathlib import Path
from typing import Any

from finance_qa.modules.solve.solvers import raw_table_linker as raw

GOLD100 = Path("data/eval/gold100_raw.jsonl")
TUNED_GOLD = ("data/eval/unbiased60_gold.jsonl", "data/eval/manual15_gold.jsonl")
TUNED_BAND = range(363, 441)
LIVE_LIMIT_PER_SLOT = 12  # aprepare_raw_table_linker uses this for non-ratio ops


def tuned_ids() -> set[int]:
    ids = set(TUNED_BAND)
    for path in TUNED_GOLD:
        if Path(path).exists():
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ids.add(int(json.loads(line)["id"]))
    return ids


def gt_keys(row: dict[str, Any]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for cell in row.get("gt_tables") or []:
        if isinstance(cell, dict) and cell.get("table_id"):
            out.add((str(cell["table_id"]), raw._norm(cell.get("row_label"))))
    return out


async def score_one(row: dict[str, Any], sem: asyncio.Semaphore) -> dict[str, Any]:
    qid, op = int(row["qid"]), str(row.get("op") or "?")
    out: dict[str, Any] = {"qid": qid, "op": op}
    request, reason = raw.build_request({
        "question": row["question"],
        "tickers": row.get("tickers") or ([row["ticker"]] if row.get("ticker") else []),
        "years": row.get("years") or [],
        "doc_type": row.get("doc_type"),
    })
    if request is None:
        return {**out, "arm": "declined", "reason": reason}
    if request.operation == "ratio":
        return {**out, "arm": "ratio_path"}

    candidates, _ = raw.build_candidates(request, limit_per_slot=LIVE_LIMIT_PER_SLOT)
    if not candidates:
        return {**out, "arm": "no_candidates"}
    wanted = gt_keys(row)
    out["gt_in_candidates"] = any(
        (c.table_id, raw._norm(c.row_label)) in wanted for c in candidates
    )

    deterministic = raw.deterministic_decision(request, candidates)
    if deterministic.supported:
        arm, decision, used_request, used_candidates = "gate", deterministic, request, candidates
    else:
        arm = "planner"
        async with sem:
            search_plan = await raw.aplan_raw_search(
                question=row["question"], request=request, table_ids=[], shortlist=[],
            )
            expanded_request = raw.request_with_search_plan(request, search_plan)
            expanded_candidates = (
                candidates
                if expanded_request == request
                else raw.build_candidates(
                    expanded_request, limit_per_slot=LIVE_LIMIT_PER_SLOT
                )[0]
            )
            used_request, used_candidates = request, candidates
            if raw.search_expansion_adds_slot_coverage(
                request, search_plan, candidates, expanded_candidates
            ):
                used_request, used_candidates = expanded_request, expanded_candidates
                out["search_expanded"] = True
                out["gt_in_candidates"] = any(
                    (c.table_id, raw._norm(c.row_label)) in wanted for c in used_candidates
                )
            decision = await raw.aplan_raw_table_linker(
                question=row["question"], request=used_request, candidates=used_candidates,
            )
            decision = raw.normalize_planner_decision(used_request, decision)

    out["arm"] = arm
    out["reason"] = decision.reason
    if not decision.supported:
        return {**out, "verdict": "abstained"}
    by_id = {c.id: c for c in used_candidates}
    chosen = [by_id[cid] for cid in decision.candidate_ids if cid in by_id]
    if not chosen:
        return {**out, "verdict": "empty"}
    keys = {(c.table_id, raw._norm(c.row_label)) for c in chosen}
    out["chosen"] = [f"{c.table_id} | {c.row_label[:50]} | {c.column}" for c in chosen]
    out["wanted"] = sorted(f"{t} | {r[:50]}" for t, r in wanted)
    if keys <= wanted:
        out["verdict"] = "right"
    elif keys & wanted:
        out["verdict"] = "partial"
    else:
        out["verdict"] = "wrong"
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseen", action="store_true")
    ap.add_argument("--op", action="append", default=[])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    skip = tuned_ids() if args.unseen else set()
    rows = [
        r
        for line in GOLD100.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for r in [json.loads(line)]
        if r.get("status") == "resolved" and r.get("gt_tables") and int(r["qid"]) not in skip
        and (not args.op or r.get("op") in args.op)
    ]

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(score_one(row, sem) for row in rows))

    arms = collections.Counter(r["arm"] for r in results)
    print(f"questions={len(rows)}  " + "  ".join(f"{k}={v}" for k, v in arms.most_common()))
    for arm in ("planner", "gate"):
        subset = [r for r in results if r["arm"] == arm]
        if not subset:
            continue
        verdicts = collections.Counter(r.get("verdict", "?") for r in subset)
        reachable = sum(1 for r in subset if r.get("gt_in_candidates"))
        right = verdicts["right"]
        print(
            f"\n{arm}: n={len(subset)}  gt reachable in candidates={reachable}/{len(subset)}"
            f"\n  right={right}  partial={verdicts['partial']}  wrong={verdicts['wrong']}"
            f"  abstained={verdicts['abstained']}  empty={verdicts['empty']}"
        )
        if reachable:
            print(f"  accuracy when the cell was reachable: {right}/{reachable}")
        by_op: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for r in subset:
            by_op[r["op"]][r.get("verdict", "?")] += 1
            by_op[r["op"]]["n"] += 1
        for op in sorted(by_op, key=lambda o: -by_op[o]["n"]):
            c = by_op[op]
            print(
                f"    {op:9s} n={c['n']:3d} right={c['right']:3d} partial={c['partial']:3d}"
                f" wrong={c['wrong']:3d} abstained={c['abstained']:3d}"
            )

    shown = 0
    for r in results:
        if r.get("verdict") in {"wrong", "partial"} and shown < args.show:
            shown += 1
            print(f"\nq{r['qid']} [{r['op']}] {r['verdict']}  reachable={r.get('gt_in_candidates')}")
            for line in r.get("chosen", []):
                print(f"   chose : {line}")
            for line in r.get("wanted", []):
                print(f"   wanted: {line}")
            print(f"   reason: {r.get('reason', '')[:200]}")

    if args.out:
        Path(args.out).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
