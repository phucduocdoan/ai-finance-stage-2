"""Cho các fact solver mang theo biểu thức pandas đọc thẳng ô trong CSV.

Vấn đề. `execute_plan` tính đáp án bằng số học Python trên các `Fact` lấy từ
`long_format.parquet`, rồi ghi `pandas_query = repr(answer)`. Đó là một hằng số.
Luật cuộc thi (`final_submission.md`): "Không được gán cứng, mã hóa hoặc lưu sẵn
kết quả dưới bất kỳ hình thức nào. Các câu hỏi vi phạm quy định này sẽ không được
tính điểm." Ví dụ luật đưa ra chính là `result = 2.06`. Trên lần chạy 31/08 có
106/1012 câu như vậy, và cả 106 câu cũng ship `evidence: []`.

Cách sửa. Không viết lại số học thành cây biểu thức. Thay vào đó `Num` là một
`float` mang thêm chuỗi biểu thức sinh ra nó, và các toán tử `+ - * /`, `abs`,
`round` tự nối chuỗi. Mọi công thức có sẵn trong `execute.py` chạy y nguyên, chỉ
khác là kết quả cuối biết mình được tính từ đâu.

`expr=None` là chất độc lan truyền: fact nào không định vị được ô thì mọi phép
tính chạm vào nó cũng mất biểu thức, và `execute_plan` quay về hằng số cũ. Thà
mất một câu còn hơn ship biểu thức đọc nhầm ô.

Định vị ô. Fact giữ `table_id`, `ma_so`, `label`, `period`. Trong CSV nộp bài,
`period` là tên cột, `ma_so` nằm ở cột "Mã số", `label` ở cột đầu. Hàng khớp còn
phải có giá trị trùng `fact.value`, nếu không thì coi như không định vị được.

Dạng biểu thức là `dfN.iloc[<hàng>]["<cột>"]`, đúng dạng codegen vẫn sinh, nên
`build_submission.make_query_exec_safe` chấm nó bằng cùng một đường.

Đo trên lần chạy 31/08: 463/498 fact định vị được, 90/106 câu định vị được toàn
bộ fact của nó.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from finance_qa.modules.data.table_store import load_frame


class Num(float):
    """Một `float` nhớ biểu thức pandas sinh ra nó; `expr=None` là không truy nguyên được."""

    __slots__ = ("expr",)

    def __new__(cls, value: Any, expr: str | None = None) -> "Num":
        obj = super().__new__(cls, float(value))
        obj.expr = expr
        return obj

    def __repr__(self) -> str:
        return f"Num({float(self)!r}, {self.expr!r})"

    def __add__(self, other): return _combine(self, other, "+")
    def __radd__(self, other): return _combine(other, self, "+")
    def __sub__(self, other): return _combine(self, other, "-")
    def __rsub__(self, other): return _combine(other, self, "-")
    def __mul__(self, other): return _combine(self, other, "*")
    def __rmul__(self, other): return _combine(other, self, "*")
    def __truediv__(self, other): return _combine(self, other, "/")
    def __rtruediv__(self, other): return _combine(other, self, "/")

    def __neg__(self) -> "Num":
        return Num(-float(self), None if self.expr is None else f"-({self.expr})")

    def __abs__(self) -> "Num":
        return Num(abs(float(self)), None if self.expr is None else f"abs({self.expr})")

    def __round__(self, ndigits: int | None = None) -> "Num":
        value = round(float(self), ndigits) if ndigits is not None else round(float(self))
        if self.expr is None:
            return Num(value, None)
        return Num(value, f"round({self.expr}, {ndigits or 0})")


def expression(value: Any) -> str | None:
    """Biểu thức của một toán hạng: hằng số literal thì trả về chính nó."""
    if isinstance(value, Num):
        return value.expr
    try:
        return repr(float(value))
    except (TypeError, ValueError):
        return None


_OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
}


def _combine(left: Any, right: Any, symbol: str) -> Num:
    value = _OPS[symbol](float(left), float(right))
    a, b = expression(left), expression(right)
    if a is None or b is None:
        return Num(value, None)
    return Num(value, f"({a} {symbol} {b})")


@lru_cache(maxsize=512)
def _frame(table_id: str):
    try:
        return load_frame(table_id)
    except Exception:
        return None


def _same_ma_so(cell: Any, wanted: str) -> bool:
    try:
        return math.isclose(float(cell), float(wanted), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return str(cell).strip() == str(wanted).strip()


@lru_cache(maxsize=8192)
def _locate(table_id: str, ma_so: str | None, label: str | None, period: str | None, value: float):
    """`(vị trí hàng, tên cột)` của ô mang đúng `value`, hoặc None."""
    df = _frame(table_id)
    if df is None or period is None or period not in df.columns:
        return None
    column = df[period].tolist()

    def matches(pos: int) -> bool:
        try:
            return math.isclose(float(column[pos]), value, rel_tol=1e-9)
        except (TypeError, ValueError):
            return False

    if ma_so is not None and "Mã số" in df.columns:
        for pos, cell in enumerate(df["Mã số"].tolist()):
            if _same_ma_so(cell, ma_so) and matches(pos):
                return pos, period
    if label:
        wanted = str(label).strip()
        for pos, cell in enumerate(df[df.columns[0]].tolist()):
            if str(cell).strip() == wanted and matches(pos):
                return pos, period
    return None


def cell_expression(fact: Any, variable: str) -> str | None:
    """`dfN.iloc[r]["col"]` cho một `Fact`, hoặc None nếu không định vị được ô."""
    row = fact.row
    ma_so = row.get("ma_so")
    found = _locate(
        fact.table_id,
        None if ma_so is None else str(ma_so),
        None if row.get("label") is None else str(row.get("label")),
        None if row.get("period") is None else str(row.get("period")),
        float(fact.value),
    )
    if found is None:
        return None
    position, column = found
    return f"{variable}.iloc[{position}][{column!r}]"


__all__ = ["Num", "cell_expression", "expression"]
