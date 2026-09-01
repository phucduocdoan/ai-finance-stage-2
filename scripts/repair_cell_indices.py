"""Định vị lại ô cho các query lệch chỉ số vì header hai tầng bị gộp.

Vấn đề. Bảng có header hai tầng được các solver đọc khi tầng leaf còn nằm như
một dòng dữ liệu: cột tên `"Giá trị số kế toán"`, `"Vay và nợ"` ở hàng 2. Lúc
đóng gói, `load_frame` gộp hai tầng thành `"Giá trị số kế toán | 31/12/2020"`
và dòng leaf biến mất khỏi thân bảng, nên nhãn đó tụt về hàng 1. Query mang chỉ
số và tên cột của frame cũ đem chạy trên CSV đã ship thì `KeyError`, và
`build_submission.make_query_exec_safe` thay nó bằng `repr(answer)`. Đáp án vẫn
đúng, nhưng query trở thành hằng số, đúng dạng luật cấm.

Cách sửa. `diag["profile_validate"]["query_cells"]` ghi lại từng phép đọc ô kèm
`row_label`, `column_index` và chuỗi `expression` nguyên văn. Định vị lại hàng
theo nhãn và cột theo chỉ số, rồi thay đúng chuỗi con đó trong query. Cả nhãn
lẫn chỉ số cột đều là thứ solver ghi ra từ ngữ nghĩa câu hỏi, không phải suy
ngược từ đáp án.

Ô nào có `row_label` rỗng thì suy độ lệch hàng từ các ô có nhãn trong cùng
frame: độ lệch là tính chất của bảng, giống nhau cho mọi hàng.

Đáp án chỉ dùng làm cửa kiểm tra cuối. Query sau khi vá phải chạy được và tái
tạo đúng `answer` đã ghi, nếu không thì giữ nguyên bản cũ. Cùng chuẩn mà
`facts/cellexpr.py` dùng `fact.value`: định vị bằng ngữ nghĩa, đối chiếu bằng
giá trị.

Không sửa `answer`, nên không đổi ANSWER_ACCURACY. Chỉ đổi query từ hằng số
thành phép đọc thật, và câu nào không tái tạo được thì degrade về đúng hành vi
cũ.

Chạy sau `repair_fact_queries.py`, trước `build_submission.py`.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/repair_cell_indices.py \
        artifacts/runs/full1012_repaired.jsonl artifacts/runs/full1012_cells.jsonl
"""
from __future__ import annotations

import io
import json
import math
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd

from finance_qa.modules.data.table_store import load_frame, submission_csv_name
from finance_qa.modules.tools.python_exec import run_query

from rescale_below_floor import as_float, records

TOLERANCE = 1e-4


@lru_cache(maxsize=2048)
def shipped_frame(table_id: str):
    """Frame đúng như nó nằm trong ZIP: `load_frame` rồi vòng qua CSV.

    Vòng CSV không thừa. `build_submission.stage` ghi `load_frame(tid).to_csv(...)`
    còn bộ chấm đọc lại bằng `read_csv`, và vòng đó đổi dtype của cột lẫn lộn số
    với chữ. Vá trên frame chưa vòng thì sẽ nhận nhầm những câu mà bộ chấm vẫn
    thấy hỏng.
    """
    try:
        return pd.read_csv(io.StringIO(load_frame(table_id).to_csv(index=False)))
    except Exception:
        return None


def frames_for(item: dict) -> dict[str, pd.DataFrame]:
    """`{tên biến: frame}` dựng từ evidence, khớp csv_path về lại table_id."""
    by_path = {f"data/{submission_csv_name(t)}": t for t in item.get("relevant_tables") or []}
    out: dict[str, pd.DataFrame] = {}
    for ev in item.get("evidence") or []:
        table_id = by_path.get(str(ev.get("csv_path") or ""))
        frame = shipped_frame(table_id) if table_id else None
        if frame is None:
            return {}
        out[str(ev.get("variable") or "")] = frame
    return out


def reproduces(query: str, frames: dict, answer: float) -> bool:
    try:
        value = float(run_query(query, frames))
    except Exception:
        return False
    return math.isclose(value, answer, rel_tol=TOLERANCE, abs_tol=1e-9)


