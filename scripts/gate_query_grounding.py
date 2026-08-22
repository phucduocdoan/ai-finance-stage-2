"""`pandas_query` có index vào cột và dòng thật sự tồn tại không, đo trên cả 1012 câu.

`config.py:218` ghi kiểu lỗi mà nó thấy khi nâng trần bảng: "a column name taken from df2
used to index df5". Nếu đúng vậy thì đây là lỗi **xác định**: tên cột có tồn tại trong frame
hay không là một phép kiểm tra, không cần LLM, không cần nhãn. Gate này đếm nó.

Đo trên `artifacts/runs/full1012_v7.jsonl`, không gọi LLM và không dùng nhãn, nên nó nói về
cả 1012 câu chứ không chỉ 119 câu chấm được.

Bốn nhóm rời nhau cho mỗi truy vấn:

- `ok`           mọi tên cột và chỉ số dòng đều nằm trong frame nó index
- `cột lạ`       index vào một cột không có trong frame đó
- `dòng quá tầm` `.iloc[i]` với i >= số dòng
- `biến lạ`      index vào `dfN` mà `evidence_tables` không có phần tử thứ N

`cột lạ` tách thêm hai nhánh, vì hai nhánh này dẫn tới hai cách sửa khác nhau:

- `mượn từ df khác`  tên cột đó *có* trong một frame khác cùng câu -> đúng kiểu lỗi
                     `config.py:218` mô tả, chặn được bằng cách kiểm tra rồi bắt sinh lại
- `bịa hẳn`          không frame nào của câu đó có tên cột này -> model tự nghĩ ra

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_query_grounding.py
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_query_grounding.py --show 15
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

from finance_qa.modules.data.table_store import load_frame

RUN = Path("artifacts/runs/full1012_v7.jsonl")


def _root(node: ast.AST) -> tuple[str | None, str | None]:
    """`(tên biến df, accessor)` của một biểu thức index.

    Accessor là `iloc`/`loc` khi index đi qua chúng, None khi index thẳng vào frame.
    Chuỗi `.iloc` gần nhất là cái quyết định, nên nó được đọc trước khi đi sâu.
    """
    accessor = None
    while True:
        if isinstance(node, ast.Name):
            return node.id, accessor
        if isinstance(node, ast.Attribute):
            if accessor is None and node.attr in {"iloc", "loc", "at", "iat"}:
                accessor = node.attr
            node = node.value
            continue
        if isinstance(node, ast.Subscript):
            # Kết quả của một phép index trước đó; accessor của tầng này đã hết hiệu lực.
            node = node.value
            accessor = None
            continue
        if isinstance(node, ast.Call):
            node = node.func
            continue
        return None, accessor


def references(query: str) -> tuple[list[tuple[str, str]], list[tuple[str, int]], int]:
    """`(tham chiếu cột, tham chiếu dòng theo vị trí, số index không phân loại được)`."""
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        return [], [], -1
    columns: list[tuple[str, str]] = []
    rows: list[tuple[str, int]] = []
    unknown = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        name, accessor = _root(node.value)
        if name is None or not name.startswith("df"):
            continue
        # `.loc[dòng, cột]` là trường hợp duy nhất mà một index mang cả hai trục.
        parts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        for position, part in enumerate(parts):
            if not isinstance(part, ast.Constant):
                unknown += 1
                continue
            value = part.value
            if isinstance(value, str):
                # Chuỗi ở khe đầu của `.loc` là nhãn dòng, mọi chỗ khác là tên cột.
                if accessor == "loc" and position == 0 and len(parts) > 1:
                    continue
                if accessor == "loc" and len(parts) == 1:
                    continue
                columns.append((name, value))
            elif isinstance(value, bool):
                unknown += 1
            elif isinstance(value, int) and accessor in {"iloc", "iat"}:
                if position == 0:
                    rows.append((name, value))
            else:
                unknown += 1
    return columns, rows, unknown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0, help="in mấy ví dụ mỗi nhóm lỗi")
    ap.add_argument("--json", help="ghi kết quả từng câu ra file JSON")
    args = ap.parse_args()

    records = []
    for line in RUN.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))

    tally: Counter[str] = Counter()
    by_solver: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    out: dict[str, dict] = {}
    for record in records:
        solution = record.get("solution") or {}
        query = str(solution.get("pandas_query") or "")
        solver = str(record.get("solver") or "?")
        if not query:
            tally["không có truy vấn"] += 1
            by_solver[solver]["không có truy vấn"] += 1
            continue
        evidence = list((record.get("diag") or {}).get("evidence_tables") or [])
        # `ordered_table_names` đánh số từ 1 theo đúng thứ tự này.
        frames: dict[str, object] = {}
        columns_of: dict[str, set] = {}
        nrows_of: dict[str, int] = {}
        for index, table_id in enumerate(evidence, start=1):
            try:
                frame = load_frame(table_id)
            except Exception:  # noqa: BLE001 - bảng không nạp được đã tính ở graph
                continue
            name = f"df{index}"
            frames[name] = table_id
            columns_of[name] = {str(c) for c in frame.columns}
            nrows_of[name] = len(frame)

        cols, rows, unknown = references(query)
        if unknown < 0:
            group = "không parse được"
        else:
            missing_var = [n for n, _ in cols + rows if n not in frames]
            bad_cols = [(n, c) for n, c in cols if n in frames and c not in columns_of[n]]
            bad_rows = [(n, i) for n, i in rows if n in frames and i >= nrows_of[n]]
            if missing_var:
                group = "biến lạ"
            elif bad_cols:
                # Cột đó có ở frame khác của cùng câu hay không quyết định cách sửa.
                borrowed = any(
                    any(c in other for name, other in columns_of.items() if name != n)
                    for n, c in bad_cols
                )
                group = "cột lạ: mượn từ df khác" if borrowed else "cột lạ: bịa hẳn"
            elif bad_rows:
                group = "dòng quá tầm"
            else:
                group = "ok"
            if group != "ok" and len(examples[group]) < args.show:
                examples[group].append(
                    f"q{record['id']} [{solver}] {query[:90]}\n"
                    f"      df có {sorted(frames)}"
                    + "".join(
                        f"\n      {n} = {frames[n]}  {nrows_of[n]} dòng"
                        f"  cột {sorted(columns_of[n])[:6]}"
                        for n in sorted(frames)
                    )
                )
        tally[group] += 1
        by_solver[solver][group] += 1
        out[str(record["id"])] = {"group": group, "solver": solver, "query": query}

    groups = ["ok", "cột lạ: mượn từ df khác", "cột lạ: bịa hẳn", "dòng quá tầm",
              "biến lạ", "không parse được", "không có truy vấn"]
    total = sum(tally.values())
    print(f"\n{total} câu, đọc từ {RUN.name}, không gọi LLM và không dùng nhãn\n")
    for group in groups:
        if tally[group]:
            print(f"  {group:<26}{tally[group]:>5}{tally[group] / total:>8.1%}")

    solvers = sorted(by_solver, key=lambda s: -sum(by_solver[s].values()))
    print(f"\n{'solver':<22}" + "".join(f"{g.split(':')[0][:9]:>11}" for g in groups[:5]))
    for solver in solvers:
        cells = "".join(f"{by_solver[solver][g]:>11}" for g in groups[:5])
        print(f"{solver:<22}{cells}")

    for group in groups:
        for line in examples[group]:
            print(f"\n  {group}\n    {line}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False,
                                              sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
