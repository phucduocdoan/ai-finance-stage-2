"""Chấm hai file `run_graph` trên tập eval sạch và in chênh lệch từng câu.

`score_clean_eval.py` chấm submission đã dựng; cái này chấm thẳng record của
`scripts/run_graph.py`, để A/B một thay đổi mà không phải dựng submission hai lần.

In cả độ phủ mã của các bảng codegen thật sự được xem, vì đó là biến đang can thiệp:
nếu độ phủ lên mà điểm không lên thì nút thắt nằm sau bước nạp bảng, và đó cũng là
kết quả -- chỉ là không phải kết quả ta mong.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/score_run_ab.py \
        artifacts/runs/mc38_control.jsonl artifacts/runs/mc38_slots.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from score_clean_eval import correct, load_labels  # noqa: E402

CSV_TICKER = re.compile(r"([A-Z0-9]+)_")


def load_run(path: str) -> dict[int, dict]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[int(row["id"])] = row.get("item") or {}
    return out


def tickers_seen(item: dict) -> set[str]:
    out = set()
    for ev in item.get("evidence") or []:
        match = CSV_TICKER.match(Path(ev.get("csv_path", "")).name)
        if match:
            out.add(match.group(1))
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    labels = load_labels()
    enriched = {
        r["id"]: r
        for r in (
            json.loads(line)
            for line in Path("data/metadata/questions_enriched.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }
    a, b = (load_run(p) for p in sys.argv[1:3])
    ids = sorted(
        i for i in set(a) & set(b)
        if i in labels and labels[i].get("answer") is not None
    )

    rows = []
    for i in ids:
        want = set(enriched[i].get("tickers") or [])
        rows.append({
            "id": i,
            "gold": labels[i]["answer"],
            "a": a[i].get("answer"),
            "b": b[i].get("answer"),
            "ok_a": correct(a[i].get("answer"), labels[i]["answer"]),
            "ok_b": correct(b[i].get("answer"), labels[i]["answer"]),
            "cov_a": want <= tickers_seen(a[i]),
            "cov_b": want <= tickers_seen(b[i]),
            "n_ev_a": len(a[i].get("evidence") or []),
            "n_ev_b": len(b[i].get("evidence") or []),
        })

    n = len(rows)
    ka, kb = sum(r["ok_a"] for r in rows), sum(r["ok_b"] for r in rows)
    ca, cb = sum(r["cov_a"] for r in rows), sum(r["cov_b"] for r in rows)
    print(f"{n} câu có nhãn, chạy được cả hai nhánh\n")
    print(f"{'':<10}{'A (đối chứng)':>16}{'B (ô mã×năm)':>16}")
    print(f"{'đúng':<10}{f'{ka}/{n}':>16}{f'{kb}/{n}':>16}")
    print(f"{'phủ đủ mã':<10}{f'{ca}/{n}':>16}{f'{cb}/{n}':>16}")
    ev_a = sorted(r["n_ev_a"] for r in rows)
    ev_b = sorted(r["n_ev_b"] for r in rows)
    print(f"{'bảng nạp':<10}{f'trung vị {ev_a[n // 2]}':>16}{f'trung vị {ev_b[n // 2]}':>16}")

    gained = [r["id"] for r in rows if r["ok_b"] and not r["ok_a"]]
    lost = [r["id"] for r in rows if r["ok_a"] and not r["ok_b"]]
    print(f"\nB so với A: +{len(gained)} / -{len(lost)} = {len(gained) - len(lost):+d}")
    print(f"  được: {gained}")
    print(f"  mất : {lost}")

    # Câu đã phủ đủ mã mà vẫn sai là phần việc còn lại, và nó đo được riêng.
    still = [r["id"] for r in rows if r["cov_b"] and not r["ok_b"]]
    print(f"\nphủ đủ mã nhưng vẫn sai: {len(still)}/{cb}  {still}")

    print(f"\n{'id':>5} {'gold':>14} {'A':>14} {'B':>14}  phủ A/B  bảng A/B")
    for r in rows:
        mark = " +" if r["ok_b"] and not r["ok_a"] else (" -" if r["ok_a"] and not r["ok_b"] else "  ")
        print(f"{r['id']:>5} {str(r['gold']):>14} {str(r['a']):>14} {str(r['b']):>14}"
              f"   {int(r['cov_a'])}/{int(r['cov_b'])}     {r['n_ev_a']:>2}/{r['n_ev_b']:<2}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
