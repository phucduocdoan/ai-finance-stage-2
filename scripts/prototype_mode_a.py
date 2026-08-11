"""Prototype: Option B mode-A end-to-end with a REAL LLM doing the reasoning.

Thesis under test: if we hand the LLM a CLEAN deterministic fact table (values keyed by
accounting mã-số, materialized via get_v) instead of raw messy OCR tables, does it reason
correctly? The pilot showed the current pipeline fails main-statement 5/10 by picking the
wrong ROW. This isolates whether clean facts fix that.

Three nodes:
  scope       — deterministic: tickers/years from questions_enriched (+ prior year for growth)
  materialize — deterministic: fan get_v_signed over ticker × year × CORE_MASO → tidy df
  reason      — LLM (local Qwen via call_llm) writes pandas over `facts` → answer

Failures are classified scope-miss vs reason-miss so we don't blame reasoning for a bad scope.

Run:
    PYTHONPATH=src python3 scripts/prototype_mode_a.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

import pandas as pd

from eval_gold import get_v_signed

# --- reason backend: strong hosted model (Gemini) for the LLM reasoning node only.
#     The data layer (get_v_signed / materialize) stays 100% local & deterministic. ---
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
REASON_MODEL = "gemini-2.5-flash"


def _gemini_key() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not in .env")


def call_reason(prompt: str, max_tokens: int = 8192) -> str:
    body = {
        "model": REASON_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    req = urllib.request.Request(
        GEMINI_ENDPOINT, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_gemini_key()}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]

BS, IS, CF = "balance_sheet", "income_statement", "cash_flow"

CORE_MASO = [
    (IS, 10, "Doanh thu thuần"), (IS, 11, "Giá vốn hàng bán"), (IS, 20, "Lợi nhuận gộp"),
    (IS, 30, "LN thuần HĐKD"), (IS, 23, "Chi phí lãi vay"), (IS, 50, "LN trước thuế"),
    (IS, 60, "LN sau thuế (NPAT)"), (CF, 20, "Lưu chuyển tiền thuần HĐKD (CFO)"),
    (BS, 100, "Tài sản ngắn hạn"), (BS, 140, "Hàng tồn kho"), (BS, 220, "Tài sản cố định thuần"),
    (BS, 270, "Tổng tài sản"), (BS, 300, "Nợ phải trả"), (BS, 310, "Nợ ngắn hạn"),
    (BS, 400, "Vốn chủ sở hữu"),
]

# gold-20 subset for the prototype — spread of single-year multi-company + multi-year, easy→hard
TEST_IDS = [371, 390, 392, 396, 415, 387, 381, 440]


def scope(q: dict) -> tuple[list[str], list[int]]:
    """Deterministic scope from question metadata; expand years to include y-1 for growth."""
    years = sorted(set(q["years"]) | {y - 1 for y in q["years"]})
    return q["tickers"], years


def materialize(tickers: list[str], years: list[int]) -> pd.DataFrame:
    rows = []
    for tk in tickers:
        for yr in years:
            for stype, maso, label in CORE_MASO:
                rows.append({
                    "ticker": tk, "year": yr, "stmt": stype, "ma_so": maso,
                    "label": label, "value": get_v_signed(tk, yr, stype, maso),
                })
    return pd.DataFrame(rows)


REASON_PROMPT = """\
Bạn là chuyên viên phân tích tài chính. Dưới đây là BẢNG DỮ LIỆU SẠCH đã trích sẵn theo
mã số kế toán chuẩn (VAS). Mỗi dòng = 1 chỉ tiêu của 1 công ty trong 1 năm.

{facts}

Cột: ticker | year | stmt (balance_sheet/income_statement/cash_flow) | ma_so (mã số VAS) |
label (tên chỉ tiêu) | value (giá trị ĐÃ BÁO CÁO, CÓ DẤU; đơn vị = đồng).
value = NaN nghĩa là không tra được số đó.

Câu hỏi: {question}

Viết code Python để tính đáp án. Có sẵn:
- `facts` (DataFrame trên) và `pd`.
- Hàm truy số AN TOÀN: `g(ticker, year, stmt, ma_so)` → trả 1 số (có dấu) hoặc nan nếu không có.
  Ví dụ: `cfo = g('MSN', 2024, 'cash_flow', 20)`. LUÔN dùng `g(...)` để lấy số, ĐỪNG tự index DataFrame.
