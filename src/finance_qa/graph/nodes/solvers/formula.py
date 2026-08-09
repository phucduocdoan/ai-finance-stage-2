"""Formula solver: a single-shot node over canonical financial data.

`_collect_canonical()` already pulls the full dataset into memory
({ticker: {year: {metric: value}}}), so there is nothing to explore — no ReAct
loop is needed. We pre-compute every named ratio deterministically, render the
whole table, and make ONE LLM call that reasons over it and submits the number
via `final_answer` (a JSON float, which sidesteps the decimal-drop bug we hit
parsing numbers out of Qwen's free text).

Falls back to repl (solver="formula_skip") when there is no formula pattern in
the question, no canonical data, or the model returns no numeric answer.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from finance_qa.graph.state import FinanceState
from finance_qa.preprocessing.canonical import canonical_frame, _get_table_meta
from finance_qa.retrieval.judge import ENDPOINT, MODEL, _API_KEY

# ── Formula pattern detection ─────────────────────────────────────────────────

_FORMULA_RE = re.compile(
    r"D/E|tỷ số nợ|hệ số nợ|\bROE\b|\bROA\b|\bROS\b"
    r"|biên lợi nhuận|tỷ suất.*lợi nhuận|thanh toán lãi vay"
    r"|khả năng thanh toán|vòng quay|lưu chuyển tiền.*kinh doanh"
    r"|tổng.*(?:\d{4}|\bnăm\b)|trung bình|bình quân"
    r"|cao nhất|thấp nhất|chênh lệch|giai đoạn \d{4}[-–]\d{4}",
    re.IGNORECASE,
)

_TRACE = os.environ.get("FORMULA_TRACE", "") not in ("", "0")


def _is_formula_question(question: str) -> bool:
    return bool(_FORMULA_RE.search(question))


# ── Canonical data collection ─────────────────────────────────────────────────

_CANONICAL_STMTS = {"balance_sheet", "income_statement", "cash_flow"}


def _collect_canonical(
    frames: dict[str, Any],
    names: dict[str, str],
) -> dict[str, dict[str, dict[str, float]]]:
    """Return {ticker: {year_str: {metric_id: float}}} from all loaded frames."""
    data: dict[str, dict[str, dict[str, float]]] = {}
    for var, table_id in names.items():
        df = frames.get(var)
        if df is None:
            continue
        meta = _get_table_meta(table_id)
        if not meta.get("has_ma_so_column"):
            continue
        stmt = meta.get("statement_type", "")
        if stmt not in _CANONICAL_STMTS:
            continue
        ticker = meta.get("ticker") or "unknown"
        canon = canonical_frame(df, table_id, stmt)
        for metric_id, yr_vals in canon.items():
            for yr_int, val in yr_vals.items():
                yr = str(yr_int)
                data.setdefault(ticker, {}).setdefault(yr, {})[metric_id] = val
    return data


# ── Named financial formulas ──────────────────────────────────────────────────

def _safe_div(a: float, b: float) -> float | None:
    if not b or math.isnan(b) or math.isnan(a):
        return None
    result = a / b
    return None if math.isinf(result) else result


_FORMULAS: dict[str, Any] = {
    "de_ratio":      lambda m: _safe_div(m["total_debt"], m["equity"]),
    "roe":           lambda m: _safe_div(
                         m.get("net_profit_attributable_to_owners", m.get("net_profit", 0)),
                         m["owners_equity"]),
    "roa":           lambda m: _safe_div(
                         m.get("net_profit_attributable_to_owners", m.get("net_profit", 0)),
                         m["total_assets"]),
    "gross_margin":  lambda m: _safe_div(m["gross_profit"], m["net_revenue"]),
    "net_margin":    lambda m: _safe_div(
                         m.get("net_profit_attributable_to_owners", m.get("net_profit", 0)),
                         m["net_revenue"]),
    "current_ratio": lambda m: _safe_div(m["current_assets"], m["short_term_debt"]),
    "quick_ratio":   lambda m: _safe_div(
                         m["current_assets"] - m.get("inventory", 0),
                         m["short_term_debt"]),
    "icr":           lambda m: _safe_div(
                         m["profit_before_tax"] + abs(m["interest_expense"]),
                         abs(m["interest_expense"])),
    "debt_ratio":    lambda m: _safe_div(m["total_debt"], m["total_assets"]),
    "cash_ratio":    lambda m: _safe_div(m["net_cash_operating"], m["net_revenue"]),
}


def _ratios_for(metrics: dict) -> dict[str, float]:
    """Every named ratio computable from these metrics."""
    out: dict[str, float] = {}
    for name, fn in _FORMULAS.items():
        try:
            v = fn(metrics)
        except (KeyError, TypeError, ZeroDivisionError):
            v = None
        if v is not None and math.isfinite(v):
            out[name] = v
    return out


# Headline raw metrics worth showing alongside the ratios. The full canonical
# row carries ~60 fields; dumping all of them buries the signal, so we keep the
# line items questions actually reference.
_HEADLINE = [
    "net_revenue", "gross_profit", "operating_profit", "profit_before_tax",
    "net_profit", "interest_expense", "net_cash_operating",
    "total_assets", "total_debt", "equity",
]


def _render(data: dict) -> str:
    """Render each year as pre-computed ratios + a few headline raw metrics."""
    lines: list[str] = []
    for ticker in sorted(data):
        lines.append(f"{ticker}:")
        for yr in sorted(data[ticker]):
            metrics = data[ticker][yr]
            ratios = _ratios_for(metrics)
            rtxt = ", ".join(f"{k}={v:.10g}" for k, v in sorted(ratios.items()))
            raw = ", ".join(f"{k}={metrics[k]:.6g}" for k in _HEADLINE if k in metrics)
            lines.append(f"  {yr}: {rtxt}")
            lines.append(f"      [VND] {raw}")
    return "\n".join(lines)


# ── LLM client ────────────────────────────────────────────────────────────────

_SYSTEM = "Bạn là chuyên gia phân tích tài chính."

_PROMPT = """\
Dữ liệu tài chính đã chuẩn hóa (các tỷ số đã tính sẵn, số liệu thô đơn vị VND):
{table}

