"""Prototype: split the REPL catch-all into RESOLVE → COMPUTE to attack the 94%
grounding failures measured in measure_repl_rescue.jsonl.

  RESOLVE : sees the raw dfs. ONLY job = find + CONFIRM the raw numbers the
            question needs (print matching rows: label + mã số + value), then set
            `cells = {"mô_tả": raw_value, ...}`. No arithmetic allowed.
  COMPUTE : sees ONLY `cells` (NO dfs → physically cannot re-fetch → forced to use
            what RESOLVE confirmed). Applies formula + unit conversion → `result`.

The "force" is structural: COMPUTE has no dataframes in its namespace, so it can't
skip the grounding step. Runs a handful of representative questions and prints
resolve→compute vs plain REPL side by side against the reference.

  PYTHONPATH=src .venv_bge/bin/python scripts/prototype_resolve_compute.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

DEBUG = os.environ.get("DEBUG") == "1"

sys.path.insert(0, "src")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.graph import make_initial_state
from finance_qa.modules.data.service import load_node as load
from finance_qa.modules.rag.service import make_retrieve_node as make_retrieve
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.codegen.repl import (
    _build_tool_repl_namespace,
    _render_schema_for_tool_repl,
    _strip_imports,
    _LANGCHAIN_REPL_OUTPUT_CAP,
    _LANGCHAIN_REPL_MAX_TOKENS,
    _LANGCHAIN_REPL_TEMPERATURE,
)
from finance_qa.modules.tools.python_exec import exec_in_namespace
from finance_qa.core.llm import get_chat_model

CFG = FinanceAgentConfig()
_understand = make_understand(CFG)
_retrieve = make_retrieve(CFG)

_R_STEPS = 6   # resolve is a lookup task — should converge fast
_C_STEPS = 5   # compute is pure arithmetic on a tiny dict


# ── prompts (local to the prototype) ────────────────────────────────────────

RESOLVE_SYSTEM = """\
Bạn là trợ lý TÌM SỐ trong báo cáo tài chính. Việc DUY NHẤT của bạn: tìm và XÁC
NHẬN các con số THÔ mà câu hỏi cần — KHÔNG tính toán (không cộng/trừ/nhân/chia,
không đổi đơn vị).

Câu hỏi: {question}

Namespace có sẵn: {df_vars}, pd, np, get_metric, get_val. KHÔNG import, KHÔNG đọc file.

Schema các DataFrame:
{schema_blocks}

Hàm tiện ích:
  get_metric(metric_id, year, ticker=None) → chỉ cho chỉ tiêu TỔNG QUÁT chuẩn
    (net_revenue, gross_profit, net_profit, total_assets, total_debt, equity,
     current_assets, short_term_debt, profit_before_tax, interest_expense,
     net_cash_operating, ...). Trả số THÔ (đồng).
  get_val(df, keyword, col=None) → dòng đầu chứa keyword → giá trị (số thô).

Quy trình BẮT BUỘC:
1. Xác định câu hỏi cần những con số THÔ nào. Nếu là câu nhiều bước/nhiều năm
   ("năm có X cao nhất thì Y"), lấy ĐỦ số thô cho MỌI năm ứng viên (cả X lẫn Y),
   để bước sau còn chọn được — đừng tự chọn năm ở đây.
2. Với TỪNG con số: print dòng khớp (nhãn + 'Mã số' nếu có + giá trị) để tự xác
   nhận đúng khoản mục/năm. Với khoản mục nêu đích danh (vd "vay ngắn hạn",
   "thu nhập khác", "lãi thuần từ dịch vụ") PHẢI dùng get_val trên df gốc và
   print xác nhận — KHÔNG tin get_metric khớp theo tên.
3. Khi đã xác nhận đủ, gán ĐỒNG THỜI hai dict:
     cells = {{"mô_tả_rõ_ràng_kèm_năm": số_thô, ...}}
     units = {{"mô_tả_rõ_ràng_kèm_năm": "đơn_vị_gốc", ...}}
   Đơn vị gốc là đơn vị của SỐ THÔ vừa lấy, ĐỌC TỪ NGUỒN — KHÔNG phải đơn vị câu
   hỏi muốn:
     - lấy từ get_val trên cột có chữ "Triệu đồng" → "triệu đồng"
     - lấy từ get_val trên cột "Tỷ đồng"          → "tỷ đồng"
     - lấy từ get_metric (chỉ tiêu chuẩn)          → "đồng"
     - nếu bản thân đã là tỷ số (D/E, ROE, biên…)  → "lần"
   Ví dụ: cells = {{"no_phai_tra_2022": 4.5e13, "von_csh_2022": 9.0e13}}
          units = {{"no_phai_tra_2022": "đồng",  "von_csh_2022": "đồng"}}
   Giá trị cells là số THÔ (chưa đổi đơn vị). KHÔNG gán result, KHÔNG tính toán."""

COMPUTE_SYSTEM = """\
Bạn là trợ lý TÍNH TOÁN tài chính. Bạn KHÔNG có bảng dữ liệu — chỉ có dict `cells`
chứa các số THÔ đã được xác nhận sẵn, kèm ĐƠN VỊ GỐC của từng số:

