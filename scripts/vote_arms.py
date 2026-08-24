"""Chọn đáp án theo cụm đông nhất giữa nhiều lần chạy đủ 1012 câu.

Đây là bước nền của v13, trước giờ nằm trong code rời nên không chạy lại được. Luật
đúng như đã nộp: gom đáp án của các arm thành cụm theo giá trị số làm tròn tương đối,
lấy cụm đông nhất, và lấy nguyên bản ghi của arm đứng đầu thứ tự ưu tiên trong cụm đó.

Lấy nguyên bản ghi, không chỉ lấy con số, vì `EXECUTION_ACCURACY` chấm cả
`pandas_query`: một con số không kèm query sinh ra nó thì mất điểm cột thứ hai.

Thứ tự ưu tiên arm là thứ tự tham số dòng lệnh. Nó chỉ phá thế hòa, và hòa là chuyện
thường: `docs/final_week_plan_2026-08-23.md` đo được "đông arm đồng ý" không mang thông
tin về đúng sai (`d = 0.51`, đáp án sai dồn cục), nên đừng đọc phiếu như độ tin cậy.
Bỏ phiếu ở đây chỉ để không cược vào một arm nhiễu, `head` với `head_b` cùng cấu hình
mà lệch nhau 4 câu trên tập nhãn.

Đối chiếu với bản đã nộp: chạy trên 6 arm của hàng đợi cho 846/1012 câu trùng số với
`artifacts/runs/full1012_voted.jsonl`, nền của v13. 166 câu lệch là do thứ tự phá thế
hòa, thứ tự cũ không ghi lại được. Trên tập nhãn 53 so với 55, tức trong nhiễu.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/vote_arms.py \
        artifacts/runs/full1012_voted.jsonl \
        artifacts/runs/full1012_all_on_a.jsonl artifacts/runs/full1012_head_b.jsonl ...
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from rescale_below_floor import records
from score_clean_eval import as_float, correct, load_labels

# Hai đáp án cùng một cụm khi lệch nhau dưới mức này theo tỉ lệ. Nới hơn thì các câu
# phần trăm làm tròn khác nhau (12,3 với 12,34) bị tách thành hai phiếu vô ích.
TOL = 1e-6


def cluster_key(value: float, seen: list[float]) -> float:
    """Đại diện cụm đã có mà `value` thuộc về, hoặc chính nó nếu là cụm mới."""
    for other in seen:
        scale = max(abs(value), abs(other), 1.0)
        if abs(value - other) <= TOL * scale:
            return other
    seen.append(value)
    return value


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    out_path = Path(sys.argv[1])
    arms = [(Path(p).stem, records(Path(p))) for p in sys.argv[2:]]

    qids = sorted({q for _, arm in arms for q in arm})
    chosen: dict[int, dict] = {}
    winner_arm: Counter[str] = Counter()
    sizes: Counter[int] = Counter()

    for qid in qids:
        votes: list[tuple[str, dict, float | None]] = []
        for name, arm in arms:
            rec = arm.get(qid)
            if rec is None:
                continue
            votes.append((name, rec, as_float((rec.get("item") or {}).get("answer"))))
        numeric = [v for v in votes if v[2] is not None]
        if not numeric:
            # Không arm nào ra số: giữ arm ưu tiên cao nhất có bản ghi, để câu này vẫn
            # có một dòng trong bài nộp.
            chosen[qid] = votes[0][1]
            sizes[0] += 1
            continue
        seen: list[float] = []
        keys = [cluster_key(value, seen) for _, _, value in numeric]
        top = Counter(keys).most_common(1)[0][0]
        name, rec, _ = next(v for v, key in zip(numeric, keys) if key == top)
        chosen[qid] = rec
        winner_arm[name] += 1
        sizes[Counter(keys)[top]] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(chosen[q], ensure_ascii=False) + "\n" for q in qids),
        encoding="utf-8",
    )
    print(f"{len(arms)} arm, {len(qids)} câu -> {out_path}")
    print(f"arm thắng: {dict(winner_arm.most_common())}")
    print(f"cỡ cụm thắng: {dict(sorted(sizes.items()))}")

    gold = {int(k): (v.get("answer") if isinstance(v, dict) else v) for k, v in load_labels().items()}
    gold = {k: v for k, v in gold.items() if as_float(v) is not None}
    ok = sum(1 for q in gold if q in chosen and correct((chosen[q].get("item") or {}).get("answer"), gold[q]))
    print(f"tập nhãn: {ok}/{len(gold)}")
    print("Đọc con số trên đúng cách: SE ≈ 2,8 câu, nên nó không chọn được hướng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
