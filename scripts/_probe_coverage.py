"""Probe statement-type / metric coverage that live retrieval delivers."""
import sys, json
sys.path.insert(0, "src")
from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.rag.service import make_retrieve_node as make_retrieve
from finance_qa.modules.data.service import load_node as load
from finance_qa.modules.data.canonical import _get_table_meta
from finance_qa.modules.codegen.formula import _collect_canonical

_cfg = FinanceAgentConfig()
understand = make_understand(_cfg)
retrieve_targeted = make_retrieve(_cfg)

qid = int(sys.argv[1])
gold = {int(json.loads(l)["id"]): json.loads(l)["question"]
        for l in open("data/eval/extended_gold.jsonl")}
q = gold[qid]
st = {"id": qid, "question": q, "errors": []}
st.update(understand(st))
print("tickers", st["tickers"], "years", st["years"], "op", st["operation"])
st.update(retrieve_targeted(st))
tids = st["table_ids"]
print(f"\n{len(tids)} tables:")
for t in tids:
    m = _get_table_meta(t)
    print(f"  {m.get('ticker'):5} {m.get('statement_type'):16} {t.split('|')[-1]:>4}  maso={m.get('has_ma_so_column')}")
st.update(load(st))
data = _collect_canonical(st.get("frames") or {}, st.get("names") or {})
print("\ncanonical per ticker/year (key metrics):")
for tk in sorted(data):
    for yr in sorted(data[tk]):
        m = data[tk][yr]
        print(f"  {tk} {yr}: CA={m.get('current_assets') is not None} "
              f"inv={m.get('inventory') is not None} "
              f"STD(310)={m.get('short_term_debt') is not None} "
              f"equity={m.get('owners_equity') is not None} "
              f"CFO={m.get('net_cash_operating') is not None}")
