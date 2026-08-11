"""Prototype: REPL reason node with the LOCAL weak model (Qwen3-8B via call_llm).

Open question this isolates:
  mode-A one-shot free-form pandas: local Qwen 1-2/8, Gemini 5/8. The gap was the WEAK
  model, not the data (facts are clean). Does letting the weak model run code STEP BY STEP —
  seeing real values via print(), self-repairing on errors, and only then submitting — close
  that gap WITHOUT depending on a strong hosted model?

Controlled A/B: SAME clean mã-số fact table as prototype_mode_a.py, SAME 8 questions, SAME
local model. The only change is one-shot → REPL. So any lift is attributable to the loop.

Protocol (weak-model-friendly, no JSON-with-code parsing):
  - The model writes ONE ```python block per turn.
  - It uses print(...) to inspect, and calls submit(<number>) when it has the final answer.
  - We exec each block in a PERSISTENT namespace, capture stdout, feed it back as the
    observation for the next turn. Errors are fed back too (self-repair).

Run:
    PYTHONPATH=src python3 scripts/prototype_repl.py
"""

from __future__ import annotations

import io
import json
import math
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

import pandas as pd

from eval_gold import get_v_signed
from finance_qa.modules.rag.judge import call_llm

BS, IS, CF = "balance_sheet", "income_statement", "cash_flow"

CORE_MASO = [
    (IS, 10, "Doanh thu thuần"), (IS, 11, "Giá vốn hàng bán"), (IS, 20, "Lợi nhuận gộp"),
    (IS, 30, "LN thuần HĐKD"), (IS, 23, "Chi phí lãi vay"), (IS, 50, "LN trước thuế"),
    (IS, 60, "LN sau thuế (NPAT)"), (CF, 20, "Lưu chuyển tiền thuần HĐKD (CFO)"),
    (BS, 100, "Tài sản ngắn hạn"), (BS, 140, "Hàng tồn kho"), (BS, 220, "Tài sản cố định thuần"),
    (BS, 270, "Tổng tài sản"), (BS, 300, "Nợ phải trả"), (BS, 310, "Nợ ngắn hạn"),
    (BS, 400, "Vốn chủ sở hữu"),
]

TEST_IDS = [371, 390, 392, 396, 415, 387, 381, 440]

MAX_STEPS = 6


def scope(q: dict) -> tuple[list[str], list[int]]:
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


def _make_g(facts: pd.DataFrame):
    def g(ticker: str, year, stmt: str, ma_so) -> float:
        # tolerate str inputs from the model ('60'/'2024') — coerce to the df's int dtype
        try:
            year, ma_so = int(year), int(ma_so)
        except (TypeError, ValueError):
            return float("nan")
        m = facts[(facts.ticker == ticker) & (facts.year == year)
                  & (facts.stmt == stmt) & (facts.ma_so == ma_so)]
        if len(m) == 0:
            return float("nan")
        v = m["value"].iloc[0]
        return float(v) if pd.notna(v) else float("nan")
    return g


REPL_SYSTEM = """\
Bạn là chuyên viên phân tích tài chính, làm việc trong một REPL Python.

BẢNG DỮ LIỆU SẠCH `facts` (đã trích theo mã số kế toán VAS; value có dấu, đơn vị = đồng;
value=NaN nghĩa là không có số đó):
{facts}

Cột: ticker | year | stmt (balance_sheet/income_statement/cash_flow) | ma_so | label | value.

Công cụ có sẵn trong namespace (biến TỒN TẠI giữa các bước):
- `facts` (DataFrame trên), `pd`, `math`.
- `g(ticker, year, stmt, ma_so)` -> 1 số có dấu hoặc nan. LUÔN dùng g(...) để lấy số.
- `submit(x)` -> nộp đáp án cuối (1 số). Gọi khi đã chắc chắn.

Câu hỏi: {question}

Quy tắc:
- ma_so 20: stmt='cash_flow' là CFO; stmt='income_statement' là lợi nhuận gộp.
- Dùng abs() khi cần ĐỘ LỚN (chi phí lãi vay ma_so 23, giá vốn). Điều kiện "dương" so sánh có dấu (>0).
- Bỏ qua công ty/năm thiếu số bằng math.isnan(...).
- Đổi đúng đơn vị câu hỏi yêu cầu (lần / % / nghìn tỷ=1e12 / tỷ=1e9).
- submit() phải là ĐẠI LƯỢNG CUỐI câu hỏi hỏi, KHÔNG phải bước trung gian.

Cách làm: mỗi lượt viết ĐÚNG MỘT khối ```python. Dùng print(...) để xem giá trị thật và
kiểm tra từng bước. Khi chắc chắn, gọi submit(<số>). Đừng đoán — hãy print ra để xác nhận."""