def label_positions(frame: pd.DataFrame, label: str) -> list[int]:
    """Các hàng mang đúng nhãn này, dò trên mọi cột chữ.

    Không chỉ cột 0: bảng cân đối kế toán để `Mã số` ở cột đầu và tên chỉ tiêu ở
    cột `TÀI SẢN` bên cạnh.
    """
    found: list[int] = []
    for column in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[column]):
            continue
        text = frame[column].astype(str).str.strip()
        found.extend(pos for pos, value in enumerate(text) if value == label)
    return sorted(set(found))


def row_shift(cells: list[dict], frames: dict) -> dict[str, int]:
    """Độ lệch hàng của mỗi frame, suy từ các ô có nhãn."""
    votes: dict[str, Counter] = {}
    for cell in cells:
        variable = str(cell.get("variable") or "")
        label = str(cell.get("row_label") or "").strip()
        frame = frames.get(variable)
        if not label or frame is None:
            continue
        recorded = cell.get("row_position")
        if not isinstance(recorded, int):
            continue
        found = label_positions(frame, label)
        if not found:
            continue
        best = min(found, key=lambda pos: abs(pos - recorded))
        votes.setdefault(variable, Counter())[best - recorded] += 1
    return {var: counter.most_common(1)[0][0] for var, counter in votes.items()}


def relocated(cell: dict, frames: dict, shifts: dict[str, int]) -> str | None:
    """Biểu thức đọc ô sau khi định vị lại, hoặc None nếu không định vị được."""
    variable = str(cell.get("variable") or "")
    frame = frames.get(variable)
    index = cell.get("column_index")
    recorded = cell.get("row_position")
    if frame is None or not isinstance(index, int) or not isinstance(recorded, int):
        return None
    if not 0 <= index < len(frame.columns):
        return None
    label = str(cell.get("row_label") or "").strip()
    found = label_positions(frame, label) if label else []
    if found:
        position = min(found, key=lambda pos: abs(pos - recorded))
    elif variable in shifts:
        # Nhãn rỗng hoặc đã bị gộp vào header: dùng độ lệch của chính bảng đó,
        # suy từ những ô còn tìm được nhãn.
        position = recorded + shifts[variable]
    else:
        position = None
    if position is None or not 0 <= position < len(frame):
        return None
    return f"{variable}.iloc[{position}][{str(frame.columns[index])!r}]"


def repaired_query(rec: dict, frames: dict) -> str | None:
    item = rec.get("item") or {}
    cells = ((rec.get("diag") or {}).get("profile_validate") or {}).get("query_cells") or []
    query = str(item.get("pandas_query") or "")
    if not cells or not query:
        return None
    shifts = row_shift(cells, frames)
    out = query
    for cell in cells:
        original = str(cell.get("expression") or "")
        if not original or original not in out:
            return None
        replacement = relocated(cell, frames, shifts)
        if replacement is None:
            return None
        out = out.replace(original, replacement)
    return None if out == query else out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    recs = records(src)

    stats: Counter[str] = Counter()
    for rec in recs.values():
        item = rec.get("item") or {}
        answer = as_float(item.get("answer"))
        query = str(item.get("pandas_query") or "")
        if answer is None or not query:
            continue
        frames = frames_for(item)
        if not frames:
            stats["không dựng được frame"] += 1
            continue
        if reproduces(query, frames, answer):
            stats["query cũ đã chạy đúng"] += 1
            continue
        stats["query cũ hỏng"] += 1
        candidate = repaired_query(rec, frames)
        if candidate is None:
            stats["không định vị lại được"] += 1
            continue
        if not reproduces(candidate, frames, answer):
            stats["vá xong vẫn không tái tạo answer"] += 1
            continue
        item["pandas_query"] = candidate
        stats["VÁ ĐƯỢC"] += 1

    dst.write_text(
        "".join(json.dumps(recs[q], ensure_ascii=False) + "\n" for q in sorted(recs)),
        encoding="utf-8",
    )
    for key, count in stats.most_common():
        print(f"{count:5d}  {key}")
    print(f"-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
