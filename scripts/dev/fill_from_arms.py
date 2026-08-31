"""Lấp ô chắc chắn sai của một lần chạy bằng đáp án của các lần chạy khác.

Đây là `retry_pool.py` tổng quát hóa, và nó không tốn GPU nào: hàng đợi quét đã để
lại 6 lần chạy đủ 1012 câu, tức 6 đáp án độc lập cho mỗi câu, đã trả tiền rồi.

Vì sao một chiều. Ô "chắc chắn sai" được xác định không cần nhãn, và trên 17 câu có
nhãn trong ô thì thay bằng arm khác cho 4 sai->đúng, 0 đúng->sai. Thay một đáp án
sai bằng một đáp án sai khác thì điểm y nguyên, nên arm này không có mặt âm và không
cần so với sàn nhiễu `sqrt(C)`.

Ba tiêu chí "chắc chắn sai", cả ba không cần nhãn, gộp từ hai script trước:

    == 0.0          hằng số bỏ cuộc của `graph.py` khi mọi solver từ chối
    vượt trần       `retry_pool.BAND`, hỏi phần trăm mà ra 2.3e13
    dưới sàn        `rescale_below_floor.FLOOR`, hỏi tỷ mà ra 0.0862

Thứ tự ưu tiên arm không phải tùy ý: `retry` trước vì nó là lần giải lại nhắm đúng
các câu này với đủ cờ, rồi `all_on` vì nó có ít đáp án 0.0 nhất (26 so với 50 của
head), rồi các arm còn lại. `all_on_b` và `no_verify` xuống cuối vì cả hai đo được
là tụt điểm trên tập nhãn (41 và 43 so với 50 của `head_b`).

Chạy sau script này thì đến `rescale_below_floor.py`: nó dọn các ô dưới sàn mà không
arm nào cứu được.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/fill_from_arms.py \
        artifacts/runs/full1012_head.jsonl artifacts/runs/full1012_filled.jsonl \
        artifacts/runs/retry_pool_allon2.jsonl artifacts/runs/full1012_all_on.jsonl ...
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from rescale_below_floor import FLOOR, UNITS, records
from retry_pool import verdict as band_verdict
from score_clean_eval import as_float, correct, load_labels


def certainly_wrong(qid: int, rec: dict) -> str | None:
    """Lý do đáp án này chắc chắn sai, hoặc None nếu không kết luận được."""
    v = band_verdict(qid, rec)
    if v:
        return v
    a = as_float((rec.get("item") or {}).get("answer"))
    floor = FLOOR.get(UNITS.get(qid) or "")
    if a is not None and floor is not None and 0 < abs(a) < floor:
        return f"dưới sàn {UNITS[qid]}"
    return None


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    base_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    arm_paths = [Path(p) for p in sys.argv[3:]]

    base = records(base_path)
    arms = [(p.stem, records(p)) for p in arm_paths]
    gold = {int(k): (v.get("answer") if isinstance(v, dict) else v) for k, v in load_labels().items()}

    merged, source = dict(base), {}
    flips = {"sai->đúng": 0, "đúng->sai": 0, "sai->sai": 0}
    pool = [q for q in base if certainly_wrong(q, base[q])]
    for qid in pool:
        for name, arm in arms:
            rec = arm.get(qid)
            if rec is None or certainly_wrong(qid, rec) is not None:
                continue
            merged[qid], source[qid] = rec, name
            if qid in gold and as_float(gold[qid]) is not None:
                was = correct((base[qid].get("item") or {}).get("answer"), gold[qid])
                now = correct((rec.get("item") or {}).get("answer"), gold[qid])
                flips["sai->đúng" if now and not was else "đúng->sai" if was and not now else "sai->sai"] += 1
            break

    out_path.write_text(
        "".join(json.dumps(merged[q], ensure_ascii=False) + "\n" for q in sorted(merged)),
        encoding="utf-8",
    )
    print(f"ô chắc chắn sai: {len(pool)}/{len(base)} | lấp được {len(source)} | "
          f"còn {len(pool) - len(source)} không arm nào cứu")
    print(f"nguồn: {dict(Counter(source.values()))}")
    print(f"ghi {len(merged)} dòng vào {out_path}")
    print(f"trên các câu có nhãn: {flips}")
    print("Mốc đăng ký trước: đúng->sai phải bằng 0. Có câu nào tụt là tiêu chí báo oan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
