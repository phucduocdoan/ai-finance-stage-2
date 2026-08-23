"""Hình dạng của 70 câu sai: lệch một chút, hay là một con số khác hẳn?

Bảy đường đã định giá đều là đường "sửa một lệch nhỏ": chọn dòng bên cạnh, chọn cột
bên cạnh, chọn bản sao khác của bảng, sửa tên cột gõ sai. Nếu số câu sai chỉ lệch
một chút so với gold thì những đường đó phải đáng nhiều câu. Nếu nó là một con số
khác hẳn thì không đường nào trong nhóm đó đáng gì, và đó mới là lời giải thích cho
hình dạng của cả bảy lần đo.

Phép đo không cần sàn nhiễu, khác bảy phép đo trước: lệch **đúng** một lũy thừa của
10, hoặc **đúng** một dấu, không phải chuyện trùng ngẫu nhiên. Chỉ có một cạm bẫy và
nó có xuất hiện thật: dung sai 1% làm hai số cách nhau 9.92 lần bị nhận là "đúng
x10", nên số thô của nhóm 10^k phải đọc kèm danh sách câu.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_miss_shape.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")
EXPONENTS = [k for k in range(-12, 13) if k != 0]


def near(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.01, abs(b) * 0.01)


def main() -> None:
    records = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    gold_labels = {str(k): v for k, v in load_labels().items()}

    def gold_of(qid: str):
        g = gold_labels[qid]
        return g.get("answer") if isinstance(g, dict) else g

    scorable = sorted(
        (q for q in gold_labels if q in records and as_float(gold_of(q)) is not None),
        key=int,
    )
    wrong = [q for q in scorable if not correct(records[q].get("answer"), gold_of(q))]
    print(f"{len(scorable)} câu chấm được, {len(wrong)} câu sai\n")

    scale, sign, both, zero, other = [], [], [], [], []
    for qid in wrong:
        a, g = as_float(records[qid].get("answer")), as_float(gold_of(qid))
        if a is None or a == 0.0 or g == 0.0:
            zero.append(qid)
        elif (k := next((k for k in EXPONENTS if near(a, g * 10**k)), None)) is not None:
            scale.append((qid, k, a, g))
        elif near(a, -g):
            sign.append((qid, a, g))
        elif (k := next((k for k in EXPONENTS if near(a, -g * 10**k)), None)) is not None:
            both.append((qid, k, a, g))
        else:
            other.append(qid)

    print(f"lệch đúng 10^k        : {len(scale)}   {dict(Counter(k for _, k, _, _ in scale))}")
    print(f"chỉ lệch dấu          : {len(sign)}")
    print(f"lệch cả dấu và 10^k   : {len(both)}")
    print(f"đáp án 0.0            : {len(zero)}")
    print(f"một con số khác hẳn   : {len(other)} = {len(other) / len(wrong):.0%}\n")
    for qid, k, a, g in scale:
        print(f"  q{qid}: nộp {a} gold {g}  (x1e{k})")
    for qid, a, g in sign:
        print(f"  dấu q{qid}: nộp {a} gold {g}")
    for qid, k, a, g in both:
        print(f"  dấu+scale q{qid}: nộp {a} gold {g}  (x1e{k})")


if __name__ == "__main__":
    main()
