"""Đo độ tin của nhãn máy: gán lại mù những câu đã có nhãn, rồi so hai lượt.

Câu hỏi cần trả lời trước khi đặt thêm vài trăm nhãn: nhãn máy có thay được nhãn trong
`artifacts/eval_clean/labels_*.jsonl` không? Mốc chốt trước khi chạy: khớp ≥ 95% thì đặt
thêm, dưới 90% thì dừng.

**Cả hai bên của phép so đều do Claude gán.** `artifacts/eval_clean/labels_*.jsonl` không
phải gold của BTC; nó là một lượt gán nhãn trước, đọc OCR thô (xem
`docs/leaderboard_and_strategy_2026-08-21.md` §8 và phần đính chính trong đó). Nên con số
ở đây đo **tính nhất quán giữa hai lượt của cùng một mô hình**, không đo tính đúng. Sai
lệch tương quan giữa hai lượt là không quan sát được bằng phép đo này.

Lượt hiệu chỉnh: `artifacts/label_calib/blind_tasks.jsonl` là 24 câu (seed 20260823, rút
phân tầng theo bậc L1-L6), agent chỉ thấy id và đề bài, không thấy nhãn cũ.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_label_calibration.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from score_clean_eval import as_float

GOLD = Path("artifacts/label_calib/gold_hidden.json")
PASSES = [
    ("A", Path("artifacts/label_calib/agent_labels.jsonl")),
    ("B", Path("artifacts/label_calib/agent_labels_b.jsonl")),
]
TOL = 0.01  # cùng dung sai với scripts/score_clean_eval.py

# Grader của BTC chấm chặt (§7.1), nên chỉ dò thang/dấu để *phân loại* kiểu lệch, không
# để tính là khớp.
FACTORS = [(1e3, "x1e3"), (1e-3, "/1e3"), (1e6, "x1e6"), (1e-6, "/1e6"),
           (1e9, "x1e9"), (1e-9, "/1e9"), (100, "x100"), (0.01, "/100")]


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    if abs(a - b) <= TOL:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= TOL


def classify(a: float | None, b: float | None) -> str:
    """Quan hệ giữa nhãn mới `a` và nhãn cũ `b`."""
    if a is None:
        return "bỏ trống"
    if close(a, b):
        return "khớp"
    if close(-a, b):
        return "lệch dấu"
    for f, name in FACTORS:
        if close(a * f, b):
            return f"lệch thang {name}"
        if close(-a * f, b):
            return f"dấu+thang {name}"
    return "khác hẳn"


def load_pass(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[str(rec["id"])] = rec
    return out


def main() -> None:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    loaded = [(name, load_pass(p), p) for name, p in PASSES]
    live = [(n, d) for n, d, _ in loaded if d]
    for name, data, path in loaded:
        print(f"lượt {name}: {len(data)} nhãn  ({path}{'' if data else ' — chưa có'})")
    print(f"nhãn cũ: {len(gold)} câu")
    print()

    for name, data in live:
        rows = []
        for qid in sorted(gold, key=int):
            old = as_float(gold[qid].get("answer"))
            rec = data.get(qid) or {}
            new = as_float(rec.get("answer"))
            rows.append((qid, rec.get("confidence", "?"), classify(new, old), old, new))

        print(f"=== lượt {name} so với nhãn cũ ===")
        print(f"{'câu':>5} {'tin cậy':>8} {'quan hệ':>14}   cũ / mới")
        for qid, conf, verdict, old, new in rows:
            mark = " " if verdict == "khớp" else "*"
            print(f"{mark}{qid:>4} {conf:>8} {verdict:>14}   {old} / {new}")

        n = len(rows)
        hit = sum(1 for r in rows if r[2] == "khớp")
        print(f"\nkhớp: {hit}/{n} = {hit / n:.1%}"
              f"   (mốc: ≥95% đặt thêm nhãn, <90% dừng)")
        counts = Counter(r[2] for r in rows if r[2] != "khớp")
        for k, v in counts.most_common():
            print(f"  {k:16} {v}")

        # Lọc theo tin cậy tự khai có cứu được không?
        print("  khớp theo tin cậy tự khai:")
        for conf in ("high", "medium", "low"):
            sel = [r for r in rows if r[1] == conf]
            if sel:
                ok = sum(1 for r in sel if r[2] == "khớp")
                print(f"    {conf:7} {ok}/{len(sel)} = {ok / len(sel):.0%}")
        print()

    if len(live) == 2:
        (na, da), (nb, db) = live
        print(f"=== lượt {na} so với lượt {nb} (hai lượt độc lập, cùng đề) ===")
        three = Counter()
        for qid in sorted(gold, key=int):
            old = as_float(gold[qid].get("answer"))
            a = as_float((da.get(qid) or {}).get("answer"))
            b = as_float((db.get(qid) or {}).get("answer"))
            ab, ao, bo = close(a, b), close(a, old), close(b, old)
            if ab and ao:
                kind = "cả ba khớp"
            elif ab and not ao:
                kind = "hai lượt mới khớp nhau, lệch nhãn cũ → nhãn cũ là nghi phạm"
            elif ao or bo:
                kind = "một lượt khớp nhãn cũ, lượt kia lệch"
            else:
                kind = "ba đáp án khác nhau → câu tự nó mơ hồ, nên loại"
            three[kind] += 1
            if kind != "cả ba khớp":
                print(f"  q{qid:<5} cũ={old} {na}={a} {nb}={b}  → {kind}")
        print()
        for k, v in three.most_common():
            print(f"  {k:62} {v}")


if __name__ == "__main__":
    main()
