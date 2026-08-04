"""Package a pipeline run into the leaderboard submission ZIP.

`submission_rule.txt` requires:
  - one `submission.json`: an array of
    {id, question, answer(float), relevant_docs, relevant_tables,
     evidence[{variable, csv_path}], pandas_query}
  - a `data/` dir holding every CSV a `csv_path` references
  - `submission.json` and `data/` at the ZIP top level; exactly one `.json`
  - every `csv_path` (incl. in evidence) relative, starting with `data/`

Two rules drive the failure handling:
  - "thiếu câu -> cả bài không được đánh giá": every id in
    questions_enriched.jsonl MUST appear, so a question whose pipeline record
    failed still emits a best-effort item (answer 0.0, retrieval tables kept so
    the retrieval score still counts) instead of being dropped.
  - "sai định dạng -> câu đó không hợp lệ": a present-but-empty item costs only
    that question, never the whole submission.

The item shape and the CSV name/source mapping are the pipeline's own
(`pipeline.run.submission_item`, `execution.query.submission_csv_name`/
`source_csv`) -- nothing is reimplemented here, only assembled and zipped.

Run:
  PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py \
      --run artifacts/runs/pipeline_XXXX.jsonl --out output/submission

  # test on a partial run (skip the all-1012 completeness gate):
  ... --run artifacts/runs/pilot_24.jsonl --only-run-ids
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

import _bootstrap  # noqa: F401

from finance_qa.paths import QUESTION_METADATA_PATH
from finance_qa.execution.query import source_csv, submission_csv_name


def load_questions() -> dict[int, dict]:
    with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
        return {int(r["id"]): r for r in map(json.loads, filter(str.strip, fh))}


def load_last_records(path: Path) -> dict[int, dict]:
    """id -> its last record (last-wins, same as pipeline.run)."""
    last: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            row = json.loads(line)
            last[int(row["id"])] = row
    return last


def _coerce_float(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def build_item(qrow: dict, record: dict | None) -> dict:
    """Prefer the pipeline's own item; otherwise a best-effort fallback.

    A failed record still carries the retrieval `table_ids`, so relevant
    docs/tables are kept (retrieval is scored on its own) with a zero answer.
    """
    if record and isinstance(record.get("item"), dict):
        item = dict(record["item"])
        item["answer"] = _coerce_float(item.get("answer"))
        return item

    table_ids = list((record or {}).get("table_ids") or [])
    docs: dict[str, None] = {}
    for tid in table_ids:
        docs.setdefault(tid.rsplit("|", 1)[0], None)
    evidence, query = [], ""
    if table_ids:
        evidence = [{"variable": "df1", "csv_path": f"data/{submission_csv_name(table_ids[0])}"}]
        query = "df1"  # non-empty + references df1; audit-only, answer is graded
    return {
        "id": int(qrow["id"]),
        "question": qrow["question"],
        "answer": 0.0,
        "relevant_docs": list(docs),
        "relevant_tables": table_ids,
        "evidence": evidence,
        "pandas_query": query,
    }


# ------------------------------------------------------------------ validation

def validate_format(items: list[dict], expected_ids: set[int] | None) -> list[str]:
    """Leaderboard-format checks over the whole array. [] means clean.

    Stricter executable consistency (does the query recompute the answer) is the
    pipeline's `validate` per item at run time; here we only guarantee the array
    is well-formed and complete, which is what gets a submission graded at all.
    """
    errs: list[str] = []
    seen: set[int] = set()
    for it in items:
        i = it.get("id")
        if not isinstance(i, int):
            errs.append(f"id không phải int: {i!r}")
            continue
        if i in seen:
            errs.append(f"id trùng: {i}")
        seen.add(i)
        if not isinstance(it.get("question"), str) or not it["question"].strip():
            errs.append(f"#{i}: question rỗng")
        if not isinstance(it.get("answer"), float):
            errs.append(f"#{i}: answer không phải float: {it.get('answer')!r}")
        for ev in it.get("evidence") or []:
            path = ev.get("csv_path", "")
            if not str(path).startswith("data/"):
                errs.append(f"#{i}: csv_path phải bắt đầu 'data/': {path!r}")
            if not str(ev.get("variable", "")).isidentifier():
                errs.append(f"#{i}: variable không hợp lệ: {ev.get('variable')!r}")
    if expected_ids is not None:
        missing = sorted(expected_ids - seen)
        if missing:
            errs.append(f"THIẾU {len(missing)} câu (bài sẽ bị loại): {missing[:10]}...")
    return errs


# --------------------------------------------------------------------- packaging

def stage(items: list[dict], out_dir: Path) -> tuple[int, list[str]]:
    """Write submission.json + copy every referenced CSV into out_dir/data/.

    Returns (n_csv_copied, warnings). A table whose source CSV is missing is
    dropped from its item (and evidence) so the ZIP never references a file it
    does not ship -- that would fail the "thiếu file" rule for the whole bài.
    """
    data_dir = out_dir / "data"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    data_dir.mkdir(parents=True)

    warnings: list[str] = []
    copied: set[str] = set()
    for it in items:
        kept_tables = []
        for tid in it.get("relevant_tables") or []:
            src = source_csv(tid)
            if not src.exists():
                warnings.append(f"#{it['id']}: bỏ table thiếu CSV {tid}")
                continue
            name = submission_csv_name(tid)
            if name not in copied:
                shutil.copyfile(src, data_dir / name)
                copied.add(name)
            kept_tables.append(tid)
        it["relevant_tables"] = kept_tables
        it["relevant_docs"] = list({t.rsplit("|", 1)[0]: None for t in kept_tables})
        # drop evidence whose CSV was dropped
        it["evidence"] = [
            ev for ev in (it.get("evidence") or [])
            if (data_dir / str(ev.get("csv_path", "")).split("/")[-1]).exists()
        ]

    (out_dir / "submission.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )
    return len(copied), warnings


def zip_dir(out_dir: Path, zip_path: Path) -> None:
    """submission.json + data/ at the ZIP top level (no parent folder)."""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(out_dir / "submission.json", "submission.json")
        for csv in sorted((out_dir / "data").glob("*.csv")):
            zf.write(csv, f"data/{csv.name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True, help="pipeline JSONL")
    ap.add_argument("--out", type=Path, default=Path("output/submission"))
    ap.add_argument("--zip", type=Path, help="ZIP path (default: <out>.zip)")
    ap.add_argument(
        "--only-run-ids",
        action="store_true",
        help="build only ids present in --run (test mode; skips the all-1012 gate)",
    )
    args = ap.parse_args(argv)

    questions = load_questions()
    records = load_last_records(args.run)
    ids = sorted(records) if args.only_run_ids else sorted(questions)
    expected = None if args.only_run_ids else set(questions)

    items = [build_item(questions[i], records.get(i)) for i in ids]

    fmt_errs = validate_format(items, expected)
    n_csv, warns = stage(items, args.out)
    # re-validate paths after staging may have pruned missing-CSV tables
    fmt_errs += validate_format(items, expected)

    zip_path = args.zip or args.out.with_suffix(".zip")
    zip_dir(args.out, zip_path)

    ok_items = sum(1 for i in ids if isinstance(records.get(i, {}).get("item"), dict))
    empty_tables = sum(1 for it in items if not it["relevant_tables"])
    print(f"items={len(items)} (from-pipeline={ok_items} fallback={len(items)-ok_items})")
    print(f"empty relevant_tables (0 điểm retrieval câu đó): {empty_tables}")
    print(f"csv shipped: {n_csv}  ->  {args.out/'data'}")
    print(f"zip: {zip_path} ({zip_path.stat().st_size/1e6:.1f} MB)")
    if warns:
        print(f"warnings ({len(warns)}):")
        for w in warns[:10]:
            print(f"  {w}")
    if fmt_errs:
        print(f"\nFORMAT ERRORS ({len(fmt_errs)}) -- bài chưa hợp lệ:")
        for e in fmt_errs[:20]:
            print(f"  {e}")
        return 1
    print("\nformat OK: đủ câu, đúng schema, mọi csv_path có file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
