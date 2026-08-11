"""Multi-step REPL fallback using a single run_code tool.

The LLM may batch multiple run_code calls per turn (Qwen3 parallel tool use).
We execute ALL of them sequentially so the namespace accumulates correctly.
Termination: any code assigns result = <float> in the shared namespace.
"""

from __future__ import annotations

import json
import math
import os

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from finance_qa.core.http import client, run_sync
from finance_qa.core.llm import API_KEY, ENDPOINT, MODEL, get_chat_model
from finance_qa.modules.codegen.prompts import REPL_SYSTEM
from finance_qa.modules.data.canonical import canonical_frame, canonical_schema_block, _get_table_meta
from finance_qa.modules.tools.python_exec import exec_in_namespace, query_names
from finance_qa.modules.data.table_store import submission_csv_name

# Set REPL_BACKEND=gemini to route REPL calls through Gemini instead of local vLLM
_REPL_BACKEND = os.environ.get("REPL_BACKEND", "vllm")
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
_GEMINI_MODEL = "gemini-2.5-flash"

MAX_REPL_STEPS = 10
_REPL_TRACE = os.environ.get("REPL_TRACE", "") not in ("", "0")
_LANGCHAIN_REPL_MAX_STEPS = 10
_LANGCHAIN_REPL_TEMPERATURE = 0.7
_LANGCHAIN_REPL_MAX_TOKENS = 8192
_LANGCHAIN_REPL_OUTPUT_CAP = 2000
_LANGCHAIN_REPL_TOTAL_SCHEMA_CAP = 12000

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

{planner_context}Namespace đã có sẵn: {df_vars}, pd, np, canonical, get_metric.
TUYỆT ĐỐI KHÔNG viết "import ..." — sẽ gây ImportError ngay lập tức.

Schema các DataFrame:
{schema_blocks}

Hàm tiện ích có sẵn:
  get_metric(metric_id, year, ticker=None) → tìm giá trị tài chính qua TẤT CẢ df, filter theo ticker nếu cần
  Ví dụ: get_metric("total_debt", 2022)          → float  (tìm trong tất cả df)
         get_metric("equity", 2022, "FPT")        → float  (chỉ df của FPT)
         get_metric("net_profit", 2021)           → float  (mã 60 = LNST)
  Pattern multi-year (L6): {{
    de = {{yr: get_metric("total_debt", yr) / get_metric("equity", yr)
           for yr in range(2016, 2021)
           if get_metric("total_debt", yr) and get_metric("equity", yr)}}
    max_yr = max(de, key=de.get)
  }}
  get_val(df, keyword, col=None) → tìm dòng chứa keyword (case-insensitive), trả giá trị từ col
  Ví dụ: get_val(df1, 'Lợi nhuận sau thuế', 'Năm 2024')  → float

Công thức VAS thường gặp (metric_id trong canonical):
  D/E       = total_debt / equity
  ROE       = net_profit / equity
  ROA       = net_profit / total_assets
  Lãi vay   = (profit_before_tax + abs(interest_expense)) / abs(interest_expense)
  Gross GM  = gross_profit / net_revenue
  Current   = current_assets / short_term_debt
  Lưu ý: interest_expense trong canonical là số ÂM (chi phí) → dùng abs()

Quy tắc:
- KHÔNG import. pd, np, get_val, get_metric, canonical, {df_vars} đã có sẵn.
- Với balance_sheet/income_statement/cash_flow: ưu tiên get_metric() thay vì get_val().
- Multi-year/multi-company: dùng get_metric() để aggregate, không cần biết df nào chứa gì.
- Dùng get_val() cho note tables hoặc khi metric_id không có trong canonical.
- Dùng print() để kiểm tra giá trị trung gian trước khi tính.
- Khi get_val trả None: thử keyword ngắn hơn hoặc col khác.
- Suy đơn vị từ độ lớn (>1e9→VND tỷ, ~1e6→triệu), đổi đúng theo câu hỏi.
- result là biến DÀNH RIÊNG cho đáp án cuối — KHÔNG dùng result cho biến trung gian hay counter.
  Dùng tên khác cho biến tạm: total, ratio, val, max_val, v.v.
