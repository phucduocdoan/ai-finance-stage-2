"""Chấm tỉ lệ đúng của đường L3 hai kỳ bằng nhãn mù, không dùng eval sạch.

`scripts/gate_l3_pair_fire.py` đã đo tỉ lệ *bắn* (29% ở ngưỡng 0.78). Số hạng còn
thiếu của phép định giá là tỉ lệ *đúng khi bắn*, và trong 15 câu bắn chỉ 2 câu có nhãn
tay. Kịch bản này ghép cặp ô ta định vị (`artifacts/l3_pair/located_hidden.json`) với
nhãn do một agent gán mù (`artifacts/l3_pair/agent_labels.jsonl`, agent chỉ thấy đề
bài, không thấy ô nào của ta, không thấy đáp án v9).

So ở mức **giá trị ô thô**, không so đáp án cuối. Lý do: agent khai đơn vị tự do
("%", "tỷ đồng", "million VND") còn pipeline khai `target_unit`, nên so đáp án cuối sẽ
lẫn lỗi định vị ô với lỗi quy đổi đơn vị. Đường hai kỳ chỉ chịu trách nhiệm phần định
vị ô. Phần đáp án v9 vẫn in ra nhưng để riêng, và có dò cả hệ số 1e3/1e6/1e9.

Giới hạn: nhãn là do máy gán, chưa qua hiệu chỉnh trên câu đã có nhãn tay. Hai câu có
nhãn tay (613, 643) được in riêng như một mẩu kiểm chứng, n = 2.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_l3_pair_accuracy.py
"""

from __future__ import annotations

import json
from pathlib import Path

LOCATED = Path("artifacts/l3_pair/located_hidden.json")
LABELS = Path("artifacts/l3_pair/agent_labels.jsonl")
CLEAN = Path("artifacts/eval_clean")

TOL = 0.01  # cùng dung sai với scripts/score_clean_eval.py


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    if abs(a - b) <= TOL:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= TOL


def scaled_match(a: float | None, b: float | None) -> str | None:
    """Khớp sau khi cho phép đổi thang hoặc đổi dấu; trả về mô tả, hoặc None."""
    if a is None or b is None:
        return None
    for factor, name in ((1.0, ""), (1e3, "x1e3"), (1e-3, "/1e3"),
                         (1e6, "x1e6"), (1e-6, "/1e6"),
                         (1e9, "x1e9"), (1e-9, "/1e9")):
        if close(a * factor, b):
            return name or "khớp"
        if close(-a * factor, b):
            return f"lệch dấu {name}".strip()
    return None


def as_float(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main() -> None:
    located = json.loads(LOCATED.read_text())
    labels = {}
    for line in LABELS.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            labels[str(d["id"])] = d

    hand = {}
    for p in sorted(CLEAN.glob("labels_*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                hand[str(d["id"])] = d

    print(f"câu bắn: {len(located)}   nhãn agent: {len(labels)}")
    print()

    both = one = none = 0
    rows = []
    for qid in sorted(located, key=int):
        loc = located[qid]
        lab = labels.get(qid)
        if lab is None:
            rows.append((qid, "thiếu nhãn", "", ""))
            continue
        ours = [as_float(c.get("value")) for c in loc["cells"]]
        # Nhãn khai theo cũ/mới; ô ta định vị theo thứ tự năm tăng dần.
        theirs = [as_float((lab.get("old") or {}).get("raw_value")),
                  as_float((lab.get("new") or {}).get("raw_value"))]
        hits = [scaled_match(o, t) for o, t in zip(ours, theirs)]
        n_hit = sum(1 for h in hits if h)
        if n_hit == 2:
            both += 1
        elif n_hit == 1:
            one += 1
        else:
            none += 1
        rows.append((
            qid,
            f"{n_hit}/2",
            lab.get("confidence", "?"),
            " | ".join(h or "lệch" for h in hits),
        ))

    print(f"{'câu':>5} {'ô khớp':>7} {'tin cậy':>8}  chi tiết")
    for qid, hit, conf, detail in rows:
        print(f"{qid:>5} {hit:>7} {conf:>8}  {detail}")
    print()
    n = len(located)
    print(f"khớp cả 2 ô: {both}/{n} = {both / n:.0%}")
    print(f"khớp 1 ô:    {one}/{n}")
    print(f"lệch cả 2:   {none}/{n}")
    print()

    # v9 trên đúng 15 câu này, để có phép so cặp.
    v9_hit = 0
    print("v9 so với nhãn agent (đáp án cuối, có dò thang và dấu):")
    for qid in sorted(located, key=int):
        lab = labels.get(qid)
        if lab is None:
            continue
        v9 = as_float(located[qid].get("v9"))
        gold = as_float(lab.get("answer"))
        m = scaled_match(v9, gold)
        if m:
            v9_hit += 1
        print(f"{qid:>5}  v9={v9}  nhãn={gold} {lab.get('unit', '')}  -> {m or 'sai'}")
    print(f"v9 đúng: {v9_hit}/{len(labels)} = {v9_hit / len(labels):.0%}")
    print()

    # Hai câu đã có nhãn tay: kiểm chứng nhỏ cho chính nhãn agent.
    overlap = sorted(set(labels) & set(hand), key=int)
    print(f"câu có cả nhãn tay và nhãn agent: {overlap or 'không có'}")
    for qid in overlap:
        h = as_float(hand[qid].get("answer"))
        a = as_float(labels[qid].get("answer"))
        print(f"{qid:>5}  tay={h}  agent={a}  -> {scaled_match(a, h) or 'lệch'}")


if __name__ == "__main__":
    main()
