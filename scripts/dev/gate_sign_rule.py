"""Câu hỏi nào đòi độ lớn thay vì dấu kế toán, đo trên submission đã có.

`gate_selection_vs_reading.py` chia 73 câu sai của v8 theo *chữ ký số học*: so đáp án đã
nộp với ô gold, 59 câu đọc hẳn ô khác, 8 câu một bên bằng 0, 3 câu chỉ sai lũy thừa 10, và
**3 câu chỉ sai dấu** (774, 777, 894). Ba câu đó là lớp duy nhất sửa được bằng một luật,
không cần chạy lại LLM.

Vì sao luật hiện tại bỏ sót:

- `SIGNED_METRIC` chứa `chenh lech`, nên `cell_locator.value_transform` phủ quyết mọi câu
  hỏi hiệu số. `execute.as_magnitude` phủ quyết y hệt bằng `DIFF_CUE_LOOSE`, và docstring
  của nó viết "in those the sign *is* the answer".
- Câu đó đúng với hiệu **theo thời gian** (q623: 2023 so với 2022, đảo dấu là đảo nghĩa) và
  sai với hiệu **giữa hai pháp nhân** (q774, q777: "chênh lệch giữa A và B", thứ tự A/B do
  người viết câu chọn, nên gold ghi độ lớn).
- q894 lấy trung bình "thuế TNDN đã nộp", một khoản chi ghi âm, mà `MAGNITUDE_METRIC`
  (`chi phí|dự phòng|hao mòn|khấu hao|lãi vay`) không khớp chữ nào.

Gate này lấy `abs()` đáp án ở những câu luật ứng viên bắn, rồi chấm lại. Đúng phép vì mọi
nhân đơn vị trên đường `apply_units` đều dương, nên `abs` trong truy vấn và `abs` trên số
cuối cho cùng kết quả. Không gọi LLM, không sửa `src`.

Số mã cổ phiếu của một câu đọc lại từ `report_id` của `table_ids`: lọc cứng chỉ cho qua
bảng khớp scope, nên tập report của `table_ids` *là* danh sách mã mà understand chọn.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_sign_rule.py
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_sign_rule.py --show
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels, load_submission  # type: ignore

from finance_qa.modules.solve.common.intent import (
    AVG_CUE,
    DIFF_CUE_LOOSE,
    SELECTION_MARKER,
    intent_norm,
)

SUBMISSION = "output/submission_v8_round2/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
YEAR = re.compile(r"\b(?:19|20)\d\d\b")
TICKER_IN_REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_")
# "đã nộp / đã trả / đã chi": tiền đã ra khỏi doanh nghiệp, bảng ghi âm, câu hỏi hỏi số tiền.
PAID_OUT = re.compile(r"\bda\s+(?:nop|tra|chi)\b")


def one_period_diff(text: str, tickers: int) -> bool:
    """Hiệu số mà cả câu chỉ nhắc một mốc thời gian: proxy văn bản cho hiệu giữa hai bên."""
    return bool(DIFF_CUE_LOOSE.search(text)) and len(set(YEAR.findall(text))) <= 1


def entity_diff(text: str, tickers: int) -> bool:
    """Hiệu số giữa hai pháp nhân, đọc từ số mã trong scope."""
    return bool(DIFF_CUE_LOOSE.search(text)) and tickers >= 2


def entity_diff_one_period(text: str, tickers: int) -> bool:
    """Hiệu giữa hai pháp nhân *trong cùng một mốc*: hai bên chỉ khác nhau ở pháp nhân."""
    return entity_diff(text, tickers) and len(set(YEAR.findall(text))) <= 1


RULES = {
    "hiệu một mốc": one_period_diff,
    "hiệu hai mã": entity_diff,
    "đã nộp/trả/chi": lambda t, n: bool(PAID_OUT.search(t)),
    "hiệu một mốc + đã nộp": lambda t, n: one_period_diff(t, n) or bool(PAID_OUT.search(t)),
    "hiệu hai mã + đã nộp": lambda t, n: entity_diff(t, n) or bool(PAID_OUT.search(t)),
    "hiệu hai mã + tb đã nộp": lambda t, n: entity_diff(t, n)
    or bool(AVG_CUE.search(t) and PAID_OUT.search(t)),
    "hiệu hai mã một mốc + đã nộp": lambda t, n: entity_diff_one_period(t, n)
    or bool(PAID_OUT.search(t)),
    "trên + không sàng lọc": lambda t, n: bool(PAID_OUT.search(t)) or (
        entity_diff_one_period(t, n) and not SELECTION_MARKER.search(t)
    ),
}


def signature(submitted: float, gold: float) -> str:
    """Sai *kiểu gì*: đây là chỗ tách "sửa được bằng một luật" khỏi "đọc sai ô"."""
    if submitted == 0.0 or gold == 0.0:
        return "một bên bằng 0"
    if abs(abs(submitted) - abs(gold)) <= 0.01 * max(abs(submitted), abs(gold)):
        return "chỉ sai dấu" if submitted * gold < 0 else "khớp trong dung sai"
    ratio = abs(submitted) / abs(gold)
    for power in (-6, -3, -2, -1, 1, 2, 3, 6, 9):
        if abs(ratio / 10.0**power - 1) <= 0.01:
            return f"sai lũy thừa 10 (x1e{power})"
    return "ô khác hẳn"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="in từng câu bị đổi trong 119 câu")
    ap.add_argument("--flips", help="in cả 1012 câu mà luật tên này đổi dấu")
    args = ap.parse_args()

    labels = load_labels()
    sub = load_submission(SUBMISSION)
    solver_of: dict[int, str] = {}
    tickers_of: dict[int, int] = {}
    for line in RUN.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            solver_of[record["id"]] = str(record.get("solver") or "?")
            found = TICKER_IN_REPORT.findall(" ".join(record.get("table_ids") or []))
            tickers_of[record["id"]] = len(set(found))

    scored = sorted(i for i, g in labels.items() if g.get("answer") is not None and i in sub)
    base = {i: correct(sub[i].get("answer"), labels[i]["answer"]) for i in scored}
    print(f"\nnguyên bản {sum(base.values())}/{len(scored)}   {SUBMISSION}\n")

    wrong = [i for i in scored if not base[i]]
    classes: dict[str, list[int]] = {}
    for i in wrong:
        value, gold = as_float(sub[i].get("answer")), as_float(labels[i]["answer"])
        key = "không đọc được số" if value is None or gold is None else signature(value, gold)
        classes.setdefault(key, []).append(i)
    print(f"{len(wrong)} câu sai, theo chữ ký số học:")
    for key, ids in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        tail = f"  {sorted(ids)}" if len(ids) <= 6 else ""
        print(f"  {key:<24}{len(ids):>4}{tail}")
    print()

    negatives = [i for i in scored if (as_float(sub[i].get("answer")) or 0) < 0]
    print(f"{len(negatives)} câu đang trả số âm trong {len(scored)} câu chấm được: {negatives}")
    gold_negative = [i for i in negatives if (as_float(labels[i]["answer"]) or 0) < 0]
    print(f"nhãn cũng âm ở {len(gold_negative)} câu: {gold_negative}\n")

    for name, fires in RULES.items():
        gained, lost, flipped_all = [], [], []
        for i, item in sub.items():
            value = as_float(item.get("answer"))
            if value is None or value >= 0:
                continue
            if not fires(intent_norm(item.get("question") or ""), tickers_of.get(i, 0)):
                continue
            flipped_all.append(i)
            if i not in base:
                continue
            now = correct(abs(value), labels[i]["answer"])
            if now and not base[i]:
                gained.append(i)
            elif base[i] and not now:
                lost.append(i)
        total = sum(base.values()) + len(gained) - len(lost)
        print(f"{name:<26} {total:>3}/{len(scored)}   được {sorted(gained)}   "
              f"mất {sorted(lost)}   đổi dấu {len(flipped_all)}/1012")
        if args.show:
            for i in sorted(set(flipped_all) & set(scored)):
                mark = "được" if i in gained else "mất" if i in lost else "không đổi"
                print(f"    q{i} [{solver_of.get(i, '?')}] {mark}"
                      f"  nộp {sub[i].get('answer')}  nhãn {labels[i]['answer']}")
        if args.flips == name:
            for i in sorted(flipped_all):
                print(f"    q{i} [{solver_of.get(i, '?')}] {tickers_of.get(i, 0)} mã"
                      f"  {str(sub[i].get('question') or '')[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
