"""Trace ONE question through the graph up to load, then run the REPL loop with
full visibility: the schema the model sees, every code turn, tool output, and the
final namespace['result']. Read-only diagnostic — no writes, no server restart."""
from __future__ import annotations

import sys
sys.path.insert(0, "src")

import json
from finance_qa.agents.finance.graph import make_initial_state
from finance_qa.agents.finance.understand import make_understand
from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.data.service import load_node as load
from finance_qa.modules.rag.service import make_retrieve_node as make_retrieve
from finance_qa.modules.codegen import repl as R

QID = int(sys.argv[1]) if len(sys.argv) > 1 else 582

# question text
from finance_qa.core.paths import QUESTION_METADATA_PATH
qmap = {int(r["id"]): r for r in map(json.loads, filter(str.strip, QUESTION_METADATA_PATH.open(encoding="utf-8")))}
q = qmap[QID]["question"]
print(f"Q{QID}: {q}\n")

cfg = FinanceAgentConfig()
st = make_initial_state(QID, q)
st.update(make_understand(cfg)(st))
print("understand →", {k: st.get(k) for k in ("operation", "answer_shape", "tickers", "years", "metric", "multi_year")})
st.update(make_retrieve(cfg)(st))
print("retrieve → tables:", st.get("table_ids"))
st.update(load(st))
frames, names = st.get("frames") or {}, st.get("names") or {}
print("load → frames:", list(frames))

print("\n===== SCHEMA the model sees =====")
print(R._render_schema_for_tool_repl(frames, names))

print("\n===== actual note-table rows =====")
import pandas as pd
pd.set_option("display.max_rows", 60); pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
for var, df in frames.items():
    print(f"\n--- {var} ({names[var]}) shape={df.shape} ---")
    print(df.to_string()[:3000])

# ---- now run the repl loop by hand, printing each turn ----
print("\n===== REPL LOOP =====")
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from finance_qa.modules.codegen.prompts import REPL_SYSTEM
from finance_qa.core.llm import get_chat_model

namespace = R._build_tool_repl_namespace(frames, names)
code_history = []

@tool
def run_code(code: str) -> str:
    """Chạy code Python/pandas."""
    from finance_qa.modules.tools.python_exec import exec_in_namespace
    clean = R._strip_imports(code)
    out = exec_in_namespace(clean, namespace, include_stdout_on_error=True)
    code_history.append(clean)
    return out[: R._LANGCHAIN_REPL_OUTPUT_CAP]

llm = get_chat_model(
    thinking=False,
    max_tokens=R._LANGCHAIN_REPL_MAX_TOKENS,
    temperature=R._LANGCHAIN_REPL_TEMPERATURE,
).bind_tools([run_code], tool_choice="required")
messages = [
    SystemMessage(REPL_SYSTEM.format(question=q, unit_hint=st.get("unit_hint") or "(không nêu — giữ nguyên giá trị gốc)", df_vars=", ".join(frames), schema_blocks=R._render_schema_for_tool_repl(frames, names))),
    HumanMessage("Tính toán từng bước, rồi gán result = <đáp án cuối>."),
]
for step in range(R._LANGCHAIN_REPL_MAX_STEPS):
    ai = llm.invoke(messages)
    messages.append(ai)
    if not ai.tool_calls:
        print(f"[turn {step}] no tool_call, text: {ai.content[:300]}"); break
    for tc in ai.tool_calls:
        code = tc["args"].get("code", "")
        print(f"\n[turn {step}] CODE:\n{code}")
        out = run_code.invoke(tc["args"])
        print(f"[turn {step}] OUT: {out[:500]}")
        messages.append(ToolMessage(content=out, tool_call_id=tc["id"]))
    r = namespace.get("result")
    if r is not None:
        print(f"\n>>> result = {r}")
        try:
            fr = float(r)
            if fr == 0.0:
                print("    (result==0 → cleared, continue)"); namespace.pop("result", None)
            else:
                break
        except Exception:
            namespace.pop("result", None)

print("\nEXPECTED (582)=13.7498  (605)=-20.734  etc.")