Câu hỏi: {question}

Suy luận theo ĐÚNG thứ tự các bước của câu hỏi. Với câu hỏi lồng nhau (ví dụ
"năm có D/E cao nhất thì ICR là bao nhiêu"): trước hết chọn năm/công ty thoả
điều kiện lọc, rồi mới lấy chỉ tiêu cần trả lời của đúng năm/công ty đó — không
lấy giá trị lớn nhất/nhỏ nhất của chính chỉ tiêu cần trả lời.

Trả lời đúng đơn vị câu hỏi yêu cầu (phần trăm nhân 100; "lần" giữ nguyên tỷ số;
tiền quy đổi từ VND). Kết thúc bằng một dòng: ĐÁP SỐ: <số>"""


@tool
def final_answer(answer: float) -> float:
    """Nộp đáp số cuối cùng dưới dạng số thực."""
    return answer


def _get_llm(thinking: bool = True, max_tokens: int = 2048) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "base_url": ENDPOINT.replace("/chat/completions", ""),
        "api_key": _API_KEY or "none",
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "timeout": 120,
    }
    if "Qwen" in MODEL:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}
    return ChatOpenAI(**kwargs)


def _extract_number(reasoning: str) -> float | None:
    """Second call: turn the reasoning's final answer into an exact JSON float.

    The server has no auto tool-choice, so we cannot let the model reason and
    emit a tool call in one shot. We reason in text (thinking on, no tools) then
    force final_answer here — a JSON float avoids the decimal-drop bug we hit
    parsing numbers out of free text."""
    llm = _get_llm(thinking=False, max_tokens=256).bind_tools(
        [final_answer], tool_choice="required"
    )
    prompt = (
        "Trích đáp số cuối cùng (số thực) từ phân tích sau và gọi final_answer:\n\n"
        + reasoning
    )
    try:
        ai: AIMessage = llm.invoke([HumanMessage(prompt)])
    except Exception as e:
        if _TRACE:
            print(f"[formula] extract error: {e}")
        return None
    for tc in ai.tool_calls:
        if tc["name"] == "final_answer" and tc["args"].get("answer") is not None:
            v = float(tc["args"]["answer"])
            return v if math.isfinite(v) else None
    return None


def _solve(question: str, data: dict) -> float | None:
    """Reason over the full data table (thinking on), then emit the number."""
    llm = _get_llm(thinking=True)  # no tools — let the model reason freely
    prompt = _PROMPT.format(table=_render(data), question=question)
    try:
        ai: AIMessage = llm.invoke([SystemMessage(_SYSTEM), HumanMessage(prompt)])
    except Exception as e:
        if _TRACE:
            print(f"[formula] solve error: {e}")
        return None
    reasoning = ai.content or ""
    if not reasoning.strip():
        return None
    if _TRACE:
        tail = reasoning.strip().splitlines()[-1] if reasoning.strip() else ""
        print(f"  reasoning tail: {tail}")
    return _extract_number(reasoning)


# ── LangGraph node ────────────────────────────────────────────────────────────

_SKIP = "formula_skip"


def formula_solver(state: FinanceState) -> dict:
    """LangGraph node. Sets solver='formula_skip' when it cannot handle the question."""
    question = state["question"]
    frames   = state.get("frames") or {}
    names    = state.get("names") or {}
    errors   = list(state.get("errors") or [])

    def _skip(reason: str) -> dict:
        return {"solver": _SKIP, "errors": errors + [f"formula_skip: {reason}"]}

    if not _is_formula_question(question):
        return _skip("no formula pattern")

    data = _collect_canonical(frames, names)
    if not data:
        return _skip("no canonical data")

    result = _solve(question, data)
    if result is None:
        return _skip("solver returned no answer")

    return {
        "answer":       result,
        "pandas_query": f"formula_oneshot({len(data)} tickers)",
        "evidence":     [],
        "solver":       "formula",
        "errors":       errors,
    }