{cells_preview}

Câu hỏi: {question}
Đơn vị đầu ra yêu cầu: {unit_hint}

Namespace: cells, pd, np. Dùng run_code() để tính, print() để kiểm tra.

Công thức VAS thường gặp:
  D/E      = total_debt / equity
  ROE      = net_profit / equity
  ROA      = net_profit / total_assets
  ICR/lãi vay = (profit_before_tax + abs(interest_expense)) / abs(interest_expense)
  Biên LN gộp = gross_profit / net_revenue
  Thanh toán hiện hành = current_assets / short_term_debt
  Lưu ý interest_expense thường là số ÂM → dùng abs().

Với câu nhiều bước ("năm có X cao nhất thì Y"): tính X cho từng năm từ `cells`,
chọn năm thỏa điều kiện, RỒI mới lấy Y của đúng năm đó (không lấy max của Y).
Với "chênh lệch A so với B" / "giữa A và B": giữ thứ tự xuất hiện → A - B.

ĐƠN VỊ (hay sai — làm CẨN THẬN): mỗi số trong cells có ĐƠN VỊ GỐC ghi kèm ở trên.
Phải đổi từ ĐƠN VỊ GỐC sang đơn vị câu hỏi "{unit_hint}", KHÔNG giả định số thô là
đồng. Quy đổi về đồng trước cho dễ: tỷ đồng ×1e9 ; triệu đồng ×1e6 ; nghìn tỷ ×1e12 ;
đồng ×1 ; "lần"/tỷ số giữ nguyên. Rồi từ đồng sang đích: tỷ đồng /1e9 ; triệu đồng
/1e6 ; nghìn tỷ /1e12.
  Ví dụ: cells["x"]=467956 đơn vị gốc "triệu đồng", câu hỏi muốn "triệu đồng"
         → GIỮ NGUYÊN 467956 (đừng chia 1e6!).
  Nếu là tỷ số (D/E, ROE, biên…): "%" → ×100 nếu đang thập phân ; "lần" → giữ nguyên.
  print cả số trước và sau khi đổi, ghi rõ nhân/chia 10^mấy.

