"""Chấm một submission trên tập eval sạch, tách theo sáu bậc L1-L6.

Sáu bậc là taxonomy trong `docs/CELL_LOCATOR_STATUS.md`: L1 đọc một ô, L2 công thức
2-3 ô, L3 hai kỳ cùng một chỉ tiêu, L4 hai pháp nhân, L5 gộp nhiều năm/công ty,
L6 multi-hop (kết quả trung gian quyết định bảng kế tiếp).

Bộ phân loại ở đây đọc **văn bản câu hỏi**, không đọc nhãn, nên nó là xấp xỉ: một
câu "tỷ lệ X trên Y năm 2023" và một câu "X năm 2023 là bao nhiêu" phân biệt được,
nhưng "chênh lệch giữa hai công ty" và "chênh lệch giữa hai năm" thì dựa vào việc
đếm mã và đếm năm, và cả hai phép đếm đều thiếu khi câu gọi tên đầy đủ. Đọc số theo
bậc như chặn trên của độ tin cậy, đừng đọc như nhãn thật.

Chỗ sót đã đo: 44 câu trong 1012 nêu từ ba pháp nhân trở lên bằng tên đầy đủ, không
mã nào, nên `is_screening` không thấy. Chúng rơi xuống L1 (13), L3 (12), L2 (3),
L4 (2) và 14 câu vẫn vào L5 nhờ cue khác. Trên 119 câu eval sạch chỉ 3 câu bị sót
(q506 vào L1, q735 vào L3, q919 vào L5), nên bảng điểm dưới đây lệch không đáng kể,
nhưng con số 210 câu của lớp sàng lọc thì là chặn dưới, thực tế khoảng 240.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_type_split.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.common.intent import (  # noqa: E402
    AVG_CUE,
    DIFF_CUE_LOOSE,
    GROWTH_CUE,
    MAX_MARKER,
    MIN_MARKER,
    RATIO_CUE,
    SUM_CUE,
    TICKER_ANSWER_MARKER,
    YEAR_ANSWER_MARKER,
    intent_norm,
)
from finance_qa.modules.solve.common.screening import TICKER, is_screening  # noqa: E402

from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

QUESTIONS = Path("ViFinQA/questions/questions.jsonl")
YEAR = re.compile(r"\b(?:19|20)\d\d\b")


def level(question: str) -> str:
    """Bậc thấp nhất mà câu hỏi này còn vừa. Thứ tự kiểm là từ khó xuống dễ."""
    norm = intent_norm(question)
    years = set(YEAR.findall(question))
    tickers = set(TICKER.findall(question))

    # L6: đáp án là một mã hoặc một năm, tức phải chọn xong thực thể rồi mới đọc số,
    # hoặc chọn quán quân rồi hỏi một chỉ tiêu khác.
    if YEAR_ANSWER_MARKER.search(norm) or TICKER_ANSWER_MARKER.search(norm):
        return "L6"
    if (MAX_MARKER.search(norm) or MIN_MARKER.search(norm)) and is_screening(question):
        return "L6"

    # L5: gộp qua nhiều công ty hoặc nhiều năm.
    if is_screening(question):
        return "L5"
    if AVG_CUE.search(norm) or SUM_CUE.search(norm) or len(years) >= 3:
        return "L5"

    # L4: hai pháp nhân, một kỳ.
    if len(tickers) == 2 and DIFF_CUE_LOOSE.search(norm):
        return "L4"

    # L3: cùng một chỉ tiêu, hai kỳ.
    if GROWTH_CUE.search(norm) or len(years) >= 2:
        return "L3"
    if DIFF_CUE_LOOSE.search(norm):
        return "L3"

    # L2: một công thức trên vài ô cùng kỳ.
    if RATIO_CUE.search(norm):
        return "L2"

    return "L1"


def why(got: float | None, gold: float | None) -> str:
    """Vì sao một câu sai, đọc bằng chính con số chứ không mở lại bảng.

    Tách "lệch đơn vị" khỏi "sai ô" vì hai thứ này sửa ở hai chỗ khác nhau: một
    cái ở `execute.apply_units`, một cái ở khâu định vị hàng và cột. Luỹ thừa 10
    tròn là bằng chứng đủ chắc cho lỗi đơn vị, vì hai ô khác nhau của một báo cáo
    hầu như không bao giờ lệch nhau đúng một luỹ thừa 10.
    """
    if correct(got, gold):
        return "đúng"
    if got is None or gold is None or got == 0:
        return "không ra số"
    if abs(abs(got) - abs(gold)) / max(abs(got), abs(gold)) < 0.01 and (got < 0) != (gold < 0):
        return "sai dấu"
    k = math.log10(abs(got / gold))
    if abs(k - round(k)) < 0.02 and round(k) != 0:
        return "lệch đơn vị"
    return "sai ô"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    labels = load_labels()
    questions = {
        json.loads(line)["id"]: json.loads(line)["question"]
        for line in QUESTIONS.read_text().splitlines()
        if line.strip()
    }
    subs = [(Path(p).parent.name, load_submission(p)) for p in sys.argv[1:]]

    buckets: dict[str, list[int]] = defaultdict(list)
    for qid, lab in sorted(labels.items()):
        if as_float(lab.get("answer")) is None:
            continue  # không chấm được, xem score_clean_eval
        buckets[level(questions[qid])].append(qid)

    total = sum(len(v) for v in buckets.values())
    print(f"tập eval sạch: {total} câu chấm được\n")
    head = "  bậc   n   " + "".join(f"{name[:22]:>24}" for name, _ in subs)
    print(head)
    for lvl in ["L1", "L2", "L3", "L4", "L5", "L6"]:
        ids = buckets.get(lvl, [])
        cells = ""
        for _, sub in subs:
            hit = sum(1 for q in ids if correct(sub.get(q, {}).get("answer"), labels[q].get("answer")))
            share = f"{hit / len(ids):.0%}" if ids else "-"
            cells += f"{f'{hit}/{len(ids)}  {share}':>24}"
        print(f"  {lvl}  {len(ids):>3}   {cells}")
    cells = ""
    for _, sub in subs:
        hit = sum(
            1 for ids in buckets.values() for q in ids if correct(sub.get(q, {}).get("answer"), labels[q].get("answer"))
        )
        cells += f"{f'{hit}/{total}  {hit / total:.0%}':>24}"
    print(f"  TỔNG {total:>3}   {cells}")

    _, first = subs[0]

    print("\ntrần lý thuyết nếu một bậc lên 100%:")
    base = sum(
        1 for ids in buckets.values() for q in ids if correct(first.get(q, {}).get("answer"), labels[q].get("answer"))
    )
    for lvl in ["L1", "L2", "L3", "L4", "L5", "L6"]:
        ids = buckets.get(lvl, [])
        miss = [q for q in ids if not correct(first.get(q, {}).get("answer"), labels[q].get("answer"))]
        print(f"  {lvl}: +{len(miss):>2} câu  ->  {(base + len(miss)) / total:.0%}")

    print(f"\nnguyên nhân sai của {Path(sys.argv[1]).parent.name}:")
    print(f"  {'bậc':<5}{'n':>4}{'đúng':>7}{'sai ô':>8}{'lệch đơn vị':>13}{'sai dấu':>9}{'không ra số':>13}")
    causes: Counter[str] = Counter()
    for lvl in ["L1", "L2", "L3", "L4", "L5", "L6"]:
        c: Counter[str] = Counter()
        for q in buckets.get(lvl, []):
            gold = as_float(labels[q].get("answer"))
            got = as_float(first.get(q, {}).get("answer"))
            c[why(got, gold)] += 1
        causes.update(c)
        print(
            f"  {lvl:<5}{sum(c.values()):>4}{c['đúng']:>7}{c['sai ô']:>8}"
            f"{c['lệch đơn vị']:>13}{c['sai dấu']:>9}{c['không ra số']:>13}"
        )
    print(
        f"  {'TỔNG':<5}{total:>4}{causes['đúng']:>7}{causes['sai ô']:>8}"
        f"{causes['lệch đơn vị']:>13}{causes['sai dấu']:>9}{causes['không ra số']:>13}"
    )

    # Câu sai vì không có dữ liệu và câu sai dù có dữ liệu là hai việc khác hẳn nhau,
    # và tỉ lệ giữa chúng quyết định nên sửa retriever hay sửa khâu đọc ô.
    print(f"\ncâu sai: thiếu bằng chứng hay đọc sai ({Path(sys.argv[1]).parent.name}):")
    print(f"  {'bậc':<5}{'n':>4}{'đúng':>7}{'sai khi đọc':>13}{'thiếu báo cáo':>15}")
    tally: Counter[str] = Counter()
    for lvl in ["L1", "L2", "L3", "L4", "L5", "L6"]:
        c = Counter()
        for q in buckets.get(lvl, []):
            if correct(first.get(q, {}).get("answer"), labels[q].get("answer")):
                c["đúng"] += 1
                continue
            report = str(labels[q].get("report_id") or "")
            shortlist = " ".join(map(str, first.get(q, {}).get("relevant_tables") or []))
            c["đọc" if report and report in shortlist else "truy xuất"] += 1
        tally.update(c)
        print(f"  {lvl:<5}{sum(c.values()):>4}{c['đúng']:>7}{c['đọc']:>13}{c['truy xuất']:>15}")
    print(f"  {'TỔNG':<5}{total:>4}{tally['đúng']:>7}{tally['đọc']:>13}{tally['truy xuất']:>15}")


if __name__ == "__main__":
    main()
