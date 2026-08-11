"""Dump every code block + output the REPL executes for one qid, plus final answer."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

import finance_qa.modules.codegen.repl as repl
from finance_qa.modules.data.table_store import load_frame

QID = int(sys.argv[1]) if len(sys.argv) > 1 else 363


def load_case(qid):
    exp = q = tids = None
    for line in open("data/eval/extended_gold.jsonl"):
        r = json.loads(line)
        if r["id"] == qid:
            exp = r["answer"]; break
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] == qid:
            q, tids = r["question"], r["table_ids"]; break
    return q, tids, exp


def main():
    question, table_ids, expected = load_case(QID)
    print(f"qid={QID}  expected={expected}")
    print(f"Q: {question}")
    print(f"tables ({len(table_ids)}): {table_ids}\n")

    names = {f"df{i}": tid for i, tid in enumerate(table_ids, 1)}
    frames = {v: load_frame(t) for v, t in names.items()}
    for v, t in names.items():
        print(f"  {v} = {t}  cols={list(frames[v].columns)}")
    print()

    orig = repl.exec_in_namespace
    n = {"i": 0}

    def spy(code, ns):
        n["i"] += 1
        out = orig(code, ns)
        print(f"----- exec #{n['i']} -----")
        print(code)
        print(f"  >>> OUTPUT: {out}")
        print(f"  >>> result var now: {ns.get('result')!r}")
        print()
        return out

    repl.exec_in_namespace = spy
    res = repl.repl_generate(question, frames, names)
    repl.exec_in_namespace = orig

    print("===== FINAL =====")
    print(f"answer={res['answer']}  expected={expected}  steps={res.get('repl_steps')}  error={res.get('error')}")


if __name__ == "__main__":
    main()