- `import math` sẵn; kiểm tra `math.isnan(x)` để bỏ công ty/năm thiếu dữ liệu (đừng để chia 0 / lấy None).

Quy tắc:
- ma_so 20: stmt='cash_flow' là CFO; stmt='income_statement' là lợi nhuận gộp.
- Dùng abs() khi công thức cần ĐỘ LỚN (chi phí lãi vay ma_so 23, giá vốn). Điều kiện "dương" so sánh có dấu (>0).
- Đổi đúng ĐƠN VỊ câu hỏi yêu cầu (lần / % / nghìn tỷ=1e12 / tỷ=1e9).
- `answer` phải là ĐẠI LƯỢNG CUỐI CÙNG câu hỏi hỏi, KHÔNG phải bước trung gian (ví dụ hỏi "hệ số thanh
  toán nhanh của công ty có CFO/LNST cao nhất" → answer là quick ratio, KHÔNG phải CFO/LNST).

Trả về DUY NHẤT một khối code, kết thúc bằng gán `answer`:
```python
answer = ...
```"""

REASON_REPAIR = """\
Code trước lỗi khi chạy:
{error}

Sửa lại. Nhớ dùng `g(ticker, year, stmt, ma_so)` để lấy số và `math.isnan(...)` để bỏ ô thiếu.
Trả về DUY NHẤT một khối code kết thúc bằng `answer = ...`."""


def extract_code(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", raw, re.DOTALL)
    return blocks[-1].strip() if blocks else raw.strip()


def _make_g(facts: pd.DataFrame):
    def g(ticker: str, year: int, stmt: str, ma_so: int) -> float:
        m = facts[(facts.ticker == ticker) & (facts.year == year)
                  & (facts.stmt == stmt) & (facts.ma_so == ma_so)]
        if len(m) == 0:
            return float("nan")
        v = m["value"].iloc[0]
        return float(v) if pd.notna(v) else float("nan")
    return g


def reason(question: str, facts: pd.DataFrame, max_attempts: int = 2) -> tuple[float | None, str, str]:
    import math
    base = REASON_PROMPT.format(facts=facts.to_string(index=False), question=question)
    prompt, last_err, code = base, "", ""
    for _ in range(max_attempts):
        raw = call_reason(prompt)
        code = extract_code(raw)
        ns = {"facts": facts, "pd": pd, "math": math, "g": _make_g(facts), "answer": None}
        try:
            exec(compile(code, "<reason>", "exec"), ns)  # noqa: S102
            ans = ns.get("answer")
            if ans is not None and math.isfinite(float(ans)):
                return float(ans), code, ""
            last_err = "answer is None or non-finite"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        prompt = base + "\n\n" + REASON_REPAIR.format(error=last_err)
    return None, code, last_err


def main() -> None:
    by_id = {json.loads(l)["id"]: json.loads(l)
             for l in open("data/metadata/questions_enriched.jsonl", encoding="utf-8")}
    gold = {json.loads(l)["id"]: json.loads(l)
            for l in open("data/eval/extended_gold.jsonl", encoding="utf-8")}

    print(f"{'qid':>4}  {'gold':>12}  {'pred':>14}  {'result':>10}  facts(nonnull/total)")
    print("-" * 78)
    correct = 0
    for qid in TEST_IDS:
        q = by_id[qid]
        tickers, years = scope(q)
        facts = materialize(tickers, years)
        nonnull = facts["value"].notna().sum()
        pred, code, err = reason(q["question"], facts)
        g = gold[qid]["answer"]

        if pred is None:
            res = "ERR"
        else:
            rel = abs(pred - g) / abs(g) if abs(g) > 1e-9 else abs(pred)
            res = "✓" if rel < 0.01 else f"✗ {rel:.1%}"
        if res == "✓":
            correct += 1
        print(f"{qid:>4}  {g:>12.6g}  {str(pred):>14}  {res:>10}  {nonnull}/{len(facts)}"
              + (f"   [{err[:40]}]" if err else ""))

    print("-" * 78)
    print(f"mode-A + LLM reason: {correct}/{len(TEST_IDS)} correct")
    print("(pipeline cũ trên lớp main-statement pilot: 5/10 — đây là baseline ngầm để so)")


if __name__ == "__main__":
    main()
