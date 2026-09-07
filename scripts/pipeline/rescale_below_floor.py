"""Đáp án nhỏ hơn sàn của đơn vị nó được hỏi: nhân lũy thừa 10 cho vào dải.

Bước hậu xử lý chạy trên file run đã hoàn tất, giữa `run_graph.py` và
`build_submission.py`. Nó không phải một solver: nó cần `unit_hint` của toàn bộ
câu hỏi và chỉ nhìn con số cuối cùng, nên nó sống ngoài `modules/solve/`.

Vì sao nhóm này sửa được mà nhóm vượt trần thì không. Trên tập nhãn, các câu vượt
trần lệch 2.6e11 tới 3.4e13, không phải lũy thừa 10, nên không có phép nhân nào
cứu được. Nhóm dưới sàn thì lệch đúng một lũy thừa 10:

    q1004  phần trăm  ta=0.0527   gold=5.27     thiếu ×100
    q772   tỷ         ta=0.0862   gold=86.25    thiếu ×1e3

Đó là hai lỗi khác nhau về nguyên nhân: một là tỉ số trả về dạng thập phân khi câu
hỏi hỏi phần trăm, một là nhận sai đơn vị nguồn của bảng nên chia quá tay. Cả hai
để lại cùng một dấu vết: mantissa hợp lý, số mũ lệch.

Sàn dưới đây suy từ ngữ nghĩa đơn vị, KHÔNG khớp từ tập nhãn: một khoản mục tài
chính không bằng một phần nghìn của chính đơn vị nó được hỏi. Kiểm chéo sau khi
đặt: cả 82 đáp án vàng có `unit_hint` đều nằm trên sàn của nó, thấp nhất là
`trăm tỷ` 0.11 so với sàn 0.01.

Một chiều giống rổ chắc chắn sai: chỉ chạm những đáp án gần như chắc chắn đã sai,
nên đổi sai thì điểm y nguyên. Đo trên lần chạy HEAD ngày 23/08: gắn cờ 38/1012,
đổi được 34, và trên 3 câu có nhãn trong nhóm thì 2 sai->đúng, 0 đúng->sai.

`pandas_query` được bọc cùng hệ số, không chỉ sửa `answer`. `EXECUTION_ACCURACY`
chấm bằng cách chạy lại query, nên sửa một mình con số sẽ làm hai chỉ số lệch nhau
đúng như v7/v8/v9 (execution thấp hơn answer 2 câu).

KHÔNG bắt được: q284, q139, q748 lệch lũy thừa 10 nhưng vẫn nằm trong dải vàng của
đơn vị chúng. Muốn bắt phải so đáp án với ô gốc trong `pandas_query`.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/rescale_below_floor.py \
        artifacts/runs/full1012.jsonl artifacts/runs/full1012_rescaled.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Sàn theo đơn vị được hỏi. Không có `none`/`count`/`đồng`: hai cái đầu không nói
# gì về thang, còn `đồng` có đáp án vàng thấp tới 3.375 nên sàn của nó vô dụng.
FLOOR = {
    "phần trăm": 0.1,
    "tỷ": 0.1,
    "lần": 0.01,
    "nghìn tỷ": 0.1,
    "trăm tỷ": 0.01,
    "triệu": 1.0,
}

# Hệ số thử, theo thứ tự, lấy cái đầu tiên đưa đáp án vào dải. `phần trăm` và
# `lần` chỉ thử ×100 vì lỗi của chúng là tỉ số chưa đổi sang phần trăm, không
# phải lẫn thang tiền.
CANDIDATES = {"phần trăm": [100.0], "lần": [100.0]}
MONEY_CANDIDATES = [1e3, 1e6, 1e9, 1e12]

QUESTIONS = Path("data/metadata/questions_enriched.jsonl")


def as_float(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def unit_hints() -> dict[int, str | None]:
    return {
        int(json.loads(line)["id"]): json.loads(line).get("unit_hint")
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
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


def factor(rec: dict, unit: str | None) -> float | None:
    """Hệ số cần nhân, hoặc None nếu câu này không dưới sàn / không cứu được."""
    a = as_float((rec.get("item") or {}).get("answer"))
    floor = FLOOR.get(unit or "")
    if a is None or a == 0 or floor is None or abs(a) >= floor:
        return None
    for k in CANDIDATES.get(unit or "", MONEY_CANDIDATES):
        if abs(a * k) >= floor:
            return k
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    recs = records(src)
    units = unit_hints()

    changed = 0
    for qid, rec in recs.items():
        k = factor(rec, units.get(qid))
        if k is None:
            continue
        item = rec["item"]
        old = as_float(item.get("answer"))
        item["answer"] = old * k
        item["pandas_query"] = f"({item.get('pandas_query') or old}) * {k:g}"
        changed += 1

    dst.write_text(
        "".join(json.dumps(recs[q], ensure_ascii=False) + "\n" for q in sorted(recs)),
        encoding="utf-8",
    )
    print(f"đổi thang {changed}/{len(recs)} câu -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
