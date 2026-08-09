"""Understand node: LLM extracts structured intent from the question.

Replaces classify (which reads pre-computed metadata) with semantic LLM understanding.
Output fields feed retrieve_targeted and the router.

Tickers are resolved rule-based from the BTC-provided code_stock.csv *before*
the LLM call (the map is authoritative, and the 8B otherwise hallucinated codes
like "Nam Kim" → NKM instead of NKG). The resolved list is both fed to the LLM
as context and used as the final answer; the LLM only decides operation/metric/
shape, which have no authoritative source.
"""
from __future__ import annotations

import json
import re
import urllib.request

from finance_qa.graph.state import FinanceState
from finance_qa.preprocessing.questions import (
    build_name_index,
    find_tickers,
    load_ticker_data,
)
from finance_qa.retrieval.judge import ENDPOINT, _API_KEY

_VALID_TICKERS, _TICKER_NAMES = load_ticker_data()
_NAME_INDEX = build_name_index(_TICKER_NAMES)


def _resolve_tickers(question: str) -> list[str]:
    """Ticker codes in the question, by direct code + company-name match."""
    return find_tickers(question, _VALID_TICKERS, _NAME_INDEX)

_SYSTEM = """\
Bạn là hệ thống phân tích câu hỏi tài chính Việt Nam.
Trích xuất thông tin có cấu trúc từ câu hỏi và trả về JSON (không giải thích thêm).

Schema:
{
  "tickers": ["HPG"],          // mã cổ phiếu viết hoa, lấy từ dấu ngoặc đơn hoặc từ tên công ty
  "years": [2021, 2022],       // các năm nguyên được đề cập hoặc nằm trong khoảng
  "metric": "gross_margin",    // chỉ tiêu chính, dùng tên tiếng Anh: revenue|net_revenue|gross_profit|
                               // net_profit|total_assets|total_debt|equity|interest_expense|
                               // gross_margin|net_margin|roe|roa|de_ratio|icr|quick_ratio|
                               // net_cash_operating|cash_and_equivalents|inventory|...
  "operation": "lookup",       // xem bên dưới
  "doc_type": "unknown",       // "consolidated" nếu hỏi hợp nhất, "separate" nếu hỏi công ty mẹ/riêng lẻ, "unknown" nếu không rõ
  "multi_year": false,         // true nếu hỏi nhiều năm khác nhau
  "multi_company": false,      // true nếu hỏi nhiều công ty khác nhau
  "unit_hint": "tỷ đồng",     // đơn vị đầu ra nếu đề cập, để trống nếu không có
  "answer_shape": "derived"    // "single_cell" nếu tra 1 ô dữ liệu, "derived" nếu cần tính toán
}

Quy tắc operation:
- "lookup"     : tra 1 giá trị trực tiếp từ báo cáo tài chính (doanh thu, tài sản, ...)
- "formula"    : tính 1 tỷ số tài chính cho 1 hoặc nhiều công ty/năm (D/E, ROE, ICR, biên lợi nhuận, ...)
- "compare"    : so sánh để tìm max/min/cao nhất/thấp nhất giữa nhiều công ty hoặc năm
- "multi_step" : nhiều bước liên kết (VD: tìm năm D/E cao nhất → rồi tính ICR năm đó)

Ví dụ:
Q: "Doanh thu năm 2022 của HPG là bao nhiêu tỷ đồng?"
→ {"tickers":["HPG"],"years":[2022],"metric":"net_revenue","operation":"lookup","doc_type":"unknown","multi_year":false,"multi_company":false,"unit_hint":"tỷ đồng","answer_shape":"single_cell"}

Q: "Lãi tiền gửi năm 2018 của công ty mẹ VJC là bao nhiêu triệu đồng?"
→ {"tickers":["VJC"],"years":[2018],"metric":"interest_income","operation":"lookup","doc_type":"separate","multi_year":false,"multi_company":false,"unit_hint":"triệu đồng","answer_shape":"single_cell"}

Q: "Năm 2024, trong nhóm BSR, PLX và PVT, công ty có biên lợi nhuận gộp cao nhất có ICR là bao nhiêu?"
→ {"tickers":["BSR","PLX","PVT"],"years":[2024],"metric":"gross_margin","operation":"multi_step","multi_year":false,"multi_company":true,"unit_hint":"","answer_shape":"derived"}

Q: "Trong giai đoạn 2016-2020, vào năm KBC có D/E cao nhất, ICR là bao nhiêu?"
→ {"tickers":["KBC"],"years":[2016,2017,2018,2019,2020],"metric":"de_ratio","operation":"multi_step","multi_year":true,"multi_company":false,"unit_hint":"","answer_shape":"derived"}
"""


def _post(question: str, tickers: list[str]) -> dict:
    user = question
    if tickers:
        user += f"\n\n(Mã cổ phiếu đã xác định sẵn: {', '.join(tickers)})"
    body = {
        "model": "Qwen/Qwen3-8B-Instruct",
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        "max_tokens": 300,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _parse(content: str) -> dict:
    # strip markdown code fence if present
    content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    content = re.sub(r"```\s*$", "", content.strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        return json.loads(m.group())
    return {}


def _expand_years(years: list) -> list[int]:
    """[2016, 2020] with gaps → expand if exactly 2 values spanning a short range."""
    ints = [int(y) for y in years if y]
    if len(ints) == 2 and 1 < ints[1] - ints[0] <= 10:
        return list(range(ints[0], ints[1] + 1))
    return ints


def understand(state: FinanceState) -> dict:
    resolved = _resolve_tickers(state["question"])
    try:
        rsp = _post(state["question"], resolved)
        content = rsp["choices"][0]["message"].get("content", "")
        result = _parse(content)
    except Exception as e:
        return {
            "tickers": resolved, "years": [], "metric": "", "operation": "multi_step",
            "doc_type": "unknown", "multi_year": False,
            "multi_company": len(resolved) > 1,
            "unit_hint": "", "answer_shape": "derived",
            "errors": (state.get("errors") or []) + [f"understand: {e}"],
        }

    years = _expand_years(result.get("years") or [])
    # BTC's code_stock.csv is authoritative: use rule-based tickers, falling
    # back to the LLM's guess only when name matching found nothing.
    tickers = resolved or [str(t).upper() for t in (result.get("tickers") or [])]

    doc_type = result.get("doc_type") or "unknown"
    if doc_type not in ("consolidated", "separate", "unknown"):
        doc_type = "unknown"

    return {
        "tickers":       tickers,
        "years":         years,
        "metric":        result.get("metric") or "",
        "operation":     result.get("operation") or "multi_step",
        "doc_type":      doc_type,
        "multi_year":    bool(result.get("multi_year", len(years) > 1)),
        "multi_company": bool(result.get("multi_company", len(tickers) > 1)),
        "unit_hint":     result.get("unit_hint") or "",
        "answer_shape":  result.get("answer_shape") or "derived",
    }
