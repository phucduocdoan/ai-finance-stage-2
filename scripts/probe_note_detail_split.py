"""Split note-detail failures into retrieval-miss vs accessor-miss.

The gold-20 set is ALL main-statement (mã-số BS/IS/CF) — it does not exercise the
note-detail class at all. The only questions with ground-truth cell locations are the
24 in data/eval/evalset.json (15 carry gt_tables), and the v9g pilot run scored exactly
those 15 end-to-end. So this is the measurable universe for the note-detail question.

For each pilot question we join three read-only sources on qid:
  - evalset.json          → gt_tables (the correct table(s) holding the answer cell)
  - tables_metadata_v2    → statement_type of each gt table (note vs main-statement)
  - pilot v9g artifact    → table_ids actually retrieved, and whether the answer was correct

Decomposition of the note-detail class:
  correct                         → resolved end-to-end
  wrong  &  gt NOT all in pool    → RETRIEVAL-miss  (right table never reached the model)
  wrong  &  gt all in pool        → ACCESSOR-miss   (table present, wrong/no cell read)
For single_cell note lookups the reasoning step is trivial, so "wrong despite retrieval
hit" is an accessor failure, not a reasoning one.

Run:
    PYTHONPATH=src python3 scripts/probe_note_detail_split.py
"""

from __future__ import annotations

import json

EVALSET = "data/eval/evalset.json"
META = "data/metadata/tables_metadata_v2.jsonl"
PILOT = "artifacts/eval/pilot_15_v9g_eval.jsonl"

MAIN_STMT = {"balance_sheet", "income_statement", "cash_flow"}


def load_stmt_types() -> dict[str, str]:
    st: dict[str, str] = {}
    with open(META, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            st[f"{r['report_id']}|{r['table_pos']}"] = r.get("statement_type", "?")
    return st


def main() -> None:
    stmt = load_stmt_types()
    evalset = {q["qid"]: q for q in json.load(open(EVALSET, encoding="utf-8"))}
    pilot = {r["qid"]: r for r in (json.loads(l) for l in open(PILOT, encoding="utf-8"))}

    rows = []
    for qid, pr in pilot.items():
        ev = evalset.get(qid, {})
        gt = [t for grp in (ev.get("gt_tables") or []) for t in grp]
        if not gt:
            continue
        gt_types = {stmt.get(t, "?") for t in gt}
        is_note = not (gt_types & MAIN_STMT)  # note-detail iff NO gt table is a main statement

        retrieved = set(pr.get("table_ids") or [])
        gt_in_pool = [t for t in gt if t in retrieved]
        all_in_pool = len(gt_in_pool) == len(gt)
        correct = bool(pr.get("correct"))

        if correct:
            verdict = "OK"
        elif not all_in_pool:
            verdict = "RETRIEVAL-miss"
        else:
            verdict = "ACCESSOR-miss"

        rows.append({
            "qid": qid, "level": pr.get("level"), "note": is_note,
            "gt_n": len(gt), "in_pool": len(gt_in_pool),
            "correct": correct, "verdict": verdict,
            "types": ",".join(sorted(gt_types)),
        })

    # ---- per-question detail ----
    print(f"{'qid':>4} {'level':>5} {'class':>5} {'gt':>5} {'pool':>5} {'correct':>7}  {'verdict':<14} gt_types")
    print("-" * 78)
    for r in sorted(rows, key=lambda x: (not x["note"], x["qid"])):
        cls = "NOTE" if r["note"] else "main"
        print(f"{r['qid']:>4} {r['level']:>5} {cls:>5} {r['gt_n']:>5} "
              f"{r['in_pool']:>5} {str(r['correct']):>7}  {r['verdict']:<14} {r['types']}")

    # ---- note-detail split ----
    note = [r for r in rows if r["note"]]
    main = [r for r in rows if not r["note"]]

    def tally(group):
        from collections import Counter
        return Counter(r["verdict"] for r in group)

    print("\n" + "=" * 60)
    print(f"NOTE-DETAIL class  (n={len(note)}):")
    for v, c in sorted(tally(note).items()):
        print(f"    {v:<16} {c}/{len(note)}")
    print(f"MAIN-STATEMENT class  (n={len(main)}):")
    for v, c in sorted(tally(main).items()):
        print(f"    {v:<16} {c}/{len(main)}")
    print("=" * 60)
    print(f"scope: {len(rows)}/15 gt-labeled pilot questions "
          f"(evalset.json ∩ v9g). Small n — directional, not a leaderboard.")


if __name__ == "__main__":
    main()
