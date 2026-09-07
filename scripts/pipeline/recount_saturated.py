"""Đếm lại các câu hỏi đếm, và bỏ đơn vị mà `apply_units` đã áp sai lên chúng.

Hai lỗi, cùng nằm ở những câu mà đáp án là *số lượng thực thể*.

`apply_units` đọc đơn vị đích bằng `unit_from_hint` trên câu hỏi, và "Có bao nhiêu
ngân hàng có X trên 40 tỷ đồng" chỉ nêu đơn vị bên trong *ngưỡng so sánh*. Đáp án
là một số ngân hàng, không có đơn vị nào. Trên lần chạy đã nộp, q563, q932 và q983
đều bị nhân `1e-09`, rồi `build_submission.round_final` làm tròn 2 chữ số biến kết
quả thành `0.0`, tức trông y như một câu bỏ cuộc.

Nặng hơn: numpy định nghĩa `+` trên bool là *hoặc* logic, nên `(c1) + (c2) + (c3)`
bão hoà ở True chứ không đếm. Ba công ty vượt ngưỡng và một công ty vượt ngưỡng đều
ra 1, im lặng, không báo lỗi. q435 đã nộp `1.0` trong khi số đếm thật là 3, và đó
là ca nguy hiểm nhất vì `1.0` trông như một đáp án bình thường.

`modules/solve/codegen/execute.py` đã sửa gốc bằng `is_count_query` và
`canonical_count`, nhưng chỉ có tác dụng cho lần chạy mới. File run đã có trên đĩa
thì vá được ngay mà không cần gọi lại LLM, vì phép biến đổi thuần cú pháp: cây cộng
toàn so sánh là vô đơn vị theo cấu trúc, không phải theo suy đoán từ chữ tiếng Việt.

Chỉ ghi đè khi query viết lại chạy được và ra một số nguyên không âm, tức đúng dạng
một số đếm phải có. `answer` và `pandas_query` luôn được ghi cùng nhau nên chúng
nhất quán theo cấu trúc, đó chính là điều `EXECUTION_ACCURACY` chấm.

Chạy TRƯỚC `build_submission.py`, vì `round_final` bọc `pandas_query` vào
`round(float(...), 2)` và đẩy hệ số tỷ lệ vào bên trong lớp bọc, chỗ mà
`strip_scale_factor` không tới được. Rời nhau với `repair_fact_queries.py`: bước đó
chỉ chạm query hằng số, còn bước này chỉ chạm cây cộng so sánh, nên thứ tự giữa hai
bước không quan trọng.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/recount_saturated.py \
        artifacts/runs/full1012_cells.jsonl artifacts/runs/full1012_recounted.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from finance_qa.modules.solve.codegen.execute import canonical_count, is_count_query
from finance_qa.modules.solve.common.units import strip_scale_factor
from finance_qa.modules.tools.python_exec import run_query

from repair_cell_indices import frames_for
from rescale_below_floor import as_float, records


def counted(query: str, frames: dict) -> float | None:
    """Giá trị của query, hoặc None nếu nó không chạy hoặc không ra số đếm.

    Một số đếm là số nguyên không âm. Kiểm tra đó vừa loại được query hỏng, vừa
    loại được trường hợp `is_count_query` nhận nhầm một biểu thức không phải đếm.
    """
    try:
        value = float(run_query(query, frames))
    except Exception:
        return None
    if value < 0 or not value.is_integer():
        return None
    return value


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    recs = records(src)

    stats: Counter[str] = Counter()
    moved: list[tuple[int, float | None, float]] = []
    for qid, rec in recs.items():
        item = rec.get("item") or {}
        query = str(item.get("pandas_query") or "").strip()
        if not query:
            continue
        raw, _ = strip_scale_factor(query)
        if not is_count_query(raw):
            continue
        stats["là câu đếm"] += 1
        rewritten = canonical_count(raw) or raw
        frames = frames_for(item)
        if not frames:
            stats["không dựng được frame"] += 1
            continue
        value = counted(rewritten, frames)
        if value is None:
            stats["viết lại không chạy được"] += 1
            continue
        old = as_float(item.get("answer"))
        if old is None or value != old:
            moved.append((qid, old, value))
            stats["đáp án đổi"] += 1
        elif rewritten == query:
            stats["không cần đổi"] += 1
            continue
        else:
            stats["chỉ query đổi"] += 1
        item["answer"] = value
        item["pandas_query"] = rewritten

    dst.write_text(
        "".join(json.dumps(recs[q], ensure_ascii=False) + "\n" for q in sorted(recs)),
        encoding="utf-8",
    )
    for qid, old, value in moved:
        print(f"  q{qid}: {old!r} -> {value!r}")
    print(f"{dict(stats)} trên {len(recs)} câu -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
