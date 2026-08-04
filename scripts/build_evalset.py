"""Build the V0 retrieval eval set from data/eval/manual_solutions/.

Ground truth is hand-transcribed from solutions.md + solutions_batch2.md (24
questions, L1-L6 x 2 batches) and validated against tables_metadata_v2.jsonl.
It is a literal, not a markdown parse: those files are prose written for humans
and any parser over them is more fragile than typing 24 rows.

Two tiers, because the batches recorded different things:
  - report-level GT: all 24 questions
  - table-level GT:  15 questions that recorded explicit `report_id|table_pos`
                     (batch 2 in full, plus #1 / #100 / #674 from batch 1)

GT is a list of **groups**. A group is a set of interchangeable answers, and
recall counts a group as hit if any member is retrieved. Two things need this:
  - OCR split a logical table in two (#100: BVH entity-info block, |15 or |16)
  - the corpus ships the same report twice under `_1` / `_2` (see DUP_BASES)

Report-level GT enumerates *every* report the question's (ticker, year, scope)
spans, not the minimal set a human would open. Several solutions note that a
year-Y report also carries year Y-1 as a comparison column, so 3 reports can
answer a 5-year question -- that is a solving shortcut, not a retrieval target.
Retrieval's job is to surface all of them; downstream picks.

Writes data/eval/evalset.json. Exits non-zero if any GT id is missing from the
corpus.
"""

from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from finance_qa.paths import EVALSET_PATH, QUESTION_METADATA_PATH, TABLE_METADATA_PATH


METADATA_PATH = TABLE_METADATA_PATH
QUESTIONS_PATH = QUESTION_METADATA_PATH
OUT_PATH = EVALSET_PATH

# Reports the corpus ships twice: `<base>_1` and `<base>_2` are the same
# document OCR'd twice -- identical table count, differing in 1-2 tables of OCR
# noise (NAB 2023: 2/111, OCB 2022 consolidated: 1/104, MBB 2022 separate:
# 2/98). Either id is a correct answer, so GT expands to both.
#
# Deliberately NOT listed: `_1`/`_2` pairs with *different* table counts, which
# are a partial plus a full scan and are not interchangeable --
# HDB 2023 consolidated (51/105), HDB 2023 separate (48/106),
# MPC 2019 separate (44/18), POW 2025 consolidated (57/10).
DUP_BASES = {
    "HDB_financial_statements_2022_separate",
    "MBB_financial_statements_2022_separate",
    "NAB_financial_statements_2022_consolidated",
    "NAB_financial_statements_2023_consolidated",
    "NVB_financial_statements_2020_consolidated",
    "OCB_financial_statements_2022_consolidated",
    "OCB_financial_statements_2022_separate",
    "VPB_financial_statements_2022_separate",
}

# fmt: off
# qid -> (level, source, tables | None, extra_alt_positions)
# tables=None => report-level only; its reports are listed in REPORTS_ONLY.
# extra_alt_positions maps a GT key to further positions that answer it equally.
EVAL: dict[int, tuple[str, str, list[str] | None, dict[str, list[int]]]] = {
    # --- batch 1 (solutions.md): only L1.1 / L1.2 / L2.1 recorded a table_pos ---
    1:   ("L1.1", "solutions.md", ["VJC_financial_statements_2018_separate|50"], {}),
    100: ("L1.2", "solutions.md", ["BVH_financial_statements_2018_consolidated|16"],
          {"BVH_financial_statements_2018_consolidated|16": [15]}),
    674: ("L2.1", "solutions.md", ["HBC_financial_statements_2016_consolidated|8"], {}),
    656: ("L2.2", "solutions.md", None, {}),
    612: ("L3.1", "solutions.md", None, {}),
    904: ("L3.2", "solutions.md", None, {}),
    793: ("L4.1", "solutions.md", None, {}),
    751: ("L4.2", "solutions.md", None, {}),
    937: ("L5.1", "solutions.md", None, {}),
    924: ("L5.2", "solutions.md", None, {}),
    440: ("L6.1", "solutions.md", None, {}),
    501: ("L6.2", "solutions.md", None, {}),

    # --- batch 2 (solutions_batch2.md): every question recorded a table_pos ---
    44:  ("L1.1", "solutions_batch2.md", ["STB_financial_statements_2016_consolidated|4"], {}),
    17:  ("L1.2", "solutions_batch2.md", ["SHB_financial_statements_2018_consolidated|5"], {}),
    40:  ("L2.1", "solutions_batch2.md", ["VIB_financial_statements_2020_consolidated|10"], {}),
    55:  ("L2.2", "solutions_batch2.md", ["FTS_financial_statements_2020|11"], {}),
    605: ("L3.1", "solutions_batch2.md", ["NLG_financial_statements_2024_consolidated|7"], {}),
    582: ("L3.2", "solutions_batch2.md", ["MCH_financial_statements_2021_consolidated|4",
                                          "MCH_financial_statements_2023_consolidated|4"], {}),
    752: ("L4.1", "solutions_batch2.md", ["ABB_financial_statements_2022_consolidated|8",
                                          "MBB_financial_statements_2022_consolidated|8"], {}),
    754: ("L4.2", "solutions_batch2.md", ["HDB_financial_statements_2021_separate|33",
                                          "ABB_financial_statements_2021_separate|32"], {}),
    818: ("L5.1", "solutions_batch2.md", ["FTS_financial_statements_2018|22",
                                          "FTS_financial_statements_2020|28",
                                          "FTS_financial_statements_2021|27",
                                          "FTS_financial_statements_2023|26",
                                          "FTS_financial_statements_2024|22"], {}),
    820: ("L5.2", "solutions_batch2.md", ["SNZ_financial_statements_2018_separate|7",
                                          "SNZ_financial_statements_2019_separate|10",
                                          "SNZ_financial_statements_2020_separate|9",
                                          "SNZ_financial_statements_2021_separate|7",
                                          "SNZ_financial_statements_2022_separate|8"], {}),
    # #363 and #524 abbreviate report_ids in the solution file ("KBC_2016|6",
    # "OCB_2022_1|30"); expanded here to real corpus ids.
    363: ("L6.1", "solutions_batch2.md", ["KBC_financial_statements_2016_consolidated|6",
                                          "KBC_financial_statements_2016_consolidated|7",
                                          "KBC_financial_statements_2018_consolidated|6",
                                          "KBC_financial_statements_2018_consolidated|7",
                                          "KBC_financial_statements_2020_consolidated|7",
                                          "KBC_financial_statements_2020_consolidated|8",
                                          "KBC_financial_statements_2020_consolidated|9"], {}),
    524: ("L6.2", "solutions_batch2.md", ["OCB_financial_statements_2017_consolidated|25",
                                          "OCB_financial_statements_2018_consolidated|21",
                                          "OCB_financial_statements_2021_consolidated|31",
                                          "OCB_financial_statements_2022_consolidated_1|30",
                                          "OCB_financial_statements_2022_consolidated_1|68"], {}),
}

