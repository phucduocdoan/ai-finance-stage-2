"""Lớp câu sàng lọc nhiều công ty: đo độ lớn và tỉ lệ đúng, không gọi LLM.

Manh mối vào: `gate_unit_default.py` in ra nhiều câu có `target_unit` là percent/ratio
mà trả về số tiền thô. Một câu hỏi tỉ lệ trả về nghìn tỉ thì sai chắc chắn, không cần
nhãn, nên tưởng là lớp riêng đáng sửa. Không phải. Tách theo số công ty trong câu hỏi
thì câu tỉ lệ một công ty đúng 5/15, bằng tỉ lệ chung, còn câu tỉ lệ sàng lọc đúng
1/16. Lớp tỉ lệ là lớp sàng lọc trá hình.

Gate này in cả hai phép tách để lần sau không phải đo lại:

1. Câu đích percent/ratio, chia theo một/hai công ty và sàng lọc.
2. Cả lớp sàng lọc trên 1012 câu, so tỉ lệ đúng với phần còn lại.

Nhận diện câu sàng lọc: từ 3 mã trở lên, hoặc có cụm "trong nhóm" / "xét các" /
"xét phân nhóm". Đây là heuristic văn bản, và nó *đếm thiếu*: câu gọi tên đầy đủ
("Tập đoàn Sao Mai", "Masan") không có mã nào nên chỉ vào lớp nhờ cụm từ. Con số ra
được vì thế là chặn dưới.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_screening_class.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from score_clean_eval import correct, load_labels, load_submission  # type: ignore

sys.path.insert(0, "scripts")
from gate_unit_default import replay  # noqa: E402

# `is_screening` (and the two regexes behind it) now live in
# `finance_qa.modules.solve.common.screening`, so the solver and every gate
# share one definition. Re-exported here, unchanged, because
# `gate_screening_run.py`, `gate_screening_evidence.py` and
# `gate_selection_reasons.py` all do `from gate_screening_class import is_screening`.
from finance_qa.modules.solve.common.screening import PHRASE, TICKER, is_screening  # noqa: E402,F401

SUBMISSION = "output/submission_v9_sign/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")


def main() -> int:
    labels = load_labels()
    sub = load_submission(SUBMISSION)
    scored = sorted(i for i, g in labels.items() if g.get("answer") is not None and i in sub)
    records = {
        int(r["id"]): r
        for r in (json.loads(l) for l in RUN.read_text().splitlines() if l.strip())
    }

    def score(ids: list[int]) -> str:
        ids = [i for i in ids if i in scored]
        ok = sum(correct(sub[i].get("answer"), labels[i]["answer"]) for i in ids)
        return f"{ok}/{len(ids)}" if ids else "-"

    ratio: list[tuple[int, bool, float, bool]] = []
    for qid, record in records.items():
        out = replay(record)
        if out is None:
            continue
        diag, raw, _ = out
        if str(diag.get("target_unit")) not in ("percent", "ratio"):
            continue
        query = str((record.get("solution") or {}).get("pandas_query") or "")
        ratio.append((qid, is_screening(str(record.get("question") or "")), raw, "/" in query))

    screening = [r for r in ratio if r[1]]
    single = [r for r in ratio if not r[1]]
    print(f"\n{len(ratio)} câu đích percent/ratio chạy lại được")
    for name, group in (("một/hai công ty", single), ("sàng lọc", screening)):
        big = sum(1 for r in group if abs(r[2]) > 1e6)
        div = sum(1 for r in group if r[3])
        print(f"  {name:<18}{len(group):>4} câu   có nhãn {score([r[0] for r in group]):<7}"
              f" trả > 1e6: {big:<4} có phép chia: {div}/{len(group)}")

    inside = [i for i, r in records.items() if is_screening(str(r.get("question") or ""))]
    lab_in = [i for i in scored if i in set(inside)]
    lab_out = [i for i in scored if i not in set(inside)]
    print(f"\nlớp sàng lọc trên {len(records)} câu: {len(inside)} câu"
          f" ({len(inside) / len(records):.0%})")
    print(f"  trong lớp   {score(lab_in)}")
    print(f"  ngoài lớp   {score(lab_out)}")
    print(f"  solver trong lớp: {Counter(str(records[i].get('solver')) for i in lab_in).most_common()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