REPL_HIST_ITEM = """\
[Bước {i}] code bạn đã chạy:
```python
{code}
```
Kết quả:
{obs}"""

REPL_CONTINUE = """\

LỊCH SỬ CÁC BƯỚC ĐÃ CHẠY (các biến vẫn còn sống trong namespace — KHÔNG cần chạy lại từ đầu,
hãy dùng tiếp biến đã có và đi tiếp):
{history}

Bước {step}/{max_steps}. Viết khối ```python tiếp theo (print để kiểm tra, hoặc submit(<số>) nếu đã xong)."""


def extract_code(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.split("</think>")[-1]
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", raw, re.DOTALL)
    return blocks[-1].strip() if blocks else ""


def run_repl(question: str, facts: pd.DataFrame, verbose: bool = False) -> tuple[float | None, str]:
    holder: dict = {"final": None}

    def submit(x):
        holder["final"] = x

    ns = {"facts": facts, "pd": pd, "math": math, "g": _make_g(facts), "submit": submit}

    sys_prompt = REPL_SYSTEM.format(facts=facts.to_string(index=False), question=question)
    transcript = ""
    history: list[tuple[str, str]] = []  # (code, obs) tích luỹ, đưa vào ngữ cảnh mỗi bước
    for step in range(MAX_STEPS):
        if history:
            hist_txt = "\n\n".join(
                REPL_HIST_ITEM.format(i=i, code=c, obs=o) for i, (c, o) in enumerate(history)
            )
            prompt = sys_prompt + REPL_CONTINUE.format(
                history=hist_txt, step=step, max_steps=MAX_STEPS)
        else:
            prompt = sys_prompt
        raw = call_llm(prompt, thinking=(step == 0),
                       max_tokens=4096 if step == 0 else 1536)
        code = extract_code(raw)
        if not code:
            obs = "(không tìm thấy khối ```python. Hãy viết code trong ```python ... ```.)"
        else:
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    exec(compile(code, "<repl>", "exec"), ns)  # noqa: S102
                obs = buf.getvalue().strip() or "(không có output — dùng print() để xem giá trị)"
            except Exception as exc:  # noqa: BLE001
                obs = f"LỖI {type(exc).__name__}: {exc}"
        history.append((code, obs))
        transcript += f"\n--- step {step} code ---\n{code}\n--- step {step} obs ---\n{obs}\n"
        if verbose:
            print(f"    [step {step}] code:\n{code}\n    obs: {obs[:200]}")

        if holder["final"] is not None:
            try:
                val = float(holder["final"])
                if math.isfinite(val):
                    return val, transcript
                holder["final"] = None  # non-finite, keep going
            except (TypeError, ValueError):
                holder["final"] = None
    return None, transcript


def main() -> None:
    verbose = "-v" in sys.argv
    by_id = {json.loads(l)["id"]: json.loads(l)
             for l in open("data/metadata/questions_enriched.jsonl", encoding="utf-8")}
    gold = {json.loads(l)["id"]: json.loads(l)
            for l in open("data/eval/extended_gold.jsonl", encoding="utf-8")}

    print(f"{'qid':>4}  {'gold':>12}  {'pred':>14}  {'result':>10}")
    print("-" * 60)
    correct = 0
    for qid in TEST_IDS:
        q = by_id[qid]
        tickers, years = scope(q)
        facts = materialize(tickers, years)
        pred, transcript = run_repl(q["question"], facts, verbose=verbose)
        g = gold[qid]["answer"]
        if pred is None:
            res = "ERR"
        else:
            rel = abs(pred - g) / abs(g) if abs(g) > 1e-9 else abs(pred)
            res = "✓" if rel < 0.01 else f"✗ {rel:.1%}"
        if res == "✓":
            correct += 1
        print(f"{qid:>4}  {g:>12.6g}  {str(pred):>14}  {res:>10}")
        if verbose:
            Path(f"artifacts/eval/repl_q{qid}.txt").write_text(transcript, encoding="utf-8")

    print("-" * 60)
    print(f"REPL + LOCAL Qwen: {correct}/{len(TEST_IDS)}  "
          f"(mode-A one-shot local ~1-2/8; Gemini 5/8 — đây là test model yếu)")


if __name__ == "__main__":
    main()
