"""Compare doc_text variants on the *dense* channel, which diag_repr.py never did.

diag_repr.py measured representations with BM25 only. That matters because the
two channels react to boilerplate in opposite ways: BM25 discounts a segment that
appears in half the corpus via IDF, a bi-encoder cannot -- it averages the
segment into the vector regardless. The production note in
preprocessing/document_text.py ("both fields stay in doc_text: BM25 discounts the
boilerplate by IDF anyway") is therefore an argument about BM25 that was never
tested on dense.

Measured here: rank of each GT table among *the question's own candidates* (the
hard-filtered slice), per variant, dense only -- diag_repr.py already swept these
variants on BM25, and rebuilding a 146k-doc BM25 per variant made this run take
longer than the encoding it exists to measure. Full-corpus embedding is not
needed and not done: retrieval only ever scores within that slice, so embedding
the union of the 24 questions' candidates (~5k tables) gives numerically the same
ranks as the 146k index would. data/indexes/tables_dense.npy is never touched.

Runs on CPU by default -- the GPU is shared and usually full, and ~5k short docs
per variant is minutes. Pass --cuda if it happens to be free.

  .venv_bge/bin/python scripts/diag_repr_dense.py
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict

import _bootstrap  # noqa: F401

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from finance_qa.core.paths import EVALSET_PATH
from finance_qa.modules.data.preprocessing.document_text import statement_label
from finance_qa.modules.rag.indexing import dense
from finance_qa.modules.rag.candidates import strip_entity
from finance_qa.modules.rag.retrievers.filters import index_by_ticker_year, load_tables, shortlist


KS = (5, 10, 15, 20, 30, 50)


def _parts(rec: dict) -> dict[str, str]:
    return {
        "label": statement_label(rec),
        "note": rec.get("note_title") or "",
        "section": rec.get("section_title") or "",
        "rows": " ".join(rec.get("first_col_labels") or []),
        "header": rec.get("header_flat") or "",
    }


def _join(rec: dict, order: tuple[str, ...]) -> str:
    p = _parts(rec)
    return " | ".join(p[k] for k in order if p[k].strip())


# Each variant is just a segment order; dropping a name drops the segment.
VARIANTS: dict[str, tuple[str, ...]] = {
    "full (production)": ("label", "note", "section", "rows", "header"),
    "no section": ("label", "note", "rows", "header"),
    "no header": ("label", "note", "section", "rows"),
    "no section+header": ("label", "note", "rows"),
    "section moved last": ("label", "note", "rows", "header", "section"),
}


def load_encoder(use_cuda: bool):
    tok = AutoTokenizer.from_pretrained(dense.MODEL)
    dtype = torch.float16 if use_cuda else torch.float32
    model = AutoModel.from_pretrained(dense.MODEL, dtype=dtype).eval()
    if use_cuda:
        model = model.cuda()
    return tok, model


@torch.no_grad()
def encode(texts: list[str], tok, model, batch: int, use_cuda: bool) -> np.ndarray:
    out = np.empty((len(texts), model.config.hidden_size), dtype=np.float32)
    order = np.argsort([len(t) for t in texts])  # length-sorted: padding is the cost
    for start in range(0, len(order), batch):
        idx = order[start : start + batch]
        enc = tok([texts[i] for i in idx], padding=True, truncation=True,
                  max_length=dense.MAX_LEN, return_tensors="pt")
        if use_cuda:
            enc = enc.to("cuda")
        vecs = model(**enc).last_hidden_state[:, 0]
        vecs = torch.nn.functional.normalize(vecs, p=2, dim=-1)
        out[idx] = vecs.float().cpu().numpy()
    return out


def summarize(ranks: list[int], n_groups: int, allhit: list[bool]) -> str:
    rs = sorted(ranks)
    at = "  ".join(f"@{k} {sum(r <= k for r in rs) / n_groups:5.1%}" for k in KS)
    return f"{at}  med #{rs[len(rs) // 2]:>3}  all@20 {sum(allhit) / len(allhit):5.1%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuda", action="store_true", help="GPU is shared; only if free")
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    evalset = json.loads(EVALSET_PATH.read_text(encoding="utf-8"))
    tables = load_tables()
    index = index_by_ticker_year(tables)
    by_key = {f"{t['report_id']}|{t['table_pos']}": t for t in tables}

    names_by_ticker: dict[str, set[str]] = defaultdict(set)
    for t in tables:
        for tok_ in re.findall(r"\w+", (t.get("company_name") or "").lower()):
            names_by_ticker[t["ticker"]].add(tok_)

    # Shortlists are variant-independent, so they are computed once.
    work = []
    for e in evalset:
        if not e["gt_tables"]:
            continue
        cands = [f"{t['report_id']}|{t['table_pos']}" for t in shortlist(e, index, all_tables=tables)]
        names = set().union(*(names_by_ticker[t] for t in e["tickers"])) if e["tickers"] else set()
        work.append((e, cands, strip_entity(e["question"], names)))

    slice_keys = sorted({k for _, cands, _ in work for k in cands})
    row_of = {k: i for i, k in enumerate(slice_keys)}
    print(f"{len(work)} câu có GT bảng, {len(slice_keys):,} bảng ứng viên duy nhất")
    print(f"encoder: {'cuda fp16' if args.cuda else 'cpu fp32'}\n")

    tok, model = load_encoder(args.cuda)
    queries = [stripped for _, _, stripped in work]
    qvecs = encode(queries, tok, model, args.batch, args.cuda)

    for vname, order in VARIANTS.items():
        texts = {k: _join(by_key[k], order) for k in slice_keys}
        t0 = time.perf_counter()
        docvecs = encode([texts[k] for k in slice_keys], tok, model, args.batch, args.cuda)

        ranks: list[int] = []
        allhit: list[bool] = []
        for qi, (e, cands, _) in enumerate(work):
            rows = np.array([row_of[k] for k in cands])
            sims = docvecs[rows] @ qvecs[qi]
            dense_order = [cands[i] for i in np.argsort(-sims)]
            per_q = []
            for g in e["gt_tables"]:
                present = [m for m in g if m in row_of and m in cands]
                if not present:
                    continue  # GT outside the hard filter: not this diagnostic's axis
                per_q.append(min(dense_order.index(m) + 1 for m in present))
            ranks.extend(per_q)
            allhit.append(all(r <= 20 for r in per_q))

        dt = time.perf_counter() - t0
        mean_len = np.mean([len(texts[k]) for k in slice_keys])
        print(f"{vname:<20} ({mean_len:>4.0f} ký tự, {dt / 60:.1f} min)")
        print(f"  dense  {summarize(ranks, len(ranks), allhit)}\n", flush=True)

    print(f"(n={len(ranks)} nhóm GT nằm trong hard filter; rank trong candidate set của câu đó,")
    print(" all@20 = tỉ lệ câu có MỌI nhóm GT trong top-20)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