# Report-level GT for the batch-1 questions whose solutions describe tables in
# prose only. Batch-2 report GT is derived from its table GT.
REPORTS_ONLY: dict[int, list[str]] = {
    656: ["FOX_financial_statements_2024_consolidated"],
    612: ["NKG_financial_statements_2020_separate",
          "NKG_financial_statements_2021_separate"],
    904: ["HDG_financial_statements_2020_consolidated",
          "HDG_financial_statements_2023_consolidated",
          "HDG_financial_statements_2024_consolidated"],
    793: ["GEE_financial_statements_2025_consolidated",
          "GEX_financial_statements_2025_consolidated"],
    751: ["OCB_financial_statements_2023_consolidated",
          "NAB_financial_statements_2023_consolidated_1"],
    937: ["CTG_financial_statements_2017_consolidated",
          "CTG_financial_statements_2018_consolidated",
          "CTG_financial_statements_2019_consolidated",
          "CTG_financial_statements_2020_consolidated"],
    924: ["DXG_financial_statements_2021_separate",
          "DXG_financial_statements_2022_separate",
          "DXG_financial_statements_2023_separate",
          "DXG_financial_statements_2024_separate",
          "DXG_financial_statements_2025_separate"],
    440: ["DIG_financial_statements_2021_consolidated",
          "DIG_financial_statements_2022_consolidated",
          "DIG_financial_statements_2023_consolidated",
          "DIG_financial_statements_2024_consolidated"],
    501: ["QNS_financial_statements_2015_separate",
          "QNS_financial_statements_2020_separate",
          "QNS_financial_statements_2021_separate",
          "QNS_financial_statements_2023_separate"],
}
# fmt: on


def dup_twins(report_id: str) -> list[str]:
    """Interchangeable ids for a report: itself, plus its OCR twin if it has one."""
    if report_id[-2:] in ("_1", "_2") and report_id[:-2] in DUP_BASES:
        base = report_id[:-2]
        return [f"{base}_1", f"{base}_2"]
    return [report_id]


def load_corpus() -> tuple[set[str], set[str]]:
    """Return (all report_ids, all "report_id|table_pos" keys)."""
    reports: set[str] = set()
    pairs: set[str] = set()
    with METADATA_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            reports.add(rec["report_id"])
            pairs.add(f"{rec['report_id']}|{rec['table_pos']}")
    return reports, pairs


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    reports, pairs = load_corpus()
    questions = {}
    with QUESTIONS_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            questions[rec["id"]] = rec

    problems: list[str] = []
    entries = []

    for qid in sorted(EVAL):
        level, source, tables, alt_positions = EVAL[qid]
        q = questions.get(qid)
        if q is None:
            problems.append(f"#{qid}: not in questions_enriched.jsonl")
            continue

        if tables is None:
            report_seeds = REPORTS_ONLY[qid]
            table_groups = None
        else:
            report_seeds = list(dict.fromkeys(t.rsplit("|", 1)[0] for t in tables))
            table_groups = []
            for key in tables:
                rid, pos = key.rsplit("|", 1)
                positions = [int(pos)] + alt_positions.get(key, [])
                group = [f"{twin}|{p}" for p in positions for twin in dup_twins(rid)]
                table_groups.append(list(dict.fromkeys(group)))

        report_groups = [dup_twins(rid) for rid in report_seeds]

        for group in report_groups:
            for rid in group:
                if rid not in reports:
                    problems.append(f"#{qid}: report_id not in corpus: {rid}")
        for group in table_groups or []:
            for key in group:
                if key not in pairs:
                    problems.append(f"#{qid}: table pair not in corpus: {key}")

        entries.append(
            {
                "qid": qid,
                "level": level,
                "source": source,
                "question": q["question"],
                "tickers": q.get("tickers", []),
                "years": q.get("years", []),
                "doc_type": q.get("doc_type", "unknown"),
                "gt_reports": report_groups,
                "gt_tables": table_groups,
            }
        )

    if problems:
        print("GT validation FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    table_tier = [e for e in entries if e["gt_tables"] is not None]
    OUT_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"{len(entries)} questions, all GT ids validated against the corpus.")
    print(
        f"  report tier: {len(entries)} questions, "
        f"{sum(len(e['gt_reports']) for e in entries)} report groups"
    )
    print(
        f"  table tier:  {len(table_tier)} questions, "
        f"{sum(len(e['gt_tables']) for e in table_tier)} table groups"
    )
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
