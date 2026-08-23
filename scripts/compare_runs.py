"""So hai lần chạy 1012 câu: sàn nhiễu run-to-run, không cần nhãn, không cần lượt nộp.

Vì sao cần: temperature là 0.0 ở mọi caller, nhưng vLLM với continuous batching
không xác định theo bit, `REPAIR_TEMPERATURE` là 0.3, và workers=24 đổi thứ tự.
Repo đã ghi hai lần chạy baseline lệch 2 câu trên 94; nhân lên 1012 là ~21 câu,
tức 2.1 điểm phần trăm, lớn hơn gần như mọi đường trong hàng đợi quét.

Nếu không có con số này thì một delta leaderboard nhỏ hơn nó không đọc được, y
hệt cách sàn 5.4 câu của tập 119 đã làm chín đường trước thành vô nghĩa.

Hai cột phải đọc riêng:
  đổi đáp án  — bao nhiêu câu ra số khác. Đây là cận trên của nhiễu điểm, vì một
                câu sai ở cả hai lần chạy đổi số mà không đổi điểm.
  đổi điểm    — trên các câu có nhãn, bao nhiêu câu đổi đúng/sai. Đây là con số
                thật cần so với delta, nhưng nó chỉ đo được trên 119 câu.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/compare_runs.py \
        artifacts/runs/full1012_head.jsonl artifacts/runs/full1012_head_b.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels


def answers(path: Path) -> dict[int, float | None]:
    """Đáp án cuối cùng cho mỗi id; bản ghi sau ghi đè bản ghi trước (--resume)."""
    out: dict[int, float | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out[int(d["id"])] = (d.get("item") or {}).get("answer")
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = answers(a_path), answers(b_path)

    shared = sorted(set(a) & set(b))
    print(f"{a_path.name}: {len(a)} câu")
    print(f"{b_path.name}: {len(b)} câu")
    print(f"chung: {len(shared)}\n")

    # Dung sai tương đối, vì hai lần chạy có thể lệch ở chữ số cuối do batching
    # chứ không do model chọn ô khác. 1e-9 tách được hai chuyện đó.
    def same(x, y) -> bool:
        fx, fy = as_float(x), as_float(y)
        if fx is None or fy is None:
            return fx is None and fy is None
        if fx == fy:
            return True
        scale = max(abs(fx), abs(fy), 1e-12)
        return abs(fx - fy) / scale < 1e-9

    changed = [q for q in shared if not same(a[q], b[q])]
    print(f"đổi đáp án: {len(changed)}/{len(shared)} = {len(changed) / len(shared):.1%}")
    print("  (cận trên của nhiễu điểm: câu sai ở cả hai lần đổi số mà không đổi điểm)")

    gold = {int(k): v for k, v in load_labels().items()}

    def gold_of(qid: int):
        g = gold[qid]
        return g.get("answer") if isinstance(g, dict) else g

    labeled = [q for q in shared if q in gold and as_float(gold_of(q)) is not None]
    ra = [q for q in labeled if correct(a[q], gold_of(q))]
    rb = [q for q in labeled if correct(b[q], gold_of(q))]
    won = sorted(set(rb) - set(ra))
    lost = sorted(set(ra) - set(rb))

    print(f"\ntrên {len(labeled)} câu có nhãn:")
    print(f"  {a_path.stem}: {len(ra)} đúng")
    print(f"  {b_path.stem}: {len(rb)} đúng")
    print(f"  đổi điểm: +{len(won)} / -{len(lost)}  ròng {len(rb) - len(ra):+d}")
    if won:
        print(f"    B được: {', '.join(f'q{q}' for q in won)}")
    if lost:
        print(f"    B mất : {', '.join(f'q{q}' for q in lost)}")

    churn = len(won) + len(lost)
    print(f"\nsàn nhiễu đọc được: {churn} câu trên {len(labeled)} có nhãn"
          f" = {churn / len(labeled):.1%}, tức ~{round(churn / len(labeled) * 1012)} câu trên 1012")
    print("So mọi delta của hàng đợi quét với con số này, không với 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
