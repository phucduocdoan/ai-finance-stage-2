"""Does the dense channel want the same text as BM25?

`header_flat` is load-bearing for BM25 -- dropping it from the index cost intra-report top5
72.2% -> 63.9% (document_text.py docstring, diag_repr.py). This asks the same question of the
dense channel, which cannot answer it the same way: an unmatched token is free for BM25
(no query term, no contribution) but not for bge-m3, whose CLS vector moves for every token
it reads. If the two channels disagree, the one shared `doc_text` column is a compromise
rather than a design.

Two arms, identical except for which dense index they load. BM25 reads the v2 `doc_text`
(header_flat included) in BOTH arms, so any delta is attributable to the dense channel:

  WITH    dense index built over doc_text v2                (tables_dense_v2rebuilt.npy)
  WITHOUT dense index built over doc_text minus header_flat (tables_dense_noheader.npy)

Both eval sets, because +3/60 on one set is not a result:
  unbiased60  data/eval/unbiased60_gold.jsonl  `evidence_table_id`
  gold94      data/eval/gold100_raw.jsonl      `gt_tables[].table_id`, minus the 4 questions
              that overlap unbiased60, so the second set is independent of the first.

Run:
  PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_dense_text.py
"""

import _bootstrap  # noqa: F401

import json
from pathlib import Path

from finance_qa.core.paths import EVAL_DIR, INDEXES_DIR, METADATA_DIR
from finance_qa.modules.rag.retrievers.filters import load_tables

from gate_header_v3 import DOC_TEXT_V2, build_dense_retriever, parse_gold_keys

DENSE_WITH = INDEXES_DIR / "tables_dense_v2rebuilt.npy"
DENSE_WITHOUT = INDEXES_DIR / "tables_dense_noheader.npy"

# The ablation, ordered by how much boilerplate each variant drops. Per-segment uniqueness
# over all 146,246 tables (non-empty / distinct / intra-report duplicate / share of chars):
#   statement_label   13.2%      8  92.7%   1.0%   <- 8 distinct values in the whole corpus
#   note_title        71.1%  5,399  58.0%   6.2%
#   section_title     57.5%  5,839  89.1%  10.9%
#   first_col_labels  97.4% 98,480   3.6%  67.4%   <- the only genuinely unique segment
#   header_flat      100.0% 30,192  52.6%  14.5%
# BM25 can carry the duplicated segments for free -- IDF discounts them. bge-m3 cannot:
# every token it reads moves the CLS vector whether or not a query could ever match it.
# `judge_text` is already exactly "doc_text minus section_title minus header_flat".
VARIANTS = [
    ("doc_text (baseline)", DENSE_WITH),
    ("- header_flat", DENSE_WITHOUT),
    ("- header - section (= judge_text)", INDEXES_DIR / "tables_dense_judgetext.npy"),
    ("note_title + labels", INDEXES_DIR / "tables_dense_nt_labels.npy"),
    ("labels only", INDEXES_DIR / "tables_dense_labelsonly.npy"),
]

QUESTIONS_PATH = METADATA_DIR / "questions_enriched.jsonl"
UNBIASED60 = EVAL_DIR / "unbiased60_gold.jsonl"
GOLD100 = EVAL_DIR / "gold100_raw.jsonl"

CUTOFFS = (1, 3, 5, 10, 20)


def _enriched(ids: set) -> dict:
    out = {}
    with QUESTIONS_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            if rec["id"] in ids:
                out[rec["id"]] = rec
    return out


def load_unbiased60() -> list[dict]:
    gold = [json.loads(line) for line in UNBIASED60.open(encoding="utf-8")]
    gold = [g for g in gold if g.get("evidence_table_id")]
    enriched = _enriched({g["id"] for g in gold})
    out = []
    for g in gold:
        q = dict(enriched[g["id"]])
        q["gold_keys"] = parse_gold_keys(g["evidence_table_id"])
        out.append(q)
    return out


