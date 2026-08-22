"""Đo `repair_shifted_multilevel_header` trên toàn bộ 146k bảng, cũ so với mới.

Sàng ứng viên bằng hai dòng đầu của CSV (rẻ), rồi mới đọc đủ bằng pandas. Với mỗi ứng
viên, chạy cả bản cũ (copy từ git HEAD, để so) và bản mới, rồi đếm: bao nhiêu bảng mỗi
bản nhận, bao nhiêu tên cột trùng nhau sau khi sửa, bao nhiêu cột `Unnamed:` còn lại.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_multilevel_header.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from finance_qa.modules.tools.dataframe import (
    parse_number,
    repair_shifted_bank_header,
    repair_shifted_multilevel_header,
)

TABLES = Path("data/tables")


def repair_old(df: pd.DataFrame) -> pd.DataFrame:
    """Bản ở git HEAD, giữ nguyên để so sánh."""
    if df.empty or len(df.columns) < 5:
        return df
    cols = [str(col) for col in df.columns]
    first = [str(value).strip() for value in df.iloc[0]]
    subheaders = [value for value in first if value]
    if len(subheaders) < 2:
        return df
    if first[: len(subheaders)] != subheaders or any(first[len(subheaders) :]):
        return df
    if any(parse_number(value) is not None for value in subheaders):
        return df

    group_start = len(cols) - len(subheaders) - 1
    if group_start < 1 or group_start + 1 >= len(cols):
        return df
    group_name = cols[group_start]
    final_name = cols[group_start + 1]
    if not (
        "số cuối" in group_name.casefold()
        and "số đầu" in final_name.casefold()
        and all(col.startswith("Unnamed:") for col in cols[group_start + 2 :])
    ):
        return df

    leaf_columns = [*cols[:group_start], *subheaders, final_name]
    if len({column.casefold() for column in leaf_columns}) == len(leaf_columns):
        repaired_columns = leaf_columns
    else:
        repaired_columns = [
            *cols[:group_start],
            *(f"{group_name} | {subheader}" for subheader in subheaders),
            final_name,
        ]
    if len(repaired_columns) != len(cols):
        return df
    out = df.iloc[1:].reset_index(drop=True).copy()
    out.columns = repaired_columns
    return out


def candidate(path: Path) -> bool:
    """Hai dòng đầu: header có ít nhất 5 cột, dòng 1 toàn chữ và dồn về trái."""
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(zip(range(2), csv.reader(fh)))
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    if len(rows) < 2:
        return False
    header, first = rows[0][1], rows[1][1]
    if len(header) < 5:
        return False
    cells = [c.strip() for c in first]
    filled = [c for c in cells if c]
    if len(filled) < 2 or cells[: len(filled)] != filled:
        return False
    return all(parse_number(c) is None for c in filled)


def audit(df: pd.DataFrame, out: pd.DataFrame) -> str:
    if out.columns.equals(df.columns) and len(out) == len(df):
        return "bỏ qua"
    names = [str(c) for c in out.columns]
    if len({n.casefold() for n in names}) != len(names):
        return "sửa nhưng TRÙNG TÊN"
    if any(n.startswith("Unnamed:") for n in names[1:]):
        return "sửa nhưng còn Unnamed"
    return "sửa sạch"


def main() -> int:
    paths = sorted(TABLES.glob("*/table_*.csv"))
    print(f"{len(paths)} bảng, đang sàng ứng viên...", flush=True)
    cands = [p for p in paths if candidate(p)]
    print(f"{len(cands)} ứng viên ({len(cands)/len(paths):.1%})", flush=True)

    old_c: Counter[str] = Counter()
    new_c: Counter[str] = Counter()
    flipped: list[str] = []
    for i, p in enumerate(cands):
        if i % 2000 == 0:
            print(f"  {i}/{len(cands)}", flush=True)
        try:
            raw = pd.read_csv(p, dtype=str, keep_default_na=False)
        except Exception:
            continue
        base = repair_shifted_bank_header(raw)
        o, n = audit(base, repair_old(base)), audit(base, repair_shifted_multilevel_header(base))
        old_c[o] += 1
        new_c[n] += 1
        if o != "bỏ qua" and n == "bỏ qua":
            flipped.append(f"{p.parent.name}|{p.name}")

    for name, c in (("cũ", old_c), ("mới", new_c)):
        total = sum(v for k, v in c.items() if k != "bỏ qua")
        print(f"\n{name}: bắt {total} bảng")
        for k, v in c.most_common():
            print(f"  {k:<24} {v}")
    print(f"\ncũ sửa, mới bỏ qua: {len(flipped)}")
    for f in flipped[:20]:
        print("  ", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
