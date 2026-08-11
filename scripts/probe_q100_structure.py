"""Trace q100: is the failure STRUCTURAL (should've been prevented) or LOGIC?

Shows: (1) what the model is given (rendered tables + profile), (2) the plan it
returns, (3) the exact binding column vs real columns, (4) why repair_binding_column
does/doesn't resolve it.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.codegen.generator import build_plan_prompt, render_tables
from finance_qa.modules.codegen.ir import parse_plan_response
from finance_qa.modules.codegen.prompts import PLAN_PROMPT  # noqa: F401
from finance_qa.modules.codegen.repairs import repair_binding_column
from finance_qa.modules.rag.judge import call_llm

TABLES = [
    "BVH_financial_statements_2018_consolidated|15",
    "BVH_financial_statements_2018_consolidated|16",
]
QUESTION = ("Tổng số lượng cổ phần của Tập đoàn Bảo Việt (BVH) vào cuối năm 2018 "
            "là bao nhiêu cổ phần?")


def main():
    names = {f"df{i}": t for i, t in enumerate(TABLES, 1)}
    frames = {v: load_frame(t) for v, t in names.items()}

    print("========== WHAT THE MODEL SEES (rendered, full rows) ==========")
    print(render_tables(frames, names, None))
    print()

    print("========== PLANNER OUTPUT ==========")
    prompt = build_plan_prompt(QUESTION, frames, names)
    raw = call_llm(prompt, thinking=False, max_tokens=4096)
    plan = parse_plan_response(raw)
    print(json.dumps(plan, ensure_ascii=False, indent=2) if plan else f"(no JSON)\n{raw[:800]}")
    print()

    if not plan:
        return
    print("========== BINDINGS vs REAL COLUMNS ==========")
    for b in plan.get("bindings", []):
        var = b.get("variable")
        col = b.get("column")
        exists = var in frames and col in frames[var].columns
        print(f"  {b.get('id')}: var={var} col={col!r}  EXISTS={exists}")
        if var in frames:
            print(f"     real cols: {[str(c) for c in frames[var].columns]}")

    print("\n========== repair_binding_column RESULT ==========")
    repaired, changes = repair_binding_column(plan, frames)
    print("changes:", changes or "(none — could not resolve)")
    for b in repaired.get("bindings", []):
        var, col = b.get("variable"), b.get("column")
        exists = var in frames and col in frames[var].columns
        print(f"  {b.get('id')}: col={col!r}  EXISTS_NOW={exists}")


if __name__ == "__main__":
    main()
