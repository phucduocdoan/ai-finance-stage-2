"""Print the exact system + user messages the REPL sends on turn 1 and a mid turn."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

import finance_qa.modules.codegen.repl as repl
from finance_qa.modules.data.table_store import load_frame

QID = 363
SHOW_TURNS = {1, 5}


def load_case(qid):
    q = tids = None
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] == qid:
            q, tids = r["question"], r["table_ids"]; break
    return q, tids


def main():
    question, table_ids = load_case(QID)
    names = {f"df{i}": tid for i, tid in enumerate(table_ids, 1)}
    frames = {v: load_frame(t) for v, t in names.items()}

    orig = repl._allm_tool_call
    turn = {"n": 0}

    async def spy(messages):
        turn["n"] += 1
        if turn["n"] in SHOW_TURNS:
            print(f"\n################ TURN {turn['n']} ################")
            for m in messages:
                print(f"\n----- role={m['role']} -----")
                print(m["content"])
        return await orig(messages)

    repl._allm_tool_call = spy
    repl.repl_generate(question, frames, names)
    repl._allm_tool_call = orig


if __name__ == "__main__":
    main()
