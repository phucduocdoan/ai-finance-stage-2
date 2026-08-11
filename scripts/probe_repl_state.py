"""Verify the REPL now carries state across steps.

Runs one previously-failing REPL question end-to-end and prints the STATE block
fed to the model on each turn, so we can see the ledger + scalar snapshot grow
(instead of the old sliding window wiping memory). Then prints final vs expected.

    PYTHONPATH=src .venv_bge/bin/python scripts/probe_repl_state.py 392
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

import finance_qa.modules.codegen.repl as repl
from finance_qa.modules.data.table_store import load_frame

QID = int(sys.argv[1]) if len(sys.argv) > 1 else 392


def load_case(qid: int):
    ans = None
    for line in open("data/eval/extended_gold.jsonl"):
        r = json.loads(line)
        if r["id"] == qid:
            ans = r
            break
    tids = None
    q = None
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] == qid:
            tids = r["table_ids"]
            q = r["question"]
            break
    return q, tids, ans["answer"]


def main() -> None:
    question, table_ids, expected = load_case(QID)
    print(f"qid={QID}  expected={expected}")
    print(f"tables={table_ids}")
    print(f"Q: {question}\n")

    names = {f"df{i}": tid for i, tid in enumerate(table_ids, 1)}
    frames = {v: load_frame(t) for v, t in names.items()}

    # Wrap _llm_tool_call to show the STATE block the model receives each turn.
    orig = repl._llm_tool_call
    turn = {"n": 0}

    def spy(messages):
        turn["n"] += 1
        user = messages[-1]["content"]
        state = user.split("TRẠNG THÁI", 1)
        print(f"===== TURN {turn['n']}: context handed to model =====")
        if len(state) > 1:
            print("TRẠNG THÁI" + state[1][:1500])
        else:
            print("(no state yet — first turn)")
        print()
        return orig(messages)

    repl._llm_tool_call = spy
    result = repl.repl_generate(question, frames, names)
    repl._llm_tool_call = orig

    print("===== RESULT =====")
    print(f"answer   = {result['answer']}")
    print(f"expected = {expected}")
    print(f"steps    = {result.get('repl_steps')}")
    print(f"error    = {result.get('error')}")
    ok = result["answer"] is not None and abs(float(result["answer"]) - expected) <= 0.01 * abs(expected)
    print(f"MATCH    = {ok}")


if __name__ == "__main__":
    main()
