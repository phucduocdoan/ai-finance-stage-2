"""Rổ câu chắc chắn sai: lọc ra để giải lại, rồi ghép về có bảo vệ.

Vì sao rổ này khác mọi arm khác trong tuần: thay một đáp án chắc chắn sai bằng một
đáp án sai khác thì điểm y nguyên, nên nó không có mặt âm và không cần sàn nhiễu để
đọc. Mọi arm cờ đều có thể làm điểm tụt nên phải so với `sqrt(C)` rồi tính z.

Hai tiêu chí, cả hai không cần nhãn:

  đáp án == 0.0     `graph.py` ghi hằng số này khi mọi solver trong SOLVER_CHAIN đã
                    từ chối (`"answer": 0.0, "pandas_query": "0.0"`). Nó là dấu bỏ
                    cuộc, không phải một phép tính ra 0.
  vượt biên độ      `unit_hint` trong questions_enriched.jsonl nói đáp án phải ở thang
                    nào. Hỏi phần trăm mà ra 2.3e13 thì sai theo định nghĩa, không
                    phải theo thống kê.

Biên độ dưới đây suy từ NGỮ NGHĨA đơn vị, không khớp từ tập nhãn, nên nó không ăn
gian tập 119 câu. Đo trên 888 câu đầu của lần chạy HEAD: bắt 78 câu, và trên 16 câu
của rổ có nhãn sạch thì báo oan 0.

Ba `unit_hint` bị bỏ ra ngoài có lý do: `none` và `count` không nói gì về thang, còn
`trăm tỷ` chưa có câu nào có nhãn trong rổ nên chưa kiểm được biên của nó.

Cái rổ này KHÔNG bắt được: nhóm đúng mantissa sai lũy thừa 10 (q139, q284, q748, q772),
vì biên của `triệu`/`đồng` rộng tới 1e10/1e15. Xem docs/final_week_plan_2026-08-23.md.

Dùng:
    # 1. lấy danh sách id
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/retry_pool.py ids \
        artifacts/runs/full1012_head.jsonl

    # 2. giải lại bằng cấu hình khác, ra file riêng
    env PYTHONPATH=src SOLVE_...=1 .venv_bge/bin/python scripts/run_graph.py \
        --ids "$(...)" --workers 24 --out artifacts/runs/retry_pool.jsonl

    # 3. ghép, chỉ nhận đáp án mới nếu nó ra khỏi rổ
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/retry_pool.py merge \
        artifacts/runs/full1012_head.jsonl artifacts/runs/retry_pool.jsonl \
        artifacts/runs/full1012_head_retried.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels

# Trần biên độ theo đơn vị. Giá trị tuyệt đối, đơn vị là chính đơn vị được hỏi.
BAND = {
    "phần trăm": 1e4,  # tăng trưởng có thể vượt 100 nhưng không vượt 1e4
    "lần": 1e4,
    "nghìn tỷ": 1e4,
    "tỷ": 1e7,
    "triệu": 1e10,
    "đồng": 1e15,
}

UNITS = {
    int(json.loads(line)["id"]): json.loads(line).get("unit_hint")
    for line in Path("data/metadata/questions_enriched.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
}


def records(path: Path) -> dict[int, dict]:
    """Bản ghi cuối cho mỗi id; bản sau ghi đè bản trước, khớp cách --resume nối file."""
    out: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[int(d["id"])] = d
    return out


def verdict(qid: int, rec: dict) -> str | None:
    """Lý do câu này chắc chắn sai, hoặc None nếu không kết luận được."""
    a = as_float((rec.get("item") or {}).get("answer"))
    if a is None:
        return "rỗng"
    if a == 0:
        return "bằng 0 (mặc định bỏ cuộc)"
    cap = BAND.get(UNITS.get(qid) or "")
    if cap and abs(a) > cap:
        return f"vượt biên độ {UNITS[qid]} (>{cap:g})"
    return None


def cmd_ids(run: Path) -> int:
    recs = records(run)
    pool = {q: v for q in sorted(recs) if (v := verdict(q, recs[q]))}
    print(",".join(str(q) for q in pool))
    counts: dict[str, int] = {}
    for v in pool.values():
        counts[v] = counts.get(v, 0) + 1
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {k}", file=sys.stderr)
    print(f"  rổ {len(pool)}/{len(recs)} = {len(pool) / len(recs):.1%}", file=sys.stderr)
    return 0


def cmd_merge(base: Path, retry: Path, out: Path) -> int:
    """Ghép có bảo vệ: chỉ nhận đáp án mới khi nó ra khỏi rổ.

    Không nhận bừa mọi đáp án mới, vì lần giải lại cũng có thể ra 0.0 hoặc một số
    vượt biên độ, và khi đó nó không tốt hơn cái đang có.
    """
    b, r = records(base), records(retry)
    gold = {int(k): (v.get("answer") if isinstance(v, dict) else v) for k, v in load_labels().items()}

    taken, kept_old, flips = 0, 0, {"sai->đúng": 0, "đúng->sai": 0, "sai->sai": 0}
    merged = dict(b)
    for qid, new in r.items():
        old = b.get(qid)
        if old is None or verdict(qid, old) is None:
            continue  # câu này không ở trong rổ, không được phép thay
        if verdict(qid, new) is not None:
            kept_old += 1
            continue
        merged[qid] = new
        taken += 1
        if qid in gold and as_float(gold[qid]) is not None:
            was = correct((old.get("item") or {}).get("answer"), gold[qid])
            now = correct((new.get("item") or {}).get("answer"), gold[qid])
            if was != now:
                flips["sai->đúng" if now else "đúng->sai"] += 1
            elif not now:
                flips["sai->sai"] += 1

    out.write_text(
        "".join(json.dumps(merged[q], ensure_ascii=False) + "\n" for q in sorted(merged)),
        encoding="utf-8",
    )
    print(f"nhận đáp án mới: {taken}  |  giữ bản cũ vì bản mới vẫn trong rổ: {kept_old}")
    print(f"ghi {len(merged)} dòng vào {out}")
    print(f"trên các câu có nhãn: {flips}")
    print("Mốc đăng ký trước: sai->đúng >= 3 thì giữ đường này, dưới thì đóng.")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "ids":
        return cmd_ids(Path(sys.argv[2]))
    if len(sys.argv) == 5 and sys.argv[1] == "merge":
        return cmd_merge(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
