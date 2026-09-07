"""Lấp ô chắc chắn sai của một lần chạy bằng đáp án của các lần chạy khác.

Pipeline không tất định: cùng code, cùng server, cùng temperature 0, hai lần chạy
lệch nhau khoảng 30% số đáp án (vLLM gộp batch liên tục, thành phần batch đổi thì
kết quả đổi). Script này biến cái đó thành lợi thế thay vì chỉ chịu đựng nó.

Vì sao một chiều, và vì sao không cần sàn nhiễu. Ô "chắc chắn sai" xác định được mà
KHÔNG cần nhãn. Thay một đáp án chắc chắn sai bằng một đáp án sai khác thì điểm y
nguyên, nên arm này không có mặt âm. Mọi arm cờ đều có thể làm tụt điểm nên phải so
với `sqrt(C)` rồi tính z; arm này thì không.

Đo hai lần, cách nhau một tuần, mốc "đúng->sai phải bằng 0" đặt trước cả hai:

    23/08  17 câu có nhãn trong rổ   4 sai->đúng   0 đúng->sai
    31/08  12 câu có nhãn trong rổ   0 sai->đúng   0 đúng->sai

Ba tiêu chí "chắc chắn sai", cả ba không cần nhãn:

    == 0.0          hằng số bỏ cuộc `graph.py` ghi khi mọi solver trong SOLVER_CHAIN
                    đã từ chối. Nó là dấu bỏ cuộc, không phải một phép tính ra 0.
                    Đối chiếu: chỉ 3 trên 1012 đáp án vàng bằng 0.
    vượt trần BAND  hỏi phần trăm mà ra 2.3e13 thì sai theo định nghĩa đơn vị
    dưới sàn FLOOR  hỏi tỷ mà ra 0.0862, xem `rescale_below_floor.py`

Thứ tự arm truyền vào có ý nghĩa: arm đầu tiên cho đáp án ra khỏi rổ sẽ thắng. Xếp
arm đáng tin nhất lên trước.

Chạy script này TRƯỚC `rescale_below_floor.py`: rescale dọn nốt các ô dưới sàn mà
không arm nào cứu được.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/fill_from_arms.py \
        artifacts/runs/run_a.jsonl artifacts/runs/filled.jsonl \
        artifacts/runs/run_b.jsonl artifacts/runs/run_c.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from rescale_below_floor import FLOOR, as_float, records, unit_hints

# Trần biên độ theo đơn vị, giá trị tuyệt đối, tính bằng chính đơn vị được hỏi.
# Suy từ ngữ nghĩa đơn vị, không khớp từ tập nhãn. `none` và `count` không nói gì
# về thang nên không có mặt; `trăm tỷ` chưa có câu có nhãn nào trong rổ để kiểm.
BAND = {
    "phần trăm": 1e4,  # tăng trưởng có thể vượt 100 nhưng không vượt 1e4
    "lần": 1e4,
    "nghìn tỷ": 1e4,
    "tỷ": 1e7,
    "triệu": 1e10,
    "đồng": 1e15,
}


def certainly_wrong(rec: dict, unit: str | None) -> str | None:
    """Lý do đáp án này chắc chắn sai, hoặc None nếu không kết luận được."""
    a = as_float((rec.get("item") or {}).get("answer"))
    if a is None:
        return "rỗng"
    if a == 0:
        return "bằng 0 (mặc định bỏ cuộc)"
    u = unit or ""
    cap = BAND.get(u)
    if cap and abs(a) > cap:
        return f"vượt trần {u} (>{cap:g})"
    floor = FLOOR.get(u)
    if floor is not None and abs(a) < floor:
        return f"dưới sàn {u} (<{floor:g})"
    return None


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    base_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    base = records(base_path)
    arms = [(p.stem, records(p)) for p in map(Path, sys.argv[3:])]
    units = unit_hints()

    merged, source = dict(base), {}
    pool = [q for q in base if certainly_wrong(base[q], units.get(q))]
    for qid in pool:
        for name, arm in arms:
            rec = arm.get(qid)
            if rec is None or certainly_wrong(rec, units.get(qid)) is not None:
                continue
            merged[qid], source[qid] = rec, name
            break

    out_path.write_text(
        "".join(json.dumps(merged[q], ensure_ascii=False) + "\n" for q in sorted(merged)),
        encoding="utf-8",
    )
    print(
        f"ô chắc chắn sai: {len(pool)}/{len(base)} | lấp được {len(source)} | "
        f"còn {len(pool) - len(source)} không arm nào cứu"
    )
    print(f"nguồn: {dict(Counter(source.values()))}")
    print(f"ghi {len(merged)} dòng vào {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
