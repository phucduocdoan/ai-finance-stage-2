"""Đáp án sai *loại đại lượng*: câu hỏi tỉ lệ, đáp án là một số dư tuyệt đối.

Tám đường trước đều là "đọc lệch một ô" và đều chết vì cùng một lý do:
`docs/miss_shape_2026-08-23.md` cho thấy 57/70 câu sai là **một con số khác hẳn**,
nên mọi đường sửa-lệch-nhỏ chỉ có 13 câu để bắn vào.

Đường này nhắm vào khối 57. Ca mẫu là q433: hỏi "hệ số nợ phải trả trên tổng tài
sản", gold 26.44, nộp -3.672.086.428.314. Truy vấn không tính tỉ số nào, nó cộng
các số dư rồi nộp. Sai đó **chứng minh được mà không cần gold**: một tỉ lệ không
thể là 10^12.

Vì thế phép đo này không cần sàn nhiễu, khác tám phép đo trước. Và nó phải nói
thẳng một chỗ dễ đọc sai: cột "câu v9 đúng" ra 0 **không phải** đối chứng, mà là
đồng nhất thức, vì đáp án đúng thì bằng gold nên không thể ngoài khoảng.

Giá trị của đường này nằm ở hình dạng phần thua, không ở phần thắng: các câu bị
bắt đã sai chắc chắn, nên chạy lại chỉ đổi được sai -> đúng hoặc sai -> sai.
**Phần thua bị chặn bằng 0 theo kiến trúc.** Với 0 thua, McNemar một phía cần 5
câu chuyển để đạt p < 0.05 và 6 câu để đạt mốc 10/2 đã chốt (p = 0.019).

Mốc chốt trước khi chạy: >= 6 trong số câu bị bắt phải chuyển thành đúng.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_answer_type.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.modules.solve.common.lookup import _norm
from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")

# Câu hỏi tỉ lệ: đáp án là phần trăm hoặc hệ số, không thể là một số dư tuyệt đối.
RATIO_QUESTION = re.compile(r"phan tram|ty le|ty trong|he so|bao nhieu %")
RATIO_UNIT_HINTS = ("percent", "%", "ratio")

# Ngưỡng phải rất lỏng để không bao giờ bắt oan. Một tỉ lệ thật hiếm khi vượt vài
# trăm phần trăm; 1e3 bỏ xa mọi giá trị hợp lệ, và số bắt được không đổi khi siết
# lên 1e4 hay 1e6, tức khối này không nằm gần ngưỡng.
LIMIT = 1e3


def is_ratio_question(question: str, unit_hint: object) -> bool:
    return bool(RATIO_QUESTION.search(_norm(question))) or unit_hint in RATIO_UNIT_HINTS


def main() -> None:
    records = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    gold_labels = {str(k): v for k, v in load_labels().items()}
    unit_hint = {}
    for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            unit_hint[str(d["id"])] = d.get("unit_hint")

    def gold_of(qid: str):
        g = gold_labels[qid]
        return g.get("answer") if isinstance(g, dict) else g

    def out_of_range(qid: str) -> bool:
        rec = records[qid]
        if not is_ratio_question(rec.get("question") or "", unit_hint.get(qid)):
            return False
        v = as_float(rec.get("answer"))
        return v is not None and abs(v) > LIMIT

    scorable = sorted(
        (q for q in gold_labels if q in records and as_float(gold_of(q)) is not None),
        key=int,
    )
    wrong = [q for q in scorable if not correct(records[q].get("answer"), gold_of(q))]
    ratio = [q for q in scorable if is_ratio_question(records[q].get("question") or "",
                                                     unit_hint.get(q))]
    caught = [q for q in wrong if out_of_range(q)]

    print(f"{len(scorable)} câu chấm được, {len(wrong)} sai, {len(ratio)} câu hỏi tỉ lệ\n")
    print(f"bắt được trong câu sai : {len(caught)}")
    print("bắt được trong câu đúng: 0 theo đồng nhất thức, không phải đối chứng\n")

    for qid in caught:
        print(f"  q{qid}: gold {gold_of(qid)}  nộp {records[qid].get('answer')}")
        print(f"       {(records[qid].get('question') or '')[:100]}")

    # Ngưỡng không được là chỗ kết quả sống nhờ. Nếu số bắt được nhảy theo ngưỡng
    # thì khối này chỉ là chuyện chọn hằng số.
    print("\nĐộ nhạy theo ngưỡng, để biết kết quả có sống nhờ hằng số hay không:")
    for limit in (1e2, 1e3, 1e4, 1e6, 1e9):
        n = sum(
            1
            for q in wrong
            if is_ratio_question(records[q].get("question") or "", unit_hint.get(q))
            and (v := as_float(records[q].get("answer"))) is not None
            and abs(v) > limit
        )
        print(f"  > {limit:.0e}: {n}")

    full = [
        q
        for q in records
        if is_ratio_question(records[q].get("question") or "", unit_hint.get(q))
        and (v := as_float(records[q].get("answer"))) is not None
        and abs(v) > LIMIT
    ]
    print(f"\nTrên toàn 1012 câu đã nộp: {len(full)} câu bị bắt "
          f"({len(full) / len(records):.1%}), so với {len(caught) / len(scorable):.1%} trên 119")


if __name__ == "__main__":
    main()
