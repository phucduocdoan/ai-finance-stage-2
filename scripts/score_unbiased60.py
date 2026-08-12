"""Score every submission artifact against the hand-labeled gold sets.

Step 0 of the codegen rewrite: the existing 20-item extended_gold sits entirely
inside ids 363-440 — the band we tuned — so it ranks v5 above Flow A while the
leaderboard says the opposite. This scores the seeded, untuned samples instead:
the 59-question unbiased set plus the 15 manually solved questions (disjoint ids).

    PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py
    PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py --tol 0.001

    # a run_graph.py JSONL scored next to the packaged submissions
    PYTHONPATH=src .venv_bge/bin/python scripts/score_unbiased60.py \
        --run solve=artifacts/runs/solve_gold74.jsonl --right solve
"""

from __future__ import annotations

import argparse
import glob
import json
import os

# Both sets carry `gold_answer` + `confidence`; ids do not overlap.
GOLD_FILES = ("data/eval/unbiased60_gold.jsonl", "data/eval/manual15_gold.jsonl")
GOLD = GOLD_FILES[0]
MANIFEST = "data/eval/unbiased60_manifest.json"


def load_gold(min_confidence: str) -> dict[int, float]:
    order = {"high": 3, "medium": 2, "low": 1, "unresolvable": 0}
    floor = order[min_confidence]
    gold: dict[int, float] = {}
    for path in GOLD_FILES:
        if not os.path.exists(path):
            continue
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("gold_answer") is None:
                continue
            if order.get(r.get("confidence") or "low", 1) < floor:
                continue
            gold[int(r["id"])] = float(r["gold_answer"])
    return gold


def load_run(path: str) -> dict[int, float | None]:
    """Answers from a run_graph.py JSONL (one record per question)."""
    out: dict[int, float | None] = {}
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        try:
            out[int(r["id"])] = float(r["item"]["answer"])
        except (KeyError, TypeError, ValueError):
            out[int(r["id"])] = None
    return out


def load_submission(path: str) -> dict[int, float | None]:
    data = json.load(open(path))
    items = data if isinstance(data, list) else (data.get("data") or data.get("results") or [])
    out: dict[int, float | None] = {}
    for r in items:
        try:
            out[int(r["id"])] = float(r["answer"])
        except (KeyError, TypeError, ValueError):
            out[int(r["id"])] = None
    return out


def hit(pred: float | None, gold: float, tol: float) -> bool:
    if pred is None:
        return False
    if gold == 0.0:
        return abs(pred) <= tol
    return abs(pred - gold) <= tol * abs(gold)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=0.01, help="relative tolerance")
    ap.add_argument("--min-confidence", default="medium", choices=["high", "medium", "low"])
    ap.add_argument(
        "--run", action="append", default=[], metavar="NAME=PATH",
        help="score a run_graph.py JSONL alongside the packaged submissions (repeatable)",
    )
    ap.add_argument("--left", default="submission_v2", help="left column of the detail table")
    ap.add_argument("--right", default="submission_graph_v5", help="right column of the detail table")
    args = ap.parse_args()

    if not os.path.exists(GOLD):
        raise SystemExit(f"{GOLD} chưa tồn tại — sub-agent chấm tay chưa xong.")

    gold = load_gold(args.min_confidence)
    print(f"gold: {len(gold)} câu (confidence >= {args.min_confidence}), tol = {args.tol:g}\n")

    paths = sorted(glob.glob("output/submission*/submission.json"))
    rows = []
    preds: dict[str, dict[int, float | None]] = {}
    sources = [(p.split("/")[1], load_submission(p)) for p in paths]
    for spec in args.run:
        name, _, path = spec.partition("=")
        if not path:
            name, path = os.path.basename(name).removesuffix(".jsonl"), name
        sources.append((name, load_run(path)))

    for name, pred in sources:
        preds[name] = pred
        n = sum(1 for qid, g in gold.items() if hit(pred.get(qid), g, args.tol))
        zeros = sum(1 for qid in gold if pred.get(qid) == 0.0)
        missing = sum(1 for qid in gold if qid not in pred)
        rows.append((name, n, zeros, missing))

    rows.sort(key=lambda r: -r[1])
    width = max(len(r[0]) for r in rows)
    print(f"{'artifact':<{width}}  đúng  tỉ lệ   zeros  thiếu")
    for name, n, zeros, missing in rows:
        print(f"{name:<{width}}  {n:>4}  {n / len(gold):>5.1%}  {zeros:>5}  {missing:>5}")

    # Per-question detail for the two artifacts we most need to compare.
    a, b = args.left, args.right
    if a in preds and b in preds:
        print(f"\nChi tiết {a} vs {b}:")
        print(f"{'id':>5}  {'gold':>16}  {a[:16]:>16}  {b[:16]:>16}  kết quả")
        counts: dict[str, int] = {}
        for qid in sorted(gold):
            g = gold[qid]
            pa, pb = preds[a].get(qid), preds[b].get(qid)
            ha, hb = hit(pa, g, args.tol), hit(pb, g, args.tol)
            tag = {(True, True): "cả hai đúng", (True, False): f"chỉ {a}",
                   (False, True): f"chỉ {b}", (False, False): "cả hai SAI"}[(ha, hb)]
            counts[tag] = counts.get(tag, 0) + 1
            fa = "None" if pa is None else f"{pa:.6g}"
            fb = "None" if pb is None else f"{pb:.6g}"
            print(f"{qid:>5}  {g:>16.6g}  {fa:>16}  {fb:>16}  {tag}")
        print("  ".join(f"{tag}={n}" for tag, n in sorted(counts.items())))

    print("\nĐộ nhạy theo tolerance:")
    for tol in (1e-9, 1e-6, 1e-4, 1e-2, 5e-2, 0.2):
        line = [f"  tol {tol:<7g}"]
        for name, *_ in rows[:6]:
            n = sum(1 for qid, g in gold.items() if hit(preds[name].get(qid), g, tol))
            line.append(f"{name.replace('submission', 's')}={n}")
        print("  ".join(line))


if __name__ == "__main__":
    main()
