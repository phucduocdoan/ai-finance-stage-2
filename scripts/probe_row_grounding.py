"""Probe: measure the ceiling of row-label grounding for the `codegen` solver.

Throwaway measurement, not a pipeline step. `codegen` addresses every row
positionally (`df1.iloc[13]["Năm nay"]`) and its own `diag.target_row` is a bare
digit or empty almost every time, so nothing today checks which row the model
actually landed on. The proposed fix is to make codegen emit the row's *printed
label*, resolve label -> index deterministically against the frame, and
repair/reject on mismatch. This script measures, from artifacts already on
disk, what such a fix could realistically buy before anyone builds it:

  M1  self-consistency / detection rate over all 520 codegen accesses
      (no gold needed) -- what a guard could notice without knowing the answer.
  M2  oracle ceiling on the gold73 subset -- what happens if codegen had used
      the *true* row index instead of its own guess.
  M3  is the gold row label even findable in the frame the model was shown.
  M4  M1/M2 split by single-frame vs multi-frame query.
  M5  visibility -- would the gold row have been rendered at all, given
      `_grid`'s head/tail elision and `max_colwidth=70` truncation.
  M6  the achievable (not oracle) number: run the existing deterministic
      `lookup.search_rows` machinery against the label at the position the
      model used, and report recovery vs. false-alarm rates.

Makes zero LLM/API calls. Read-only against `data/` and the run artifact.

Usage:
  PYTHONPATH=src:scripts .venv_bge/bin/python scripts/probe_row_grounding.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
from score_gold75 import TOL, close, load_gold  # noqa: E402

from finance_qa.modules.data.table_store import load_frame  # noqa: E402
from finance_qa.modules.solve.common.context import _HEAD_ROWS, _MAX_GRID_ROWS, _TAIL_ROWS  # noqa: E402
from finance_qa.modules.solve.common.lookup import _norm, _score, label_column, search_rows  # noqa: E402
from finance_qa.modules.solve.solvers.cell_locator import direct_metric_phrases  # noqa: E402

RUN_PATH = Path("artifacts/runs/full1012_v7.jsonl")

ACCESS = re.compile(r'(df\d+)\.iloc\[(-?\d+)\]\["([^"]*)"\]')
CSV_PATH = re.compile(r"^data/(.+)_table_(\d+)\.csv$")
TABLE_ID_RE = re.compile(r"[A-Za-z0-9_]+\|\d+")
GRID_MAX_COLWIDTH = 70


@lru_cache(maxsize=None)
def _frame(table_id: str) -> pd.DataFrame:
    return load_frame(table_id)


def load_runs() -> dict[int, dict]:
    runs: dict[int, dict] = {}
    for line in RUN_PATH.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        runs[rec["id"]] = rec
    return runs


def evidence_map(item: dict) -> dict[str, str]:
    """`variable -> table_id`, derived from `item.evidence[*].csv_path`."""
    out: dict[str, str] = {}
    for ev in item.get("evidence") or []:
        m = CSV_PATH.match(ev["csv_path"])
        if m:
            out[ev["variable"]] = f"{m.group(1)}|{m.group(2)}"
    return out


def extract_accesses(query: str) -> list[tuple[str, int, str]]:
    return [(v, int(k), c) for v, k, c in ACCESS.findall(query)]


def distinct_vars(accesses: list[tuple[str, int, str]]) -> set[str]:
    return {v for v, _, _ in accesses}


def tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) >= 3}


def row_has_numeric(df: pd.DataFrame, k: int, label_col) -> bool:
    row = df.iloc[k]
    for c in df.columns:
        if c == label_col:
            continue
        v = row[c]
        if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
            return True
    return False


def resolve_label(table_id: str, k: int) -> tuple[str | None, pd.DataFrame, object]:
    """(label at position k, frame, label column). label is None if k is out of range."""
    df = _frame(table_id)
    col = label_column(df)
    if not (0 <= k < len(df)):
        return None, df, col
    return df.iloc[k][col], df, col


# ---------------------------------------------------------------------------
# M1: self-consistency / detection rate
# ---------------------------------------------------------------------------

def m1(codegen_recs: list[dict]) -> None:
    print("\n=== M1: self-consistency / detection rate (all codegen accesses) ===")
    access_bucket: Counter[str] = Counter()
    # per-question worst bucket, worst-first
    order = ["out_of_range", "empty_or_nan", "header_no_numeric", "no_token_overlap", "looks_fine"]
    rank = {name: i for i, name in enumerate(order)}
    question_bucket: Counter[str] = Counter()
    multi_access: Counter[str] = Counter()
    multi_question: Counter[str] = Counter()
    single_access: Counter[str] = Counter()
    single_question: Counter[str] = Counter()
    n_multi_q = n_single_q = 0

    for rec in codegen_recs:
        item = rec["item"]
        query = item["pandas_query"]
        emap = evidence_map(item)
        accesses = extract_accesses(query)
        target_row = str((rec.get("diag") or {}).get("target_row") or "")
        question = item["question"]
        qtok = tokens(question) | tokens(target_row)
        multi_frame_q = len(distinct_vars(accesses)) > 1
        worst = rank["looks_fine"]
        for var, k, _col in accesses:
            table_id = emap.get(var)
            if table_id is None:
                bucket = "unmapped_variable"
            else:
                label, df, col = resolve_label(table_id, k)
                if label is None:
                    bucket = "out_of_range"
                elif str(label).strip() == "" or (isinstance(label, float) and np.isnan(label)):
                    bucket = "empty_or_nan"
                elif not row_has_numeric(df, k, col):
                    bucket = "header_no_numeric"
                else:
                    ltok = tokens(str(label))
                    bucket = "looks_fine" if (ltok & qtok) else "no_token_overlap"
            access_bucket[bucket] += 1
            (multi_access if multi_frame_q else single_access)[bucket] += 1
            if bucket in rank:
                worst = min(worst, rank[bucket])
        question_bucket[order[worst]] += 1
        if multi_frame_q:
            n_multi_q += 1
            multi_question[order[worst]] += 1
        else:
            n_single_q += 1
            single_question[order[worst]] += 1

    total_acc = sum(access_bucket.values())
    print(f"per-access (n={total_acc}):")
    for name, n in access_bucket.most_common():
        print(f"  {n:5d} ({n/total_acc*100:5.1f}%)  {name}")
    total_q = sum(question_bucket.values())
    print(f"per-question, worst access wins (n={total_q}):")
    for name in order:
        n = question_bucket.get(name, 0)
        print(f"  {n:5d} ({n/total_q*100:5.1f}%)  {name}")

    print(f"\n  -- M4 split: single-frame questions n={n_single_q}, multi-frame n={n_multi_q} --")
    for label, ctr, n in (("single-frame", single_question, n_single_q), ("multi-frame", multi_question, n_multi_q)):
        print(f"  {label} (n={n}):")
        for name in order:
            c = ctr.get(name, 0)
            print(f"    {c:5d} ({c/n*100:5.1f}%)  {name}")


# ---------------------------------------------------------------------------
# gold helpers shared by M2/M3/M5/M6
# ---------------------------------------------------------------------------

def gold_tables_and_labels(row: dict) -> tuple[list[str], list[str]]:
    tids = TABLE_ID_RE.findall(str(row.get("evidence_table_id") or ""))
    labels = [s.strip() for s in str(row.get("evidence_row_label") or "").split(";") if s.strip()]
    return tids, labels


MIN_SCORE = 0.5  # same bar lookup.search_rows uses


def _section_header_above(df: pd.DataFrame, col, i: int) -> str:
    """Nearest preceding row with a label but no numeric cell (a section banner
    like "Ngắn hạn" / "Dài hạn") -- used only to break ties between two rows
    that carry byte-identical labels under different sections."""
    j = i - 1
    while j >= 0:
        if not row_has_numeric(df, j, col):
            return str(df.iloc[j][col])
        j -= 1
    return ""


_PAREN = re.compile(r"\([^)]*\)")


def match_label(df: pd.DataFrame, col, gold_label: str) -> tuple[int | None, str]:
    """Find gold_label's position in df[col].

    Word-overlap scoring (`lookup._score`), not raw string containment: a
    naive substring check matches a bare section header like "Ngắn hạn"
    against a gold label that happens to contain the phrase "(Ngắn hạn,
    ...)", landing on the header row instead of the data row it qualifies.

    `evidence_row_label` is gold's own free-text description and often bundles
    a parenthetical note/table annotation onto the actual line-item phrase
    (e.g. "Lãi vay (Thuyết minh - chi tiết Chi phí tài chính)"); scoring the
    parenthetical's words against every row spuriously favors an unrelated row
    that happens to share note-title vocabulary. Score against the
    parenthetical-stripped phrase first (falling back to the full label if
    that strips everything), same as `direct_metric_phrases` strips short
    parens from the question before treating it as a row-label query.

    Ties break exactly the way `lookup.search_rows` breaks them: shorter
    label wins (`hits.sort(key=lambda h: (-h.score, len(h.label), ...))`).
    Only if score AND length still tie (two rows with byte-identical labels,
    e.g. the same line item repeated under "Ngắn hạn" and "Dài hạn") do we
    fall back to whichever section header above the row shares more tokens
    with gold's full (unstripped) label -- the only signal left once the
    row's own text is a wash.
    """
    core_label = _PAREN.sub(" ", gold_label).strip() or gold_label
    g_tokens = _norm(core_label).split()
    if not g_tokens:
        return None, "not_found"
    scored = []
    for i in range(len(df)):
        lab = str(df.iloc[i][col])
        n = _norm(lab)
        if not n:
            continue
        scored.append((_score(g_tokens, n), i, lab))
    if not scored:
        return None, "not_found"
    best_score = max(s for s, _, _ in scored)
    if best_score < MIN_SCORE:
        return None, "not_found"
    best = [(i, lab) for s, i, lab in scored if s == best_score]
    method = "exact" if best_score >= 1.25 else "token_overlap"
    best.sort(key=lambda t: (len(t[1]), t[0]))
    shortest_len = len(best[0][1])
    tied = [(i, lab) for i, lab in best if len(lab) == shortest_len]
    if len(tied) == 1:
        return tied[0][0], method
    full_tokens = _norm(gold_label).split()
    ranked = []
    for i, lab in tied:
        header_tokens = set(_norm(_section_header_above(df, col, i)).split())
        own_tokens = set(_norm(lab).split())
        bonus = sum(1 for t in full_tokens if t in header_tokens and t not in own_tokens)
        ranked.append((bonus, -i, i))
    ranked.sort(reverse=True)
    return ranked[0][2], method + "+header_tiebreak"


def substitute_and_eval(query: str, var: str, old_k: int, new_k: int, emap: dict[str, str]) -> float | None:
    pat = re.compile(rf'{re.escape(var)}\.iloc\[{old_k}\]')
    new_query = pat.sub(f"{var}.iloc[{new_k}]", query)
    ns = {v: _frame(t) for v, t in emap.items()}
    ns["pd"] = pd
    ns["np"] = np
    try:
        val = eval(new_query, {}, ns)  # noqa: S307 - controlled, offline, read-only frames
    except Exception:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def reeval(query: str, emap: dict[str, str]) -> float | None:
    ns = {v: _frame(t) for v, t in emap.items()}
    ns["pd"] = pd
    ns["np"] = np
    try:
        val = eval(query, {}, ns)  # noqa: S307
    except Exception:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


SIGN_FIX_IDS = {525, 526}


def build_single_cell_stratum(gold: dict[int, dict], runs: dict[int, dict]) -> tuple[list[int], list[int]]:
    """Split the gold73-codegen-36 into (single-table, multi-table) id lists."""
    single, multi = [], []
    for qid, row in gold.items():
        rec = runs.get(qid)
        if rec is None or rec.get("solver") != "codegen":
            continue
        tids, labels = gold_tables_and_labels(row)
        if len(tids) == 1 and len(labels) == 1:
            single.append(qid)
        else:
            multi.append(qid)
    return sorted(single), sorted(multi)


# ---------------------------------------------------------------------------
# M2 + M3
# ---------------------------------------------------------------------------

def m2_m3(gold: dict[int, dict], runs: dict[int, dict], single_ids: list[int], multi_ids: list[int]) -> dict:
    print("\n=== M3: is the gold row label findable in the shown frame? ===")
    print(f"single-table gold-codegen questions: n={len(single_ids)} {single_ids}")
    print(f"multi-table gold-codegen questions (separate stratum, reported not oracle-substituted): "
          f"n={len(multi_ids)} {multi_ids}")

    match_methods: Counter[str] = Counter()
    not_found_detail = []
    resolved: dict[int, tuple[str, str, int, str]] = {}  # qid -> (var, table_id, true_k, method)

    for qid in single_ids:
        row = gold[qid]
        rec = runs[qid]
        item = rec["item"]
        tids, labels = gold_tables_and_labels(row)
        gold_table, gold_label = tids[0], labels[0]
        emap = evidence_map(item)
        var = next((v for v, t in emap.items() if t == gold_table), None)
        if var is None:
            match_methods["table_not_in_query_evidence"] += 1
            not_found_detail.append((qid, gold_table, gold_label, "gold table not among query's evidence"))
            continue
        df = _frame(gold_table)
        col = label_column(df)
        pos, method = match_label(df, col, gold_label)
        match_methods[method] += 1
        if pos is None:
            frame_labels = [str(x) for x in df[col].tolist()]
            not_found_detail.append((qid, gold_table, gold_label, "; ".join(frame_labels[:25])))
        else:
            resolved[qid] = (var, gold_table, pos, method)

    total = sum(match_methods.values())
    print(f"\nmatch method distribution (n={total}):")
    for name, n in match_methods.most_common():
        print(f"  {n:3d} ({n/total*100:5.1f}%)  {name}")
    if not_found_detail:
        print("\nnot-found / no-evidence cases (gold label vs frame labels):")
        for qid, table_id, gold_label, extra in not_found_detail:
            print(f"  q{qid}  table={table_id}")
            print(f"    gold label : {gold_label!r}")
            print(f"    frame/note : {extra[:300]}")

    print("\n=== M2: oracle ceiling (substitute the true row index, re-evaluate) ===")
    flips_right = []
    flips_wrong = []
    unresolved_ambiguous = []
    unchanged = []
    same_index = []
    table_rows = []
    for qid in single_ids:
        if qid not in resolved:
            continue
        rec = runs[qid]
        item = rec["item"]
        query = item["pandas_query"]
        var, gold_table, true_k, method = resolved[qid]
        emap = evidence_map(item)
        accesses = extract_accesses(query)
        ks_for_var = sorted({k for v, k, _ in accesses if v == var})
        if len(ks_for_var) != 1:
            unresolved_ambiguous.append((qid, var, ks_for_var))
            continue
        old_k = ks_for_var[0]
        gold_answer = float(row_answer(gold[qid]))
        orig_val = reeval(query, emap)
        was_correct = close(orig_val, gold_answer, TOL)
        if old_k == true_k:
            same_index.append((qid, old_k, was_correct))
            table_rows.append((qid, old_k, true_k, method, was_correct, was_correct, "index already matched gold"))
            continue
        new_val = substitute_and_eval(query, var, old_k, true_k, emap)
        is_correct = close(new_val, gold_answer, TOL)
        if not was_correct and is_correct:
            flips_right.append((qid, old_k, true_k, orig_val, new_val, gold_answer))
            table_rows.append((qid, old_k, true_k, method, was_correct, is_correct, "FLIP wrong->right"))
        elif was_correct and not is_correct:
            flips_wrong.append((qid, old_k, true_k, orig_val, new_val, gold_answer))
            table_rows.append((qid, old_k, true_k, method, was_correct, is_correct, "FLIP right->wrong"))
        else:
            unchanged.append((qid, old_k, was_correct))
            table_rows.append((qid, old_k, true_k, method, was_correct, is_correct,
                                "index changed, correctness unchanged (still wrong for a different reason)"))

    print(f"resolved+unambiguous single-var cases: n={len(resolved) - len(unresolved_ambiguous)}")
    print(f"  {'qid':>5} {'used_k':>6} {'true_k':>6} {'method':<28} {'was_ok':>6} {'now_ok':>6}  note")
    for qid, old_k, true_k, method, was_ok, now_ok, note in table_rows:
        print(f"  {qid:>5} {old_k:>6} {true_k:>6} {method:<28} {str(was_ok):>6} {str(now_ok):>6}  {note}")
    print(f"\n  index already correct (codegen's row was never the problem here): "
          f"n={len(same_index)}  {[q for q,*_ in same_index]}")
    print(f"  wrong -> right : {len(flips_right)}  {[q for q, *_ in flips_right]}")
    for qid, old_k, true_k, ov, nv, ga in flips_right:
        note = "  [KNOWN SIGN-FIX, do not double count]" if qid in SIGN_FIX_IDS else ""
        print(f"    q{qid}: used k={old_k} val={ov} -> true k={true_k} val={nv}  (gold={ga}){note}")
    print(f"  right -> wrong : {len(flips_wrong)}  {[q for q, *_ in flips_wrong]}")
    for qid, old_k, true_k, ov, nv, ga in flips_wrong:
        print(f"    q{qid}: used k={old_k} val={ov} -> true k={true_k} val={nv}  (gold={ga})")
    print(f"  no change (already same index, or substitution didn't flip correctness): "
          f"n={len(unchanged)}  {[q for q,*_ in unchanged]}")
    if unresolved_ambiguous:
        print(f"  skipped, var accessed at >1 distinct row (ambiguous substitution): "
              f"n={len(unresolved_ambiguous)}  {unresolved_ambiguous}")

    return {"resolved": resolved, "flips_right": flips_right, "flips_wrong": flips_wrong}


def row_answer(row: dict) -> float:
    return float(row["gold_answer"])


# ---------------------------------------------------------------------------
# M5: was the gold row even visible in the grid shown to the model?
# ---------------------------------------------------------------------------

def m5(gold: dict[int, dict], runs: dict[int, dict], m2_state: dict) -> None:
    print("\n=== M5: was the gold row visible in the `_grid` rendering at all? ===")
    resolved = m2_state["resolved"]
    ids_of_interest = sorted(resolved)  # every single-table gold-codegen id we could resolve
    for qid in ids_of_interest:
        row = gold[qid]
        rec = runs[qid]
        var, gold_table, true_k, method = resolved[qid]
        df = _frame(gold_table)
        col = label_column(df)
        n = len(df)
        elided = n > _MAX_GRID_ROWS and (_HEAD_ROWS <= true_k < n - _TAIL_ROWS)
        label_text = str(df.iloc[true_k][col])
        truncated = len(label_text) > GRID_MAX_COLWIDTH
        was_correct = close(reeval(rec["item"]["pandas_query"], evidence_map(rec["item"])),
                             row_answer(row), TOL)
        flag = []
        if elided:
            flag.append("ELIDED (middle of head/tail split)")
        if truncated:
            flag.append(f"TRUNCATED label ({len(label_text)} chars > {GRID_MAX_COLWIDTH})")
        status = "correct" if was_correct else "WRONG"
        print(f"  q{qid} [{status}] table={gold_table} rows={n} true_k={true_k} "
              f"{'; '.join(flag) if flag else 'visible & untruncated'}")
        if flag:
            print(f"      label: {label_text[:120]!r}")


# ---------------------------------------------------------------------------
# M6: the deterministic, achievable number via lookup.search_rows
# ---------------------------------------------------------------------------

def m6(gold: dict[int, dict], runs: dict[int, dict], codegen_recs: list[dict], m2_state: dict) -> None:
    print("\n=== M6: achievable via existing deterministic lookup.search_rows ===")
    resolved = m2_state["resolved"]

    # (a) disagreement rate across the 26 single-table gold cases + whether
    # search_rows lands on the true gold row when it disagrees with the model.
    disagree = 0
    disagree_and_gold_right = 0
    agree = 0
    detail = []
    for qid, (var, gold_table, true_k, method) in resolved.items():
        rec = runs[qid]
        item = rec["item"]
        query = item["pandas_query"]
        accesses = extract_accesses(query)
        ks_for_var = sorted({k for v, k, _ in accesses if v == var})
        if len(ks_for_var) != 1:
            continue
        used_k = ks_for_var[0]
        phrases = direct_metric_phrases(item["question"])
        phrase = phrases[0] if phrases else item["question"]
        hits = search_rows([gold_table], phrase, limit=1)
        best_k = hits[0].position if hits else None
        if best_k is None:
            continue
        if best_k == used_k:
            agree += 1
        else:
            disagree += 1
            hit_gold = best_k == true_k
            if hit_gold:
                disagree_and_gold_right += 1
            detail.append((qid, used_k, best_k, true_k, hit_gold, phrase))

    n = agree + disagree
    print(f"resolved single-table cases with exactly one access to the gold var: n={n}")
    print(f"  used position == search_rows best position : {agree} ({agree/n*100:.1f}%)" if n else "  n/a")
    print(f"  disagree                                    : {disagree} ({disagree/n*100:.1f}%)" if n else "")
    if disagree:
        print(f"  of those disagreements, search_rows matches the true gold row: "
              f"{disagree_and_gold_right}/{disagree} ({disagree_and_gold_right/disagree*100:.1f}%)")
    for qid, used_k, best_k, true_k, hit_gold, phrase in detail:
        print(f"    q{qid}: used={used_k} search_rows={best_k} true={true_k} "
              f"{'RECOVERS GOLD' if hit_gold else 'does not recover'}  phrase={phrase!r}")

    # (b) false-alarm rate: among codegen answers on gold73 that are ALREADY
    # correct, how often would swapping to search_rows' suggestion break them.
    print("\n  -- false-alarm check on currently-correct codegen gold73 answers --")
    fired = 0
    broke = 0
    checked = 0
    fired_ids = []
    broke_ids = []
    for qid, row in gold.items():
        rec = runs.get(qid)
        if rec is None or rec.get("solver") != "codegen":
            continue
        item = rec["item"]
        query = item["pandas_query"]
        emap = evidence_map(item)
        gold_answer = row_answer(row)
        orig_val = reeval(query, emap)
        if not close(orig_val, gold_answer, TOL):
            continue  # only currently-correct answers are in scope for a false alarm
        checked += 1
        accesses = extract_accesses(query)
        # Apply the check to every single-access variable in the query.
        by_var: dict[str, set[int]] = {}
        for v, k, _c in accesses:
            by_var.setdefault(v, set()).add(k)
        any_fired = False
        any_broke = False
        for var, ks in by_var.items():
            if len(ks) != 1 or var not in emap:
                continue
            used_k = next(iter(ks))
            table_id = emap[var]
            phrases = direct_metric_phrases(item["question"])
            phrase = phrases[0] if phrases else item["question"]
            hits = search_rows([table_id], phrase, limit=1)
            if not hits or hits[0].position == used_k:
                continue
            any_fired = True
            new_val = substitute_and_eval(query, var, used_k, hits[0].position, emap)
            if not close(new_val, gold_answer, TOL):
                any_broke = True
        if any_fired:
            fired += 1
            fired_ids.append(qid)
        if any_broke:
            broke += 1
            broke_ids.append(qid)
    print(f"  currently-correct codegen gold73 answers checked: n={checked}")
    print(f"  check fires (search_rows disagrees on some access): {fired}  {fired_ids}")
    print(f"  check fires AND would move the answer off correct: {broke}  {broke_ids}")


def main() -> int:
    gold = load_gold()
    runs = load_runs()
    codegen_recs = [rec for rec in runs.values() if rec.get("solver") == "codegen"]
    print(f"codegen records in run: {len(codegen_recs)}")
    print(f"gold73 questions solved by codegen: "
          f"{sum(1 for qid in gold if qid in runs and runs[qid].get('solver') == 'codegen')}")

    m1(codegen_recs)
    single_ids, multi_ids = build_single_cell_stratum(gold, runs)
    m2_state = m2_m3(gold, runs, single_ids, multi_ids)
    m5(gold, runs, m2_state)
    m6(gold, runs, codegen_recs, m2_state)

    known_bucket_c = [526, 555, 635, 868, 946]
    print(f"\n=== known bucket-C ids {known_bucket_c}: fate under the oracle (M2) ===")
    flip_ids = {q for q, *_ in m2_state["flips_right"]}
    resolved = m2_state["resolved"]
    for qid in known_bucket_c:
        if qid in flip_ids:
            print(f"  q{qid}: RECOVERED by oracle row substitution")
        elif qid in resolved:
            print(f"  q{qid}: gold row resolved but substitution did not flip it "
                  f"(may be a table/column/sign issue, not a row issue)")
        else:
            print(f"  q{qid}: gold row NOT resolved in the shown frame (multi-table stratum, "
                  f"table-mismatch, or not-found -- see M3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