- Gán result = <số> chỉ khi đã có đáp án hoàn chỉnh."""


_SCHEMA_LABEL_LIMIT = 30   # max unique string values to show inline
_SCHEMA_BLOCK_CHARS = 1200  # cap per table block to avoid 400 errors


def _schema_block(var: str, table_id: str, df: pd.DataFrame) -> str:
    canonical = canonical_schema_block(var, table_id, df)
    if canonical is not None:
        return canonical
    tmeta = _get_table_meta(table_id)
    stype = tmeta.get("statement_type") or "note"
    # Non-canonical tables: explicitly tell LLM to use get_val(), NOT get_metric()
    note_hint = " [NOTE — dùng get_val(df, keyword, col), KHÔNG dùng get_metric()]"
    cols = df.columns.tolist()
    dtypes = ", ".join(str(df[c].dtype) for c in cols)
    lines = [
        f"### {var}  ({table_id})  [{stype}]{note_hint}",
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


def _tool_call_request(messages: list[dict]) -> tuple[str, dict, dict]:
    """Endpoint + body + headers for one run_code turn, per backend."""
    # temp=0 makes the REPL loop on identical failing code; sampling lets it escape.
    temperature = float(os.environ.get("REPL_TEMP", "0.7"))
    gemini = _REPL_BACKEND == "gemini"
    body = {
        "model": _GEMINI_MODEL if gemini else MODEL,
        "messages": messages,
        "tools": _TOOLS,
        "tool_choice": "required",
        "max_tokens": 4096,
        "temperature": temperature,
    }
    endpoint, key = (_GEMINI_ENDPOINT, _GEMINI_KEY) if gemini else (ENDPOINT, API_KEY)
    if not gemini:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return endpoint, body, ({"Authorization": f"Bearer {key}"} if key else {})


async def _allm_tool_call(messages: list[dict]) -> dict:
    """POST to vLLM or Gemini with run_code tool. Returns the raw assistant message dict."""
    endpoint, body, headers = _tool_call_request(messages)
    response = await client().post(endpoint, json=body, headers=headers, timeout=180)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]


def _render_state(
    ledger: list[tuple[str, str]],
    namespace: dict,
    initial_keys: set[str],
) -> str:
    """Persistent memory injected every turn: all prior code→output + live scalars.

    Replaces the old sliding window. The namespace already accumulates Python
    state across steps; this makes that state *visible* to the model so it never
    re-explores what it already computed.
    """
    lines = ["========== TRẠNG THÁI (các bước đã chạy) =========="]
    for i, (code, output) in enumerate(ledger, 1):
        lines.append(f"[{i}] >>> {code}")
        out = output.strip()
        if out:
            if len(out) > 600:
                out = out[:600] + " …(cắt)"
            lines.append(f"    → {out}")

    snap = []
    for k, v in namespace.items():
        if k in initial_keys or k == "result":
            continue
        if getattr(v, "ndim", 0) and getattr(v, "ndim", 0) > 0:
            continue  # arrays / Series / DataFrame — không phải scalar
        try:
            snap.append(f"  {k} = {float(v):.6g}")
        except (TypeError, ValueError):
            continue
    if snap:
        lines.append("\nBiến scalar hiện có trong namespace:")
        lines.extend(snap)

    lines.append("==================================================")
    lines.append(
        "Chạy BƯỚC TIẾP THEO dựa trên trạng thái trên. "
        "KHÔNG chạy lại code đã có ở trên. Gán result=<số> khi đã đủ dữ liệu."
    )
    return "\n".join(lines)


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


def _print_trace(ledger: list[tuple[str, str]], answer: float | None = None) -> None:
    import sys
    sep = "─" * 72
    print(f"\n{sep}", file=sys.stderr)
    print(f"REPL TRACE  {'→ result=' + str(answer) if answer is not None else '→ NO RESULT'}", file=sys.stderr)
    print(sep, file=sys.stderr)
    for i, (code, output) in enumerate(ledger, 1):
        print(f"[{i}] {code}", file=sys.stderr)
        if output.strip():
            for line in output.strip().splitlines():
                print(f"    {line}", file=sys.stderr)
    print(sep, file=sys.stderr)


async def arepl_generate(
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
            if not pd.api.types.is_numeric_dtype(df[c]):
                mask = df[c].astype(str).str.contains(keyword, na=False, case=False)
                if mask.any():
                    rows = df[mask]
                    if col and col in df.columns:
                        return rows[col].values[0]
                    for vc in df.columns:
                        if pd.api.types.is_numeric_dtype(df[vc]):
                            return rows[vc].values[0]
        return None

    canonical_data: dict[str, dict] = {}
    ticker_map: dict[str, str] = {}
    for var, tid in names.items():
        tmeta = _get_table_meta(tid)
        data = canonical_frame(frames[var], tid, tmeta["statement_type"])
        if data:
            canonical_data[var] = data
        ticker_map[var] = tmeta.get("ticker", "")

    def _get_metric(metric_id: str, year: int, ticker: str | None = None) -> float | None:
        """Search canonical across all dfs for (metric_id, year), optionally filtered by ticker."""
        for var, data in canonical_data.items():
            if ticker is not None and ticker_map.get(var, "").upper() != ticker.upper():
                continue
            if metric_id in data and year in data[metric_id]:
                return data[metric_id][year]
        return None

    namespace: dict = {**frames, "pd": pd, "np": np, "print": _safe_print,
                       "get_val": _get_val, "get_metric": _get_metric, "canonical": canonical_data}
    code_history: list[str] = []

    blocks = [_schema_block(var, names[var], frames[var]) for var in frames]
    # Hard cap on total schema. Canonical blocks are ~2000 chars each vs ~800 for raw schema,
    # but they encode actual values so the LLM needs fewer steps overall.
    _TOTAL_SCHEMA_CAP = 12000
    total = sum(len(b) for b in blocks)
    if total > _TOTAL_SCHEMA_CAP:
        ratio = _TOTAL_SCHEMA_CAP / total
        blocks = [b[: max(200, int(len(b) * ratio))] for b in blocks]
    schema_blocks = "\n\n".join(blocks)
    df_vars = ", ".join(frames.keys())
    planner_ctx = f"Planner đã thử nhưng gặp lỗi: {planner_error[:400]}\n\n" if planner_error else ""

    system_content = _SYSTEM_TMPL.format(
        question=question,
        schema_blocks=schema_blocks,
        df_vars=df_vars,
        planner_context=planner_ctx,
    )
    task = "Tính toán và gán result = <đáp án cuối> khi xong."
    initial_keys = set(namespace)
    ledger: list[tuple[str, str]] = []  # (code, output) for every step, never dropped

    for step in range(MAX_REPL_STEPS):
        # Rebuild context each turn from the persistent ledger + namespace snapshot
        # so the model always sees every prior observation and current variable values.
        user_content = task
        if ledger:
            user_content += "\n\n" + _render_state(ledger, namespace, initial_keys)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        try:
            asst = await _allm_tool_call(messages)
        except Exception as exc:
            if _REPL_TRACE:
                _print_trace(ledger)
            return _fail(code_history, names, planner_error, f"LLM error step {step}: {exc}")

        tool_calls = asst.get("tool_calls") or []
        if not tool_calls:
            break

        # Execute ALL run_code calls in this turn sequentially — namespace accumulates.
        # LLM may batch multiple calls; that's fine, we run them all and check result after.
        turn_had_exception = False
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (KeyError, json.JSONDecodeError):
                args = {}

            code = args.get("code", "").strip()
            if not code:
                continue
            # Strip import lines — pd/np/dfs already in namespace; __import__ blocked
            clean = "\n".join(
                ln for ln in code.splitlines()
                if not ln.lstrip().startswith("import ") and not ln.lstrip().startswith("from ")
            ).strip()
            run = clean or code
            output = exec_in_namespace(run, namespace)
            if len(output) > 2000:
                output = output[:2000] + "\n...(truncated)"
            code_history.append(run)
            ledger.append((run, output))
            # Detect exception in output — result set before the exception is unreliable
            if any(kw in output for kw in ("Error", "Traceback", "Exception")):
                turn_had_exception = True

        # Termination: any code in this turn assigned result = <scalar>
        # Skip if the turn threw an exception — result may be an intermediate loop value.
        if turn_had_exception and "result" in namespace:
            del namespace["result"]
        raw = namespace.get("result")
        if raw is not None:
            try:
                answer = float(raw)
                # Skip result=0: LLM often initialises counters with result=0 before loops.
                # Financial answers are virtually never exactly zero.
                if math.isfinite(answer) and answer != 0.0:
                    if _REPL_TRACE:
                        _print_trace(ledger, answer=answer)
                    return _success(answer, code_history, names, planner_error, step + 1)
            except (TypeError, ValueError):
                pass
            del namespace["result"]  # bad value or zero → clear and keep going

    if _REPL_TRACE:
        _print_trace(ledger)
    return _fail(code_history, names, planner_error, f"REPL: no result after {MAX_REPL_STEPS} steps")


def repl_generate(
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    planner_error: str = "",
    last_plan: dict | None = None,
) -> dict:
    """Sync `arepl_generate`, for the offline planner probes."""
    return run_sync(arepl_generate(question, frames, names, planner_error, last_plan))


def _success(
    answer: float,
    code_history: list[str],
    names: dict[str, str],
    planner_error: str,
    steps: int,
) -> dict:
    evidence = _evidence_from_codes(code_history, names)
    # Single-line float literal so the evaluator can eval() it directly.
    return {
        "pandas_query": repr(answer),
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
    pandas_query = "0.0"
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


def _render_schema_for_tool_repl(frames: dict[str, pd.DataFrame], names: dict[str, str]) -> str:
    blocks = [_schema_block(var, names[var], frames[var]) for var in frames]
    total = sum(len(block) for block in blocks)
    if total > _LANGCHAIN_REPL_TOTAL_SCHEMA_CAP:
        ratio = _LANGCHAIN_REPL_TOTAL_SCHEMA_CAP / total
        blocks = [block[: max(200, int(len(block) * ratio))] for block in blocks]
    return "\n\n".join(blocks)


def _build_tool_repl_namespace(frames: dict[str, pd.DataFrame], names: dict[str, str]) -> dict:
    import numpy as np

    def _safe_print(*args, **kwargs):
        print(*(a.tolist() if hasattr(a, "tolist") else a for a in args), **kwargs)

    def get_val(df: pd.DataFrame, keyword: str, col: str | None = None):
        """First row whose string cell contains keyword -> value from col or first numeric."""
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):
                continue
            mask = df[c].astype(str).str.contains(keyword, na=False, case=False, regex=False)
            if mask.any():
                rows = df[mask]
                if col and col in df.columns:
                    return rows[col].values[0]
                for value_col in df.columns:
                    if pd.api.types.is_numeric_dtype(df[value_col]):
                        return rows[value_col].values[0]
        print(
            f"get_val(keyword={keyword!r}) -> None: không có dòng nào khớp. "
            f"Cột: {list(df.columns)}. Dùng print(df) để xem đúng nhãn/tên cột."
        )
        return None

    canonical_data: dict[str, dict] = {}
    ticker_map: dict[str, str] = {}
    for var, table_id in names.items():
        meta = _get_table_meta(table_id)
        data = canonical_frame(frames[var], table_id, meta["statement_type"])
        if data:
            canonical_data[var] = data
        ticker_map[var] = meta.get("ticker", "")

    def get_metric(metric_id: str, year: int, ticker: str | None = None):
        """Search canonical across all dfs for (metric_id, year), optional ticker filter."""
        for var, data in canonical_data.items():
            if ticker is not None and ticker_map.get(var, "").upper() != ticker.upper():
                continue
            if metric_id in data and year in data[metric_id]:
                return data[metric_id][year]
        avail_tickers = sorted({ticker for ticker in ticker_map.values() if ticker})
        all_metrics = sorted(set().union(*[d.keys() for d in canonical_data.values()])) if canonical_data else []
        if ticker is not None and ticker.upper() not in {t.upper() for t in avail_tickers}:
            print(f"get_metric(..., ticker={ticker!r}) -> None: ticker có: {avail_tickers}")
        elif metric_id not in all_metrics:
            print(
                f"get_metric({metric_id!r}, ...) -> None: không phải chỉ tiêu canonical. "
                f"Khoản mục chi tiết dùng get_val(df, '<nhãn>'). Canonical hiện có: {all_metrics[:20]}"
            )
        else:
            print(f"get_metric({metric_id!r}, {year}) -> None: không có số cho năm {year}.")
        return None

    return {
        **frames,
        "pd": pd,
        "np": np,
        "print": _safe_print,
        "get_val": get_val,
        "get_metric": get_metric,
        "canonical": canonical_data,
    }


def _strip_imports(code: str) -> str:
    kept = [
        line
        for line in code.splitlines()
        if not line.lstrip().startswith(("import ", "from "))
    ]
    return "\n".join(kept).strip() or code


async def asolve_repl(
    *,
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    unit_hint: str = "",
    errors: list[str] | None = None,
    max_steps: int = _LANGCHAIN_REPL_MAX_STEPS,
) -> dict:
    """LangChain tool-calling REPL used by the finance graph.

    `arepl_generate()` above remains the batch fallback for the planner
    generator. This service is state-shaped for graph adapters.
    """
    prior_errors = list(errors or [])

    def _out(answer: float, pandas_query: str, code_history: list[str], extra_err=None) -> dict:
        return {
            "answer": answer,
            "pandas_query": pandas_query,
            "evidence": _evidence_from_codes(code_history, names) if code_history else [],
            "solver": "repl",
            "errors": prior_errors + ([extra_err] if extra_err else []),
        }

    if not frames:
        return _out(0.0, "0.0", [], "repl: no frames loaded")

    namespace = _build_tool_repl_namespace(frames, names)
    code_history: list[str] = []

    @tool
    def run_code(code: str) -> str:
        """Chạy code Python/pandas trong namespace bền vững. Gán result = <số> khi xong."""
        clean = _strip_imports(code)
        output = exec_in_namespace(clean, namespace, include_stdout_on_error=True)
        code_history.append(clean)
        return output[:_LANGCHAIN_REPL_OUTPUT_CAP] + (
            "\n...(truncated)" if len(output) > _LANGCHAIN_REPL_OUTPUT_CAP else ""
        )

    llm = get_chat_model(
        thinking=False,
        max_tokens=_LANGCHAIN_REPL_MAX_TOKENS,
        temperature=_LANGCHAIN_REPL_TEMPERATURE,
    ).bind_tools([run_code], tool_choice="required")

    messages: list = [
        SystemMessage(
            REPL_SYSTEM.format(
                question=question,
                unit_hint=unit_hint or "(không nêu — giữ nguyên giá trị gốc)",
                df_vars=", ".join(frames),
                schema_blocks=_render_schema_for_tool_repl(frames, names),
            )
        ),
        HumanMessage("Tính toán từng bước, rồi gán result = <đáp án cuối>."),
    ]

    llm_errors = 0
    stuck = 0
    last_err_out = None
    for _ in range(max_steps):
        try:
            ai: AIMessage = await llm.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            llm_errors += 1
            if llm_errors <= 2:
                messages.append(
                    HumanMessage(
                        "Yêu cầu vừa rồi bị lỗi, có thể do code quá dài nên bị cắt. "
                        "Hãy viết code thật ngắn, chỉ 1-2 dòng cho bước tiếp theo, "
                        "rồi gán result khi đã có đáp án."
                    )
                )
                continue
            return _out(0.0, "0.0", code_history, f"repl: LLM error: {exc}")
        messages.append(ai)
        if not ai.tool_calls:
            break

        turn_error = False
        turn_out: list[str] = []
        for tc in ai.tool_calls:
            output = run_code.invoke(tc["args"])
            messages.append(ToolMessage(content=output, tool_call_id=tc["id"]))
            turn_out.append(output)
            if any(marker in output for marker in ("Error", "Traceback", "Exception")):
                turn_error = True

        if turn_error:
            namespace.pop("result", None)
            joined = "\n".join(turn_out)
            stuck = stuck + 1 if joined == last_err_out else 0
            last_err_out = joined
            if stuck >= 1:
                messages.append(
                    HumanMessage(
                        "Bạn lặp lại cùng một lỗi. Chạy từng bước nhỏ: print riêng từng "
                        "get_metric()/get_val() để tìm giá trị None, sửa ticker/nhãn/tên cột, "
                        "rồi mới ghép lại."
                    )
                )
            if stuck >= 3:
                return _out(0.0, "0.0", code_history, "repl: stuck on repeated error")
            continue
        last_err_out = None

        raw = namespace.get("result")
        if raw is not None:
            try:
                answer = float(raw)
            except (TypeError, ValueError):
                answer = None
            if answer is not None and math.isfinite(answer) and answer != 0.0:
                return _out(answer, repr(answer), code_history)
            namespace.pop("result", None)

    return _out(0.0, "0.0", code_history, f"repl: no answer after {max_steps} steps")


def solve_repl(
    *,
    question: str,
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    unit_hint: str = "",
    errors: list[str] | None = None,
    max_steps: int = _LANGCHAIN_REPL_MAX_STEPS,
) -> dict:
    """Sync `asolve_repl`, for single-question scripts."""
    return run_sync(
        asolve_repl(
            question=question,
            frames=frames,
            names=names,
            unit_hint=unit_hint,
            errors=errors,
            max_steps=max_steps,
        )
    )
