"""Estimate the main-statement vs note-detail split across all 1012 questions.

We have NO ground-truth cell location for the full set (only 15 in evalset.json).
So this is a HEURISTIC estimate on the question text, and we validate the heuristic
against those 15 gt-labelled questions to report its accuracy before trusting the 1012 number.

Classification logic (indicator-based, not shape-based — a multi-year question can still be
about a note item, e.g. FTS q818):
  NOTE  if the text carries a breakdown / sub-item marker (theo ngành/kỳ hạn, thù lao,
        lãi tiền gửi, dự phòng rủi ro cho vay, cho thuê ...), OR names no main line at all.
  MAIN  if it names a headline BS/IS/CF line that carries a mã-số, or asks for a ratio/metric
        that is built from such lines (ROE, D/E, biên lợi nhuận, thanh toán, vòng quay ...).

Run:
    PYTHONPATH=src python3 scripts/estimate_question_class.py
"""

from __future__ import annotations

import json
from collections import Counter

QS = "data/metadata/questions_enriched.jsonl"

# strong note-detail markers: breakdowns and sub-items that never carry a statement mã-số
NOTE_MARKERS = [
    "theo ngành", "theo kỳ hạn", "theo khu vực", "theo loại", "theo đối tượng",
    "theo thời gian", "theo tiến độ", "cơ cấu",
    "lãi tiền gửi", "tiền gửi tại", "cho vay khách hàng", "dự phòng rủi ro cho vay",
    "dự phòng rủi ro tín dụng",
    "thù lao", "hội đồng quản trị", "hđqt", "ban giám đốc", "bên liên quan",
    "khen thưởng", "phúc lợi", "chi phí phạt", "chi phí nhân công", "chi phí lãi vay phải trả",
    "cho thuê khô", "cho thuê ướt", "số lượng nhân viên", "số lượng cổ phiếu",
    "mệnh giá", "cổ tức", "thuế suất", "phải thu theo tiến độ", "giao dịch với",
    "quỹ khen thưởng",
]

# ratio / derived-metric terms — always computed from main-statement lines → MAIN
RATIO_MARKERS = [
    "roe", "roa", "biên lợi nhuận", "tỷ suất lợi nhuận", "tỷ số", "hệ số",
    "d/e", "nợ trên vốn", "thanh toán", "đòn bẩy", "vòng quay", "khả năng thanh toán",
    "thanh toán nhanh", "thanh toán hiện hành", "thanh toán lãi vay", "biên",
    "số ngày tồn kho", "chuyển đổi", "tăng trưởng doanh thu",
]

# headline statement lines that carry a mã-số → MAIN
MAIN_LINES = [
    "lợi nhuận sau thuế", "lợi nhuận trước thuế", "lợi nhuận gộp", "lợi nhuận thuần",
    "lợi nhuận từ hoạt động kinh doanh", "lãi cơ bản trên cổ phiếu",
    "doanh thu thuần", "doanh thu bán hàng", "giá vốn", "tổng tài sản", "tổng nguồn vốn",
    "vốn chủ sở hữu", "nợ phải trả", "hàng tồn kho", "tài sản ngắn hạn", "tài sản dài hạn",
    "nợ ngắn hạn", "nợ dài hạn", "tài sản cố định", "vốn cổ phần",
    "lưu chuyển tiền thuần", "dòng tiền", "chi phí tài chính", "doanh thu hoạt động tài chính",
    "chi phí bán hàng", "chi phí quản lý doanh nghiệp", "giá vốn hàng",
    "lãi thuần từ hoạt động dịch vụ", "thu nhập lãi thuần", "lãi thuần từ hoạt động kinh doanh",
]


def classify(text: str) -> str:
    t = text.casefold()
    if any(m in t for m in NOTE_MARKERS):
        return "NOTE"
    if any(m in t for m in RATIO_MARKERS):
        return "MAIN"
    if any(m in t for m in MAIN_LINES):
        return "MAIN"
    return "NOTE"  # names no headline line and no ratio → treat as note-detail sub-item


def main() -> None:
    qs = [json.loads(l) for l in open(QS, encoding="utf-8")]

    # ---- validate against the 15 gt-labelled questions ----
    gt_note = {1, 100, 524, 754, 818}
    gt_main = {17, 40, 44, 55, 363, 582, 605, 674, 752, 820}
    gt = {**{q: "NOTE" for q in gt_note}, **{q: "MAIN" for q in gt_main}}
    by_id = {q["id"]: q for q in qs}

    conf = Counter()
    print("=== validation on 15 gt-labelled questions ===")
    print(f"{'qid':>4} {'truth':>5} {'pred':>5}  ok  question")
    for qid in sorted(gt):
        truth = gt[qid]
        pred = classify(by_id[qid]["question"])
        ok = "✓" if pred == truth else "✗"
        conf[(truth, pred)] += 1
        print(f"{qid:>4} {truth:>5} {pred:>5}   {ok}  {by_id[qid]['question'][:70]}")
    correct = conf[("NOTE", "NOTE")] + conf[("MAIN", "MAIN")]
    print(f"heuristic accuracy on gt: {correct}/15 = {correct/15:.0%}")
    print(f"  confusion: MAIN→MAIN {conf[('MAIN','MAIN')]}  MAIN→NOTE {conf[('MAIN','NOTE')]}  "
          f"NOTE→NOTE {conf[('NOTE','NOTE')]}  NOTE→MAIN {conf[('NOTE','MAIN')]}")

    # ---- apply to all 1012 ----
    cls = Counter(classify(q["question"]) for q in qs)
    n = len(qs)
    print(f"\n=== estimate on all {n} questions ===")
    for c in ("MAIN", "NOTE"):
        print(f"  {c:<5} {cls[c]:>5}  {cls[c]/n:>4.0%}")

    # split by answer_shape for context
    print("\n=== by answer_shape ===")
    for shape in ("single_cell", "derived"):
        sub = [q for q in qs if q["answer_shape"] == shape]
        sc = Counter(classify(q["question"]) for q in sub)
        print(f"  {shape:<12} (n={len(sub):>4}):  MAIN {sc['MAIN']:>4} ({sc['MAIN']/len(sub):.0%})  "
              f"NOTE {sc['NOTE']:>4} ({sc['NOTE']/len(sub):.0%})")


if __name__ == "__main__":
    main()
