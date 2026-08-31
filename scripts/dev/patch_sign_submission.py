"""Áp luật dấu lên một submission đã có, không gọi LLM và không đổi bằng chứng.

Vì sao vá thay vì chạy lại cả 1012 câu: luật dấu nằm hoàn toàn trong `apply_units`,
không đổi prompt, không đổi retrieval, không đổi bảng nào được chọn. Chạy lại full
sẽ xáo 58 câu "ô khác hẳn" theo nhiễu LLM, mà biên độ nhiễu đó lớn hơn +3 câu cần
đo. Vá thì 989 câu còn lại giữ nguyên từng byte.

Cách làm, mỗi câu một lần:

1. Dựng lại `df1..dfN` từ `diag["evidence_tables"]` và chạy `apply_units` hai lượt,
   một với luật mới và một với `between_two_companies`/`PAID_OUT` bị vô hiệu hoá.
2. Nếu hai lượt ra cùng kết quả thì bỏ qua, không chạm vào câu đó.
3. Nếu khác, kiểm tra lượt "luật cũ" có tái tạo đúng con số đã nộp không. Không
   khớp nghĩa là replay không trung thực với câu đó (solver khác, hoặc bảng đã
   đổi), và câu đó bị bỏ qua chứ không vá theo phỏng đoán.
4. Khớp thì thay cả `answer` và `pandas_query`. Cả hai, vì EXECUTION_ACCURACY chạy
   lại chuỗi truy vấn đã nộp: vá số mà không vá truy vấn thì hai chỉ số chỏi nhau.

`round(..., 2)` được áp lại đúng như `build_submission.round_final` làm, nên câu
được vá và câu không được vá cùng một dạng.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/patch_sign_submission.py \
        --src output/submission_v8_round2 --out output/submission_v9_sign
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen import execute
from finance_qa.modules.solve.codegen.execute import apply_units
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.tools.python_exec import run_query

RUN = Path("artifacts/runs/full1012_v7.jsonl")
TICKER_IN_REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_")
NEVER = re.compile(r"(?!x)x")


def replay(record: dict, *, new_rule: bool) -> tuple[float, str] | None:
    """Chạy lại đuôi tất định. Trả về (giá trị, truy vấn) hoặc None nếu không chạy được."""
    solution = PandasSolution.model_validate(record.get("solution") or {})
    if not (solution.pandas_query or "").strip():
        return None
    frames = {}
    # `names` cũng phải truyền: `apply_units` tra đơn vị trong page text của bảng qua
    # nó, và thiếu nó thì q744 rơi về "mặc định vnd" rồi bị chia thêm 1e6.
    names = {}
    for i, table_id in enumerate((record.get("diag") or {}).get("evidence_tables") or [], 1):
        names[f"df{i}"] = table_id
        try:
            frames[f"df{i}"] = load_frame(table_id)
        except Exception:  # noqa: BLE001 - bảng thiếu thì bỏ câu này
            return None
    if not frames:
        return None

    saved = (execute.between_two_companies, execute.PAID_OUT)
    if not new_rule:
        execute.between_two_companies = lambda *_: False  # type: ignore[assignment]
        execute.PAID_OUT = NEVER  # type: ignore[assignment]
    try:
        query, _ = apply_units(
            solution, frames,
            question=record.get("question") or "",
            names=names,
            tickers=sorted(set(TICKER_IN_REPORT.findall(" ".join(record.get("table_ids") or [])))),
        )
    finally:
        execute.between_two_companies, execute.PAID_OUT = saved

    try:
        return float(run_query(query, dict(frames))), query
    except Exception:  # noqa: BLE001 - truy vấn lỗi thì bỏ câu này
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="output/submission_v8_round2")
    ap.add_argument("--out", default="output/submission_v9_sign")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in, không ghi gì")
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    items = json.loads((src / "submission.json").read_text())
    by_id = {int(it["id"]): it for it in items}
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]

    patched, skipped_drift, unchanged, unreplayable = [], [], 0, 0
    for record in records:
        qid = int(record["id"])
        item = by_id.get(qid)
        if item is None:
            continue
        old = replay(record, new_rule=False)
        new = replay(record, new_rule=True)
        if old is None or new is None:
            unreplayable += 1
            continue
        if old[0] == new[0]:
            unchanged += 1
            continue
        was = item.get("answer")
        if round(old[0], 2) != was:
            skipped_drift.append((qid, was, round(old[0], 2)))
            continue
        item["answer"] = round(new[0], 2)
        item["pandas_query"] = f"round({new[1]}, 2)"
        patched.append((qid, was, item["answer"]))

    print(f"\nvá {len(patched)} câu, giữ nguyên {len(items) - len(patched)} câu")
    print(f"  luật không đổi kết quả   {unchanged}")
    print(f"  không chạy lại được      {unreplayable}")
    print(f"  replay lệch, bỏ qua      {len(skipped_drift)}")
    for qid, was, now in skipped_drift:
        print(f"      q{qid} đã nộp {was} nhưng replay ra {now}")
    print()
    for qid, was, now in patched:
        print(f"  q{qid}  {was}  ->  {now}")

    if args.dry_run:
        return 0

    out.mkdir(parents=True, exist_ok=True)
    if (src / "data").is_dir() and not (out / "data").exists():
        # Bằng chứng không đổi: luật dấu không chọn lại bảng nào.
        shutil.copytree(src / "data", out / "data")
    (out / "submission.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nđã ghi {out / 'submission.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
