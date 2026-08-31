"""Reproduce the stratified 100-question gold-set sample and write a manifest.

This replaces hand-picking questions: the sample is drawn once, deterministically
(seed=0), from questions_enriched.jsonl, stratified by (op, bank/nonbank), and
the manifest records exactly how -- so anyone can re-derive the same 100 qids
from tables_metadata_v2.jsonl + questions_enriched.jsonl alone.

Strata:
  - op: classify_ops-style regex rules over the question text (ported below,
    same 8 patterns + "lookup" fallback), applied inline rather than importing
    scripts/classify_ops.py so this script has no dependency beyond the two
    metadata files.
  - bank/nonbank: the question's primary ticker's industry_segment in
    tables_metadata_v2.jsonl (== "bank" -> "bank", else "nonbank").

The 15 qids that already carry gt_tables in data/eval/evalset.json
(1,17,40,44,55,100,363,524,582,605,674,752,754,818,820 -- the acceptance-test
set for scripts/build_gold_candidates.py) are excluded from the sampling pool,
so the 100 are a genuinely new set, not an extension of the acceptance-test 15.

Allocation: proportional to stratum size, largest-remainder rounding to hit
exactly 100, ties broken by stratum key for determinism.

For each sampled question, resolved_report_count comes from
build_gold_candidates.build_candidates_for_question() -- the same resolver
used for the candidate shortlists, so the manifest and the candidates are
never out of sync with each other.

Usage:
  python scripts/build_gold100_manifest.py --out data/eval/gold100_manifest.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path

from build_gold_candidates import (
    META_PATH,
    QUESTIONS_PATH,
    build_candidates_for_question,
    build_report_index,
    load_questions_by_id,
)

SEED = 0
TARGET = 100

# --- op classification (ported from /tmp/gold100/step1_sample.py, itself a
# copy of scripts/classify_ops.py's rules) ----------------------------------
OP_RULES = [
    ("complex", re.compile(
        r"(năm mà|trong số các năm mà|"
        r"trong số các .+ (có|đạt).+ (lớn nhất|cao nhất|thấp nhất|nhỏ nhất)|"
        r"gấp bao nhiêu lần .+ trong năm đó|"
        r"trong năm đó|"
        r"trong nhóm .+ nào)",
        re.IGNORECASE,
    )),
    ("argmax", re.compile(
        r"(năm nào .+ (lớn nhất|cao nhất|nhỏ nhất|thấp nhất)|"
        r"(công ty|doanh nghiệp|ngân hàng) nào .+ (lớn nhất|cao nhất|nhỏ nhất|thấp nhất)|"
        r"(lớn nhất|cao nhất|nhỏ nhất|thấp nhất) (trong|ở) (các năm|năm nào|giai đoạn)|"
        r"đứng (đầu|thứ|cuối))",
        re.IGNORECASE,
    )),
    ("growth", re.compile(
        r"(tăng|giảm) (bao nhiêu (phần trăm|%)|so với)|"
        r"tăng trưởng|"
        r"thay đổi bao nhiêu (phần trăm|%)|"
        r"biến động bao nhiêu (phần trăm|%)",
        re.IGNORECASE,
    )),
    ("ratio", re.compile(
        r"tỷ (suất|trọng|lệ|số)|"
        r"biên lợi nhuận|"
        r"hệ số|"
        r"\bROE\b|\bROA\b|\bROIC\b|\bEPS\b|"
        r"chiếm bao nhiêu (phần trăm|%)|"
        r"trên tổng .+ là bao nhiêu (%|phần trăm)|"
        r"gấp bao nhiêu lần|"
        r"vòng quay",
        re.IGNORECASE,
    )),
    ("avg", re.compile(r"trung bình (cộng|của|hàng năm)|bình quân", re.IGNORECASE)),
    ("sum", re.compile(
        r"tổng .+ (trong (giai đoạn|các năm)|từ năm .+ đến năm)|"
        r"tổng cộng .+ (trong (giai đoạn|các năm)|từ năm .+ đến năm)|"
        r"cộng dồn",
        re.IGNORECASE,
    )),
    ("diff", re.compile(
        r"chênh lệch bao nhiêu|"
        r"nhiều hơn|ít hơn|kém|hơn|"
        r"khác biệt bao nhiêu",
        re.IGNORECASE,
    )),
    ("count", re.compile(
        r"có bao nhiêu (công ty|người|thành viên|đơn vị|khoản|dòng|loại|nhân viên)|"
        r"số lượng .+ là bao nhiêu",
        re.IGNORECASE,
    )),
]


def classify_op(question: str) -> str:
    for op, pat in OP_RULES:
        if pat.search(question):
            return op
    return "lookup"


ACCEPTANCE_TEST_QIDS = {1, 17, 40, 44, 55, 100, 363, 524, 582, 605, 674, 752, 754, 818, 820}


def build_ticker_segment(meta_path: Path) -> dict[str, str]:
    ticker_segment: dict[str, str] = {}
    with meta_path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            ticker_segment.setdefault(d["ticker"], d.get("industry_segment", "general"))
    return ticker_segment


def draw_sample(questions_path: Path, meta_path: Path) -> tuple[list[dict], dict]:
    """(sampled questions with _op/_bank tags, allocation-by-stratum dict)."""
    ticker_segment = build_ticker_segment(meta_path)

    with questions_path.open(encoding="utf-8") as f:
        all_questions = [json.loads(line) for line in f if line.strip()]

    pool = []
    for q in all_questions:
        if q["id"] in ACCEPTANCE_TEST_QIDS:
            continue
        tickers = q.get("tickers") or []
        if not tickers:
            continue
        seg = ticker_segment.get(tickers[0], "general")
        q["_op"] = classify_op(q["question"])
        q["_bank"] = "bank" if seg == "bank" else "nonbank"
        pool.append(q)

    strata = defaultdict(list)
    for q in pool:
        strata[(q["_op"], q["_bank"])].append(q)

    rng = random.Random(SEED)
    raw = {k: TARGET * len(v) / len(pool) for k, v in strata.items()}
    floor_alloc = {k: int(v) for k, v in raw.items()}
    remainder = TARGET - sum(floor_alloc.values())
    order = sorted(raw.keys(), key=lambda k: (-(raw[k] - floor_alloc[k]), k))
    for k in order[:remainder]:
        floor_alloc[k] += 1

    sample = []
    allocation = {}
    for k in sorted(floor_alloc, key=lambda k: -floor_alloc[k]):
        n = min(floor_alloc[k], len(strata[k]))
        chosen = rng.sample(strata[k], n)
        sample.extend(chosen)
        allocation[f"{k[0]}/{k[1]}"] = {"alloc": floor_alloc[k], "chosen": n, "pool": len(strata[k])}

    sample.sort(key=lambda q: q["id"])
    return sample, allocation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output manifest JSON path")
    args = ap.parse_args()

    sample, allocation = draw_sample(QUESTIONS_PATH, META_PATH)

    questions_by_id = load_questions_by_id(QUESTIONS_PATH)
    ticker_year_reports, report_tables, ticker_company = build_report_index(META_PATH)

    entries = []
    for q in sample:
        record = build_candidates_for_question(
            questions_by_id[q["id"]], ticker_year_reports, report_tables, ticker_company,
        )
        entries.append({
            "qid": q["id"],
            "op": q["_op"],
            "bank": q["_bank"],
            "tickers": record["tickers"],
            "years": record["years"],
            "doc_type": record["doc_type"],
            "resolved_report_count": record["resolved_report_count"],
            "scope_warning": record["scope_warning"],
        })

    manifest = {
        "seed": SEED,
        "target_sample_size": TARGET,
        "excluded_acceptance_test_qids": sorted(ACCEPTANCE_TEST_QIDS),
        "strata_definition": {
            "op": "classify_ops-style regex over question text; 8 rules "
                  "(complex, argmax, growth, ratio, avg, sum, diff, count) "
                  "then 'lookup' fallback -- see OP_RULES in this script",
            "bank": "primary ticker's industry_segment in tables_metadata_v2.jsonl "
                    "== 'bank' -> 'bank', else 'nonbank'",
        },
        "allocation_method": "proportional to stratum size, largest-remainder rounding to 100, "
                              "ties broken by stratum key",
        "allocation_by_stratum": allocation,
        "n_sampled": len(entries),
        "questions": entries,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = sorted(e["resolved_report_count"] for e in entries)
    n = len(counts)
    n_warn = sum(1 for e in entries if e["scope_warning"])
    print(f"wrote {len(entries)} question(s) -> {out_path}")
    print(f"resolved reports per question: min={counts[0]} median={counts[n // 2]} "
          f"max={counts[-1]} mean={sum(counts) / n:.1f}")
    print(f"scope warnings: {n_warn}")


if __name__ == "__main__":
    main()
