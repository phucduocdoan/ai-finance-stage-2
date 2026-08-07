"""Multi-step REPL fallback using a single run_code tool.

The LLM may batch multiple run_code calls per turn (Qwen3 parallel tool use).
We execute ALL of them sequentially so the namespace accumulates correctly.
Termination: any code assigns result = <float> in the shared namespace.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request

import pandas as pd

from finance_qa.execution.query import exec_in_namespace, query_names, submission_csv_name
from finance_qa.retrieval.judge import ENDPOINT, MODEL, _API_KEY

# Set REPL_BACKEND=gemini to route REPL calls through Gemini instead of local vLLM
_REPL_BACKEND = os.environ.get("REPL_BACKEND", "vllm")
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
_GEMINI_MODEL = "gemini-2.5-flash"

MAX_REPL_STEPS = 10

_RUN_CODE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": (
            "Execute Python/pandas code in a persistent namespace. "
            "All DataFrames are pre-loaded. Use print() to inspect intermediate values."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
}

_TOOLS = [_RUN_CODE_TOOL]

_SYSTEM_TMPL = """\
Bạn là trợ lý tính toán tài chính. Dùng run_code() để tính toán, gán result = <số> khi xong.

Câu hỏi: {question}

{planner_context}Namespace đã có sẵn: {df_vars}, pd, np.
TUYỆT ĐỐI KHÔNG viết "import ..." — sẽ gây ImportError ngay lập tức.

Schema các DataFrame:
{schema_blocks}

Hàm tiện ích có sẵn:
  get_val(df, keyword, col=None) → tìm dòng chứa keyword (case-insensitive), trả giá trị từ col
  Ví dụ: get_val(df1, 'Lợi nhuận sau thuế', 'Năm 2024')  → float
         get_val(df2, 'lưu chuyển tiền thuần', 'Năm nay') → float

Quy tắc:
- KHÔNG import. pd, np, get_val, {df_vars} đã có sẵn.
- Dùng get_val() để lấy giá trị — KHÔNG tự viết hàm filter.
- Dùng print() để kiểm tra giá trị trung gian trước khi tính.
- Khi get_val trả None: thử keyword ngắn hơn hoặc col khác.
- Suy đơn vị từ độ lớn (>1e9→VND tỷ, ~1e6→triệu), đổi đúng theo câu hỏi.
- result là biến DÀNH RIÊNG cho đáp án cuối — KHÔNG dùng result cho biến trung gian hay counter.
  Dùng tên khác cho biến tạm: total, ratio, val, max_val, v.v.