print kiểm tra rồi gán  result = <số cuối cùng>  (chương trình dừng khi thấy result)."""


# ── a generic tool-calling loop (shared by both nodes) ───────────────────────

def _loop(system: str, kickoff: str, namespace: dict, sentinel: str, max_steps: int):
    """Run a forced-tool loop until code sets `sentinel` in namespace. Returns the
    sentinel value (or None). `sentinel` is 'cells' for resolve, 'result' for compute."""
    code_history: list[str] = []

    @tool
    def run_code(code: str) -> str:
        """Chạy code Python/pandas. print() để xem giá trị."""
        clean = _strip_imports(code)
        out = exec_in_namespace(clean, namespace, include_stdout_on_error=True)
        code_history.append(clean)
        return out[:_LANGCHAIN_REPL_OUTPUT_CAP] + (
            "\n...(truncated)" if len(out) > _LANGCHAIN_REPL_OUTPUT_CAP else ""
        )

    llm = get_chat_model(
        thinking=False,
        max_tokens=_LANGCHAIN_REPL_MAX_TOKENS,
        temperature=_LANGCHAIN_REPL_TEMPERATURE,
    ).bind_tools([run_code], tool_choice="required")

    messages: list = [SystemMessage(system), HumanMessage(kickoff)]
    last_err = None
    stuck = 0
    for _ in range(max_steps):
        try:
            ai: AIMessage = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001
            messages.append(HumanMessage(
                "Yêu cầu lỗi (có thể code quá dài). Viết code THẬT NGẮN 1–2 dòng."))
            continue
        messages.append(ai)
        if not ai.tool_calls:
            break
        turn_out, turn_err = [], False
        for tc in ai.tool_calls:
            out = run_code.invoke(tc["args"])
            messages.append(ToolMessage(content=out, tool_call_id=tc["id"]))
            turn_out.append(out)
            if DEBUG:
                cap = 100000 if DEBUG else 300
                print(f"    ┌─[{sentinel}] CODE: {tc['args'].get('code','')[:cap]}")
                print(f"    └─ OUT: {out[:cap]}")
            if any(k in out for k in ("Error", "Traceback", "Exception")):
                turn_err = True

        # Commit check FIRST, regardless of error: if the code set the sentinel to a
        # valid value, take it — a stray error later in the same blob must not discard
        # a value that was already assigned (this was the "no cells" bug).
        val = namespace.get(sentinel)
        if sentinel == "cells" and isinstance(val, dict) and val:
            return val, code_history
        if sentinel == "result" and val is not None and not turn_err:
            try:
                f = float(val)
                if math.isfinite(f) and f != 0.0:
                    return f, code_history
            except (TypeError, ValueError):
                pass
            namespace.pop("result", None)

        # Stuck detection on repeated identical output (error OR clean — the model
        # loops on the same blob without ever committing the sentinel).
        joined = "\n".join(turn_out)
        stuck = stuck + 1 if joined == last_err else 0
        last_err = joined
        if turn_err and stuck >= 1:
            messages.append(HumanMessage(
                "Bạn lặp cùng một lỗi. Chạy TỪNG bước nhỏ: print riêng từng "
                "get_metric()/get_val() để tìm cái trả None, sửa nhãn/năm/ticker."))
        elif not turn_err and stuck >= 1 and sentinel == "cells":
            messages.append(HumanMessage(
                "Bạn đã in ra các số cần rồi. NGAY BÂY GIỜ hãy gán biến cells với các "
                "GIÁ TRỊ SỐ thật (không dùng ... hay chuỗi), ví dụ: "
                "cells = {\"ten_ro_rang_2020\": 467956.0}. Chỉ gán cells, đừng in lại."))
        if stuck >= 3:
            break
    return namespace.get(sentinel) if sentinel == "cells" else None, code_history


# ── resolve → compute ────────────────────────────────────────────────────────

def resolve_compute(question, frames, names, unit_hint):
    # RESOLVE: raw dfs in namespace
    ns_r = _build_tool_repl_namespace(frames, names)
    cells, r_hist = _loop(
        RESOLVE_SYSTEM.format(
            question=question, df_vars=", ".join(frames),
            schema_blocks=_render_schema_for_tool_repl(frames, names)),
        "Tìm và XÁC NHẬN từng con số thô câu hỏi cần, rồi gán cells = {...}.",
        ns_r, "cells", _R_STEPS)
    if not isinstance(cells, dict) or not cells:
        return 0.0, cells, "resolve: no cells"
    units = ns_r.get("units") if isinstance(ns_r.get("units"), dict) else {}

    # COMPUTE: ONLY cells — no dfs (the structural gate)
    import numpy as np
    ns_c = {"cells": dict(cells), "pd": __import__("pandas"), "np": np}
    preview = "\n".join(
        f"  cells[{k!r}] = {v}   (đơn vị gốc: {units.get(k, '?')})"
        for k, v in cells.items())
    result, c_hist = _loop(
        COMPUTE_SYSTEM.format(
            cells_preview=preview, question=question,
            unit_hint=unit_hint or "(không nêu — giữ nguyên giá trị gốc)"),
        "Tính từ cells rồi gán result = <đáp án cuối>.",
        ns_c, "result", _C_STEPS)
    return (result if result is not None else 0.0), cells, ""


# ── live prefix + comparison harness ─────────────────────────────────────────

def live_prefix(qid, question):
    st = make_initial_state(qid, question)
    st.update(_understand(st)); st.update(_retrieve(st)); st.update(load(st))
    return st


def _match(pred, ref):
    if pred is None:
        return False
    pred = float(pred)
    return abs(pred - ref) / abs(ref) < 0.01 if abs(ref) > 1e-9 else abs(pred) < 1e-9


REPRESENTATIVE = [105, 294, 34, 378, 387, 363, 415, 426]


def main():
    rows = {r["qid"]: r for r in map(json.loads, open(
        "artifacts/runs/measure_repl_rescue.jsonl", encoding="utf-8"))}
    ids = [int(x) for x in sys.argv[1:]] or REPRESENTATIVE

    print(f"{'qid':>4} {'ref':>10} {'REPL':>12} {'R→C':>12}  repl  rc   sec")
    print("-" * 72)
    n_repl = n_rc = 0
    for qid in ids:
        r = rows[qid]
        q, ref = r["question"], r["ref"]
        st = live_prefix(qid, q)
        frames, names = st.get("frames") or {}, st.get("names") or {}
        unit = st.get("unit_hint")
        if not frames:
            print(f"{qid:>4}  no frames"); continue

        t0 = time.monotonic()
        rc, cells, note = resolve_compute(q, frames, names, unit)
        t_rc = time.monotonic() - t0

        repl_pred = r["pred"]  # reuse the REPL number already measured (same live path)

        ok_repl, ok_rc = _match(repl_pred, ref), _match(rc, ref)
        n_repl += ok_repl; n_rc += ok_rc
        rp = "None" if repl_pred is None else f"{float(repl_pred):.4g}"
        print(f"{qid:>4} {ref:>10.4g} {rp:>12} {rc:>12.4g}  "
              f"{'OK' if ok_repl else '·':>4} {'OK' if ok_rc else '·':>3} {t_rc:>5.0f}  {note}")
        print(f"       cells={ {k: f'{v:.4g}' if isinstance(v,(int,float)) else v for k,v in (cells or {}).items()} }")

    print("-" * 72)
    print(f"REPL (measured): {n_repl}/{len(ids)}    resolve→compute: {n_rc}/{len(ids)}")


if __name__ == "__main__":
    main()
