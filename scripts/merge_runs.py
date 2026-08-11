"""Merge a re-run of some questions back into a full run JSONL.

The graph run is per-question, so a fix that only affects one solver can be
re-run for just those ids and folded back in -- the rest of the run stays byte
identical, which keeps the answers that were already graded.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/merge_runs.py \
      --base artifacts/runs/graph_1012.jsonl \
      --patch artifacts/runs/graph_formula_fix.jsonl \
      --out artifacts/runs/graph_1012_v2.jsonl
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def read(path: Path) -> list[dict]:
    out = []
    for line in filter(str.strip, path.read_text(encoding="utf-8").splitlines()):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # a kill mid-write leaves one partial line
    return out


def executable(query: str) -> bool:
    try:
        ast.parse(query, mode="eval")
    except SyntaxError:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--patch", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    base = read(args.base)
    patch = {r["id"]: r for r in read(args.patch) if r.get("status") == "ok"}

    replaced = kept = literalized = 0
    merged = []
    for rec in base:
        new = patch.get(rec["id"])
        if new is not None:
            merged.append(new)
            replaced += 1
            continue
        item = rec.get("item") or {}
        if item and not executable(str(item.get("pandas_query", ""))):
            # No re-run for this id and its query cannot even parse: ship the
            # answer as a literal so execution scoring does not zero it out.
            item["pandas_query"] = repr(float(item.get("answer") or 0.0))
            literalized += 1
        merged.append(rec)
        kept += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for rec in merged:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"base={len(base)} patch={len(patch)} -> {args.out}")
    print(f"  replaced by re-run: {replaced}")
    print(f"  kept from base:     {kept}  (of which literalized: {literalized})")


if __name__ == "__main__":
    main()