- Gán result = <số> chỉ khi đã có đáp án hoàn chỉnh."""


_SCHEMA_LABEL_LIMIT = 30   # max unique string values to show inline
_SCHEMA_BLOCK_CHARS = 1200  # cap per table block to avoid 400 errors


def _schema_block(var: str, table_id: str, df: pd.DataFrame) -> str:
    cols = df.columns.tolist()
    dtypes = ", ".join(str(df[c].dtype) for c in cols)
    lines = [
        f"### {var}  ({table_id})",
        f"Columns: {cols}",
        f"Dtypes:  {dtypes}",
        f"Rows: {len(df)}",
    ]
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            vals = df[c].dropna().astype(str).str.strip()
            uniq = [v for v in vals.unique() if v and v.lower() != "nan"]
            if not uniq:
                continue
            if len(uniq) <= _SCHEMA_LABEL_LIMIT:
                lines.append(f"  '{c}' labels: {uniq}")
            else:
                lines.append(
                    f"  '{c}': {len(uniq)} unique — "
                    f"print(list(df['{c}'].unique())) để xem"
                )
    block = "\n".join(lines)
    if len(block) > _SCHEMA_BLOCK_CHARS:
        block = block[: _SCHEMA_BLOCK_CHARS] + "\n  ...(truncated)"
    return block


def _llm_tool_call(messages: list[dict]) -> dict:
    """POST to vLLM or Gemini with run_code tool. Returns the raw assistant message dict."""
    if _REPL_BACKEND == "gemini":
        payload = {
            "model": _GEMINI_MODEL,
            "messages": messages,
            "tools": _TOOLS,
            "tool_choice": "required",
            "max_tokens": 4096,
        }
        endpoint = _GEMINI_ENDPOINT
        key = _GEMINI_KEY
    else:
        payload = {
            "model": MODEL,
            "messages": messages,
            "tools": _TOOLS,
            "tool_choice": "required",
            "max_tokens": 4096,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        endpoint = ENDPOINT
        key = _API_KEY

    data = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(endpoint, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    return body["choices"][0]["message"]


def _evidence_from_codes(
    code_list: list[str],
    names: dict[str, str],
) -> list[dict[str, str]]:
    all_code = "\n".join(code_list)
    try:
        used = query_names(all_code)
    except SyntaxError:
        used = set(names.keys())
    return [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
        if var in used
    ] or [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in list(names.items())[:1]
    ]


def repl_generate(
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    planner_error: str = "",
    last_plan: dict | None = None,
) -> dict:
    """Tool-calling REPL: LLM runs code step-by-step, terminates via result=<float>."""
    import numpy as np

    def _safe_print(*args, **kwargs):
        safe_args = tuple(a.tolist() if hasattr(a, "tolist") else a for a in args)
        print(*safe_args, **kwargs)

    def _get_val(df: pd.DataFrame, keyword: str, col: str | None = None):
        """Find first row where any string column contains keyword, return value from col."""
        for c in df.columns:
            if df[c].dtype == object:
                mask = df[c].astype(str).str.contains(keyword, na=False, case=False)
                if mask.any():
                    rows = df[mask]
                    if col and col in df.columns:
                        return rows[col].values[0]
                    for vc in df.columns:
                        if pd.api.types.is_numeric_dtype(df[vc]):
                            return rows[vc].values[0]
        return None

    namespace: dict = {**frames, "pd": pd, "np": np, "print": _safe_print, "get_val": _get_val}
    code_history: list[str] = []

    blocks = [_schema_block(var, names[var], frames[var]) for var in frames]
    # Hard cap on total schema to prevent HTTP 400 for questions with many tables.
    _TOTAL_SCHEMA_CAP = 5000
    total = sum(len(b) for b in blocks)
    if total > _TOTAL_SCHEMA_CAP:
        ratio = _TOTAL_SCHEMA_CAP / total
        blocks = [b[: max(200, int(len(b) * ratio))] for b in blocks]
    schema_blocks = "\n\n".join(blocks)
    df_vars = ", ".join(frames.keys())
    planner_ctx = f"Planner đã thử nhưng gặp lỗi: {planner_error[:400]}\n\n" if planner_error else ""

    messages: list[dict] = [
        {
            "role": "system",
            "content": _SYSTEM_TMPL.format(
                question=question,
                schema_blocks=schema_blocks,
                df_vars=df_vars,
                planner_context=planner_ctx,
            ),
        },
        {
            "role": "user",
            "content": "Tính toán và gán result = <đáp án cuối> khi xong.",
        },
    ]

    for step in range(MAX_REPL_STEPS):
        try:
            asst = _llm_tool_call(messages)
        except Exception as exc:
            return _fail(code_history, names, planner_error, f"LLM error step {step}: {exc}")

        messages.append(asst)

        tool_calls = asst.get("tool_calls") or []
        if not tool_calls:
            break

        # Execute ALL run_code calls in this turn sequentially — namespace accumulates.
        # LLM may batch multiple calls; that's fine, we run them all and check result after.
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (KeyError, json.JSONDecodeError):
                args = {}

            code = args.get("code", "").strip()
            if code:
                # Strip import lines — pd/np/dfs already in namespace; __import__ blocked
                clean = "\n".join(
                    ln for ln in code.splitlines()
                    if not ln.lstrip().startswith("import ") and not ln.lstrip().startswith("from ")
                ).strip()
                code_history.append(clean or code)
                output = exec_in_namespace(clean or code, namespace)
            else:
                output = "(empty code)"

            if len(output) > 2000:
                output = output[:2000] + "\n...(truncated)"

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": output,
            })

        # Termination: any code in this turn assigned result = <scalar>
        raw = namespace.get("result")
        if raw is not None:
            try:
                answer = float(raw)
                # Skip result=0: LLM often initialises counters with result=0 before loops.
                # Financial answers are virtually never exactly zero.
                if math.isfinite(answer) and answer != 0.0:
                    return _success(answer, code_history, names, planner_error, step + 1)
            except (TypeError, ValueError):
                pass
            del namespace["result"]  # bad value or zero → clear and keep going

        # Sliding window: keep system + user + last 10 messages
        if len(messages) > 12:
            messages = messages[:2] + messages[-10:]

    return _fail(code_history, names, planner_error, f"REPL: no result after {MAX_REPL_STEPS} steps")


def _success(
    answer: float,
    code_history: list[str],
    names: dict[str, str],
    planner_error: str,
    steps: int,
) -> dict:
    evidence = _evidence_from_codes(code_history, names)
    used_vars = [e["variable"] for e in evidence]
    df_ref = "; ".join(f"_ = {v}" for v in used_vars)
    pandas_query = f"{df_ref}\nanswer = {repr(answer)}" if df_ref else f"answer = {repr(answer)}"
    return {
        "pandas_query": pandas_query,
        "answer": answer,
        "evidence": evidence,
        "error": "",
        "repl_steps": steps,
        "planner": False,
        "repl": True,
        "planner_error": planner_error,
    }


def _fail(
    code_history: list[str],
    names: dict[str, str],
    planner_error: str,
    error: str,
) -> dict:
    evidence = _evidence_from_codes(code_history, names)
    used_vars = [e["variable"] for e in evidence]
    df_ref = "; ".join(f"_ = {v}" for v in used_vars)
    pandas_query = f"{df_ref}\nanswer = 0.0" if df_ref else "answer = 0.0"
    return {
        "pandas_query": pandas_query,
        "answer": 0.0,
        "evidence": evidence,
        "error": error,
        "repl_steps": len(code_history),
        "planner": False,
        "repl": True,
        "planner_error": planner_error,
    }
