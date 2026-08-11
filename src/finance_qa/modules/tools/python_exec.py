"""Python execution and submission validation helpers."""
from __future__ import annotations

import ast
import contextlib
import io
import math

import pandas as pd

from finance_qa.modules.data.table_store import load_frame, source_csv, submission_csv_name

SAFE_GLOBALS = {
    "__builtins__": {
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "float": float, "int": int, "len": len,
        "list": list, "max": max, "min": min, "print": print, "range": range,
        "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
        "tuple": tuple, "zip": zip,
    },
    "pd": pd,
}


def query_names(query: str) -> set[str]:
    """Return free variable names read by a pandas query."""
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        tree = ast.parse(query)
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    known = set(SAFE_GLOBALS) | set(SAFE_GLOBALS["__builtins__"])
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    } - assigned - known


def run_query(query: str, frames: dict[str, pd.DataFrame]) -> float:
    """Evaluate an expression query, or execute statements that assign ``answer``."""
    namespace = dict(frames)
    try:
        result = eval(compile(query, "<query>", "eval"), SAFE_GLOBALS, namespace)
    except SyntaxError:
        exec(compile(query, "<query>", "exec"), SAFE_GLOBALS, namespace)
        if "answer" not in namespace:
            raise ValueError("multi-statement query must assign `answer`")
        result = namespace["answer"]

    if isinstance(result, (pd.Series, pd.DataFrame)):
        if result.size == 1:
            result = result.item()
        else:
            raise ValueError(
                f"query trả về {type(result).__name__} shape={result.shape} thay vì scalar; "
                f"dùng .iloc[0] hoặc .values[0] để lấy ô đơn"
            )
    elif hasattr(result, "item"):
        result = result.item()
    value = float(result)
    if not math.isfinite(value):
        raise ValueError(f"query returned non-finite {value!r}")
    return value


def exec_in_namespace(code: str, namespace: dict, include_stdout_on_error: bool = False) -> str:
    """Execute code in a persistent namespace and return stdout or an error string."""
    safe_builtins = {
        **SAFE_GLOBALS["__builtins__"],
        "print": print, "repr": repr, "type": type, "hasattr": hasattr,
        "getattr": getattr, "bool": bool, "isinstance": isinstance,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "IndexError": IndexError, "KeyError": KeyError, "AttributeError": AttributeError,
        "__import__": __import__,
    }
    namespace.setdefault("__builtins__", safe_builtins)
    namespace.setdefault("pd", SAFE_GLOBALS["pd"])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<repl>", "exec"), namespace)
        out = buf.getvalue().strip()
        return out if out else "(no output — use print() to inspect values)"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        if include_stdout_on_error:
            captured = buf.getvalue().strip()
            return f"{captured}\n{err}" if captured else err
        return err


def validate(item: dict, rel_tol: float = 1e-6) -> list[str]:
    """Validate submission item consistency."""
    errs: list[str] = []
    add = errs.append

    if not isinstance(item.get("id"), int):
        add("id phải là integer")
    if not isinstance(item.get("question"), str) or not item["question"].strip():
        add("question rỗng")

    docs = item.get("relevant_docs") or []
    tables = item.get("relevant_tables") or []
    evidence = item.get("evidence") or []
    query = item.get("pandas_query") or ""
    if not docs:
        add("relevant_docs rỗng")
    if not tables:
        add("relevant_tables rỗng")
    if not evidence:
        add("evidence rỗng")
    if not query.strip():
        add("pandas_query rỗng")

    table_ids = set()
    for table_id in tables:
        if "|" not in table_id:
            add(f"relevant_tables sai định dạng: {table_id!r}")
            continue
        doc = table_id.rsplit("|", 1)[0]
        if doc not in docs:
            add(f"table {table_id} thuộc doc không có trong relevant_docs")
        if not source_csv(table_id).exists():
            add(f"table {table_id} không tồn tại trong corpus")
        table_ids.add(table_id)

    frames: dict[str, pd.DataFrame] = {}
    declared: set[str] = set()
    for ev in evidence:
        var, path = ev.get("variable", ""), ev.get("csv_path", "")
        if not var.isidentifier():
            add(f"variable {var!r} không hợp lệ")
        if var in declared:
            add(f"variable {var!r} bị trùng")
        declared.add(var)
        if not path.startswith("data/"):
            add(f"csv_path phải bắt đầu bằng 'data/': {path!r}")
        name = path.split("/")[-1]
        match = [table_id for table_id in table_ids if submission_csv_name(table_id) == name]
        if not match:
            add(f"evidence {name!r} không khớp bất kỳ relevant_tables nào")
            continue
        try:
            frames[var] = load_frame(match[0])
        except Exception as exc:  # noqa: BLE001 - reported as a validation error
            add(f"không đọc được CSV của {match[0]}: {exc}")

    used = query_names(query) if query.strip() else set()
    for name in sorted(used - declared):
        add(f"query dùng {name!r} nhưng không có evidence tương ứng")
    if used:
        for name in sorted(declared - used):
            add(f"evidence khai báo {name!r} nhưng query không dùng")

    if errs:
        return errs
    try:
        value = run_query(query, frames)
    except Exception as exc:  # noqa: BLE001 - the whole point is to report it
        return [f"query chạy lỗi: {type(exc).__name__}: {exc}"]

    answer = item.get("answer")
    if not isinstance(answer, (int, float)) or isinstance(answer, bool):
        add(f"answer phải là số, đang là {answer!r}")
    elif not math.isclose(float(answer), value, rel_tol=rel_tol):
        add(f"answer={answer!r} khác kết quả chạy query={value!r}")
    return errs

__all__ = [
    "SAFE_GLOBALS",
    "exec_in_namespace",
    "query_names",
    "run_query",
    "validate",
]
