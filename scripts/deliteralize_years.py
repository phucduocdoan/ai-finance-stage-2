"""Cho câu hỏi "năm nào" chọn năm bằng dữ liệu, thay vì cộng năm vào một ô nhân 0.

`raw_selection_linker.py:813` và `project_year` trong `codegen/execute.py` cùng phát
ra một dạng: `(<ô thắng>) * 0 + <năm>`. Ý định ghi trong docstring của `project_year`
là giữ năm bên trong truy vấn để việc chấm lại tái tạo được đáp án. Ý định đúng,
nhưng `* 0` triệt tiêu ô đọc, nên cái còn lại là một hằng số. Luật thi cấm "gán cứng,
mã hóa hoặc lưu sẵn kết quả dưới bất kỳ hình thức nào", và dạng này còn khó phát hiện
hơn một hằng số trần vì nó vẫn tham chiếu một dataframe thật.

Trên bản đã nộp có 33 câu như vậy, tất cả đều là câu "năm nào".

Bản sửa: dựng lại phép so sánh mà solver đã thực sự làm rồi vứt đi. `chosen` trong
diag còn giữ đủ ô của từng năm ứng viên, nên viết lại được thành

    max([(float(<ô 2016>), 2016), (float(<ô 2021>), 2021), ...])[1]

Đổi số trong ô là đổi đáp án, tức năm không còn là hằng số nữa. Cùng phép so sánh,
cùng người thắng, nên đáp án không đổi.

Chỉ chạm được 24 trong 33 câu: 9 câu còn lại đi qua codegen, nơi các nhánh của `max`
không được ghi vào diag, nên không dựng lại được từ file run.

Điều kiện ghi đè, và đây là điều làm bước này không thể mất điểm: truy vấn mới phải
chạy được trên đúng frame mà gói nộp sẽ chở, và ra đúng đáp án cũ trong sai số
`rel_tol=1e-6` mà `build_submission.make_query_exec_safe` dùng. Câu nào không thoả
thì giữ nguyên.

Truy vấn mới đọc bảng của mọi năm ứng viên chứ không riêng năm thắng, nên phải thêm
các bảng đó vào `relevant_tables` lẫn `evidence`. Nếu chỉ thêm vào `evidence`, `stage`
sẽ không copy CSV, rồi loại chính evidence đó, rồi `make_query_exec_safe` thay truy
vấn bằng hằng số trần, tức tệ hơn dạng đang có.

Chạy TRƯỚC `build_submission.py`, cùng lý do với `recount_saturated.py`: sau khi đóng
gói thì `round_final` đã bọc truy vấn lại. Rời nhau với các bước vá khác: bước này chỉ
chạm câu có `answer_kind == "selected_year"`.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/deliteralize_years.py \
        artifacts/runs/full1012_recounted.jsonl artifacts/runs/full1012_years.jsonl
"""
from __future__ import annotations

import ast
import json
import math
import sys
from collections import Counter
from pathlib import Path

from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.modules.tools.python_exec import run_query

from repair_cell_indices import shipped_frame
from rescale_below_floor import as_float, records


def annihilated_year(query: str) -> bool:
    """Truy vấn có nhân một biểu thức với 0 hay không.

    Kiểm tra theo cấu trúc chứ không theo chuỗi, vì `abs()` bọc ngoài và khoảng
    trắng khác nhau giữa hai chỗ phát ra dạng này (q946 là `abs((abs(...)) * 0 + 2018)`).
    """
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mult)
        and any(
            isinstance(side, ast.Constant) and side.value == 0
            for side in (node.left, node.right)
        )
        for node in ast.walk(tree)
    )


def cells_of(candidate: dict) -> list[dict]:
    """Các ô của một ứng viên, dù nó là ô đơn hay một nhóm dòng cộng lại."""
    if candidate.get("kind") == "group":
        return [c for c in candidate.get("cells") or [] if c.get("table_id")]
    if candidate.get("table_id"):
        return [candidate]
    return []


def rebuilt(diag_linker: dict, tables: dict[str, str]) -> str | None:
    """Truy vấn chọn năm dựng từ `chosen`, hoặc None nếu không dựng được.

    `tables` được điền thêm tại chỗ: table_id -> tên biến. Người gọi dùng nó để
    viết `evidence` và `relevant_tables` khớp với truy vấn.
    """
    if diag_linker.get("answer_kind") != "selected_year":
        return None
    if diag_linker.get("axis") != "year":
        return None
    order = diag_linker.get("order")
    if order not in {"max", "min"}:
        return None

    by_year: dict[int, list[dict]] = {}
    for candidate in diag_linker.get("chosen") or []:
        year = candidate.get("year")
        cells = cells_of(candidate)
        if not isinstance(year, int) or not cells:
            return None
        if year in by_year:  # hai ứng viên cùng một năm: không còn là phép chọn năm
            return None
        by_year[year] = cells
    if len(by_year) < 2:
        return None

    def var(table_id: str) -> str:
        if table_id not in tables:
            tables[table_id] = f"df{len(tables) + 1}"
        return tables[table_id]

    terms = []
    for year in sorted(by_year):
        reads = [
            f"{var(c['table_id'])}.iloc[{int(c['row_position'])}][{str(c['column'])!r}]"
            for c in by_year[year]
        ]
        expr = reads[0] if len(reads) == 1 else "(" + " + ".join(reads) + ")"
        terms.append(f"(float({expr}), {year})")
    return f"{order}([{', '.join(terms)}])[1]"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    recs = records(src)

    stats: Counter[str] = Counter()
    for qid, rec in recs.items():
        item = rec.get("item") or {}
        query = str(item.get("pandas_query") or "").strip()
        if not query or not annihilated_year(query):
            continue
        stats["dạng nhân 0"] += 1

        tables: dict[str, str] = {}
        new_query = rebuilt((rec.get("diag") or {}).get("raw_selection_linker") or {}, tables)
        if new_query is None:
            stats["không dựng lại được"] += 1
            continue

        try:
            frames = {var: shipped_frame(tid) for tid, var in tables.items()}
        except Exception:  # noqa: BLE001 - một bảng không dựng được là bỏ cả câu
            stats["không dựng được frame"] += 1
            continue

        old = as_float(item.get("answer"))
        try:
            value = float(run_query(new_query, frames))
        except Exception:  # noqa: BLE001 - truy vấn mới không chạy là bỏ cả câu
            stats["viết lại không chạy được"] += 1
            continue
        if old is None or not math.isclose(value, old, rel_tol=1e-6, abs_tol=1e-9):
            stats["đáp án lệch, bỏ qua"] += 1
            print(f"  bỏ q{qid}: {old!r} -> {value!r}")
            continue

        item["pandas_query"] = new_query
        item["evidence"] = [
            {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
            for tid, var in tables.items()
        ]
        kept = list(item.get("relevant_tables") or [])
        item["relevant_tables"] = kept + [t for t in tables if t not in kept]
        stats["đã viết lại"] += 1

    dst.write_text(
        "".join(json.dumps(recs[q], ensure_ascii=False) + "\n" for q in sorted(recs)),
        encoding="utf-8",
    )
    print(f"{dict(stats)} trên {len(recs)} câu -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
