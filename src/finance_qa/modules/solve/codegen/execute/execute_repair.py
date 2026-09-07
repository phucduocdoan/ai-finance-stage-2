"""Describe an execution failure so the repair call can act on it.

Part of the `codegen.execute` facade: see `execute/__init__.py`.
"""
from __future__ import annotations

import ast
import re
from typing import Mapping, Sequence

import pandas as pd

from finance_qa.modules.solve.codegen.codegen import CODEGEN_SYSTEM
from finance_qa.modules.solve.common.solution import PandasSolution

MAX_REPAIRS = 2

# Control-arm temperature. Not 0.0, because without `repair_history` the repair
# prompt differs from the generation prompt by one appended error line, so at
# temperature 0 the model re-emits the identical query: all 8 questions that died
# on the 60-question gold set logged the *same* error twice more and never varied.
#
# That reading of the symptom was wrong. The cause is not sampling: `_arepair`
# built a fresh two-message prompt on every attempt, so attempt 2 never saw
# attempt 1's query or error and had no way to know it was repeating itself.
# Measured on the gold94 runs, noise at 0.3 does not fix it — of the questions
# that entered the loop, the error was byte-identical across every attempt for 5
# of 8 (base1), 5 of 7 (base2) and 4 of 7 (fanout), q381 and q396 three times over.
REPAIR_TEMPERATURE = 0.3

# History arm. With the attempts block below, the prompt genuinely changes between
# attempts — it grows by one failed query each time — so the reason to inject noise
# is gone and the retry can be as reproducible as the first call.
HISTORY_TEMPERATURE = 0.0

_DF_VAR = re.compile(r"\bdf\d+\b")

REPAIR_SYSTEM = CODEGEN_SYSTEM + """

The previous query failed to execute. Fix the pandas query. Do not change the
evidence table you read from. The error is followed by the true shape and the
true column names of every dataframe the query touched — the fixed query must
index by a name from that list, copied character for character."""


def _blank_cell_error(exc: Exception) -> bool:
    """Is this the failure where the query found a cell holding no number?

    Three shapes of the same mistake: the cell is empty (`nan`), the cell holds
    text (`'V.19.'`, `'Đang hoạt động'`, `'1,23%'`), or arithmetic ran against a
    column that is text. Naming the column list back at the model does not help
    here — the column it used exists, it is the *cell* that is unusable.
    """
    if isinstance(exc, (TypeError, ValueError)):
        return any(
            token in str(exc)
            for token in ("non-finite", "could not convert string to float",
                          "did not contain a loop", "not supported for the input types",
                          "unsupported operand")
        )
    return False


def _row_dump(solution: PandasSolution, frames: Mapping[str, pd.DataFrame]) -> str:
    """The row the model said it was aiming at, cell by cell.

    This is the single largest hole in the repair loop: over a 1012-question run
    `ValueError: query returned non-finite nan` was logged 91 times, more than
    every other execution error combined, and it names neither the row nor the
    value. The repair had nothing to work from and re-emitted the query it had
    just written — measured, the error was byte-identical on all three attempts
    for 56 of the 79 questions that ended at 0.0.
    """
    frame = frames.get(solution.table_variable)
    if frame is None:
        return ""
    try:
        row = frame.iloc[int(str(solution.target_row).strip())]
    except (TypeError, ValueError, IndexError):
        return ""  # a label-indexed or multi-cell query: the dump would be a guess
    cells = [
        f"{str(col)!r}={'(rỗng)' if pd.isna(val) or not str(val).strip() else repr(str(val).strip())}"
        for col, val in row.items()
    ]
    return (
        f"Hàng bạn đã đọc, {solution.table_variable}.iloc[{solution.target_row}], "
        f"chứa: {'; '.join(cells)}"
    )


def describe_error(
    exc: Exception,
    query: str,
    frames: Mapping[str, pd.DataFrame],
    solution: PandasSolution | None = None,
) -> str:
    """The failure as the repair call needs to see it.

    `str(exc)` alone is what made the loop a no-op: a `KeyError` arrives as the
    bare string `'2018'` — no exception type, no indication that the problem is a
    column name, no list of the names that do exist. Every repair got that, and
    every repair answered with the query it had just written.
    """
    lines = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, KeyError):
        lines.append("(không có cột hay nhãn nào mang tên này)")
    if solution is not None and _blank_cell_error(exc):
        dump = _row_dump(solution, frames)
        if dump:
            lines.append(dump)
        lines.append(
            "Ô bạn đọc không chứa số. Chọn ô khác: cùng chỉ tiêu nhưng ở cột số "
            "liệu khác, hoặc hàng khác mang đúng nhãn chỉ tiêu mà câu hỏi cần. "
            "Không ép kiểu, không bịa số."
        )
    for var in sorted(set(_DF_VAR.findall(query))):
        frame = frames.get(var)
        if frame is None:
            lines.append(f"{var}: biến này không tồn tại")
            continue
        columns = ", ".join(repr(str(col)) for col in frame.columns)
        lines.append(
            f"{var}: {frame.shape[0]} hàng x {frame.shape[1]} cột; "
            f"chỉ có các cột [{columns}]; vị trí hàng hợp lệ 0..{frame.shape[0] - 1}"
        )
    return "\n".join(lines)


def _attempts_block(attempts: Sequence[tuple[str, str]]) -> str:
    """Every query already tried and why it failed, most recent one in full.

    The earlier entries keep only the first line of `describe_error` — the rest of
    it is the shape and column list of the same dataframes, which does not change
    between attempts, so repeating it three times would spend prompt budget on
    dilution. What the model is missing is the *queries it has already spent*, and
    those are one line each.
    """
    lines = []
    for i, (query, detail) in enumerate(attempts, 1):
        body = detail if i == len(attempts) else (detail.splitlines() or [""])[0]
        lines.append(f"Lần {i} — truy vấn đã chạy:\n{query or '(rỗng)'}\nLỗi:\n{body}")
    lines.append(
        "Tất cả các truy vấn trên đã chạy và đều lỗi. Đừng nộp lại bất kỳ truy vấn "
        "nào trong số đó — hãy đọc một ô khác."
    )
    return "\n\n".join(lines)


def multiplies_by_zero(query: str) -> bool:
    """Query nhân một ô với 0 rồi cộng hằng số vào: gán cứng đội lốt đọc ô.

    Dạng codegen tự nghĩ ra khi nó biết đáp án nhưng không tìm được ô nào cho ra
    đáp án đó, ví dụ `(df2.iloc[9]["Cộng"]) * 0 + 2020`. Query chạy được, đọc một
    ô thật, và trả về đúng hằng số đã viết sẵn. Luật (`final_submission.md`) cấm
    gán cứng kết quả, nên đây vẫn là câu bị chấm 0.
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
