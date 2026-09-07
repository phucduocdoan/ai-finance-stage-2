"""Bắt các `pandas_query` gán cứng đáp án trong một file nộp.

Luật (`final_submission.md`): "Không được gán cứng, mã hóa hoặc lưu sẵn kết quả
dưới bất kỳ hình thức nào. Các câu hỏi vi phạm quy định này sẽ không được tính
điểm." Ví dụ luật đưa ra là `result = 2.06` và `result = 1.03 * 2`.

Bắt ba dạng, đều là kiểm tra cú pháp trên cây AST chứ không so với đáp án nào:

1. Truy vấn rỗng. Không đọc ô nào thì đáp án chỉ có thể từ chỗ khác mà ra.
2. Truy vấn chỉ gồm hằng số và số học trên hằng số, không chạm vào frame nào.
   `2.06` và `1.03 * 2` đều rơi vào đây.
3. Truy vấn nhân một ô với 0 rồi cộng hằng số, ví dụ `df2.iloc[9]["Cộng"] * 0 + 2020`.
   Nó chạy được và đọc một ô thật, nhưng trả về đúng hằng số đã viết sẵn. Đây là
   dạng codegen tự nghĩ ra khi nó biết đáp án mà không tìm được ô nào cho ra đáp án đó.

Truy vấn sai cú pháp KHÔNG bị tính là vi phạm: nó là một câu trả lời sai, không
phải một đáp án gán cứng. Script báo riêng để khỏi lẫn hai thứ.

Dùng:
    .venv_bge/bin/python scripts/pipeline/check_no_hardcode.py output/submission_v36.zip
"""
from __future__ import annotations

import ast
import json
import sys
import zipfile
from pathlib import Path


def reads_a_frame(tree: ast.AST) -> bool:
    """Biểu thức có chạm vào một DataFrame nào không.

    `Subscript` (`df.iloc[9]`, `df["Cộng"]`) và `Attribute` (`df.iloc`) là đọc dữ
    liệu thật. `Call` không được tính: `round(...)` và `float(...)` cũng là `Call`,
    nên `round(float(0.59), 2)` sẽ lọt qua nếu tính cả `Call` -- đúng kẽ hở BTC bắt
    được trên các câu 368/390/694/719/770/778/959.
    """
    return any(isinstance(node, (ast.Subscript, ast.Attribute)) for node in ast.walk(tree))


def multiplies_by_zero(tree: ast.AST) -> bool:
    """Có phép nhân với hằng số 0, tức mọi ô đọc được đều bị triệt tiêu."""
    return any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mult)
        and any(
            isinstance(side, ast.Constant) and side.value == 0
            for side in (node.left, node.right)
        )
        for node in ast.walk(tree)
    )


def violation(query: str) -> str | None:
    """Lý do câu này vi phạm, hoặc None nếu không."""
    text = query.strip()
    if not text:
        return "truy vấn rỗng"
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None  # sai cú pháp là trả lời sai, không phải gán cứng
    if not reads_a_frame(tree):
        return "chỉ gồm hằng số, không đọc ô nào"
    if multiplies_by_zero(tree):
        return "nhân ô với 0 nên kết quả là hằng số"
    return None


def items_of(path: Path) -> list[dict]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            name = next(n for n in archive.namelist() if n.endswith("submission.json"))
            return json.loads(archive.read(name))
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    items = items_of(path)

    bad: list[tuple[object, str, str]] = []
    unparsable: list[object] = []
    for item in items:
        query = str(item.get("pandas_query") or "")
        reason = violation(query)
        if reason:
            bad.append((item.get("id"), reason, query))
        elif query.strip():
            try:
                ast.parse(query, mode="eval")
            except SyntaxError:
                unparsable.append(item.get("id"))

    if unparsable:
        print(f"{len(unparsable)} câu sai cú pháp (trả lời sai, không vi phạm luật): {unparsable}")
    if not bad:
        print(f"sạch: {len(items)} câu, 0 câu gán cứng đáp án")
        return 0
    print(f"VI PHẠM: {len(bad)}/{len(items)} câu gán cứng đáp án")
    for qid, reason, query in bad:
        print(f"  {qid}: {reason} -- {query[:80]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