def load_gold94(exclude: set) -> list[dict]:
    rows = [json.loads(line) for line in GOLD100.open(encoding="utf-8")]
    rows = [r for r in rows if r.get("gt_tables") and r["qid"] not in exclude]
    enriched = _enriched({r["qid"] for r in rows})
    out = []
    for r in rows:
        if r["qid"] not in enriched:  # not every gold100 qid is in questions_enriched
            continue
        q = dict(enriched[r["qid"]])
        q["gold_keys"] = sorted({t["table_id"] for t in r["gt_tables"] if t.get("table_id")})
        out.append(q)
    return out


def gold_ranks(questions: list[dict], index: Path, tables: list[dict]) -> dict:
    """Best rank of any of a question's gold tables in `pool.ranked`, None if absent.

    Pool membership is reported separately from the cutoffs because it is the hard ceiling:
    the production judge reads the whole pool (`judge_top_n` is off by default), so a gold
    table that misses the pool is unreachable no matter how good the ordering is.
    """
    retriever = build_dense_retriever(
        parquet_path=DOC_TEXT_V2, index_path=index, tables=tables
    )
    out = {}
    for q, pool in zip(questions, retriever.build_pools(questions)):
        gold = set(q["gold_keys"])
        rank = min((i for i, key in enumerate(pool.ranked) if key in gold), default=None)
        out[q["id"]] = (rank, bool(gold & set(pool.keys)), len(pool.ranked))
    return out


def report(name: str, with_ranks: dict, without_ranks: dict) -> None:
    n = len(with_ranks)
    print(f"\n=== {name} (n={n}) ===")
    for label, idx in (("shortlist ", 1), ("in pool   ", None)):
        if idx == 1:
            a = sum(1 for v in with_ranks.values() if v[1])
            b = sum(1 for v in without_ranks.values() if v[1])
        else:
            a = sum(1 for v in with_ranks.values() if v[0] is not None)
            b = sum(1 for v in without_ranks.values() if v[0] is not None)
        print(f"  {label}  with header_flat {a:>3}/{n}  without {b:>3}/{n}  delta {b - a:+d}")
    for cut in CUTOFFS:
        a = sum(1 for v in with_ranks.values() if v[0] is not None and v[0] < cut)
        b = sum(1 for v in without_ranks.values() if v[0] is not None and v[0] < cut)
        print(
            f"  top-{cut:<2}      with header_flat {a:>3}/{n}  without {b:>3}/{n}  "
            f"delta {b - a:+d}"
        )
    moved = [
        (with_ranks[q][0], without_ranks[q][0])
        for q in with_ranks
        if with_ranks[q][0] != without_ranks[q][0]
    ]
    better = sum(1 for a, b in moved if a is None or (b is not None and b < a))
    print(f"  ranks moved {len(moved)}/{n}: {better} better, {len(moved) - better} worse")


def ablation(questions: list[dict], label: str, tables: list[dict]) -> None:
    n = len(questions)
    print(f"\n=== {label} (n={n}) ===")
    head = f"{'dense_text':<34}{'pool':>7}" + "".join(f"{f'top-{c}':>8}" for c in CUTOFFS)
    print(head)
    print("-" * len(head))
    for name, index in VARIANTS:
        ranks = gold_ranks(questions, index, tables)
        pool = sum(1 for v in ranks.values() if v[0] is not None)
        cells = "".join(
            f"{sum(1 for v in ranks.values() if v[0] is not None and v[0] < c):>8}"
            for c in CUTOFFS
        )
        print(f"{name:<34}{pool:>7}{cells}")


def main() -> int:
    tables = load_tables()
    u60 = load_unbiased60()
    g94 = load_gold94(exclude={q["id"] for q in u60})
    print(f"unbiased60: {len(u60)} questions | gold94: {len(g94)} questions (disjoint)")

    for name, questions in (("unbiased60", u60), ("gold94", g94)):
        ablation(questions, name, tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
