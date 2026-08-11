"""Verify derived+multi_company gold answers against data/eval/extended_gold.jsonl.

Uses load_frame() (which now has C1 fix: min_ratio=0.25 for short tables) plus
a local find_maso_col with C2 fix (sparse-table min_count lowered).

Run:
    PYTHONPATH=src .venv_bge/bin/python scripts/eval_gold.py
"""

from __future__ import annotations

import json
import re
import sys

import pandas as pd

sys.path.insert(0, "src")

from finance_qa.modules.data.table_store import load_frame

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

_meta: dict[str, dict] = {}

def _load_meta() -> dict[str, dict]:
    if _meta:
        return _meta
    with open("data/metadata/tables_metadata_v2.jsonl", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            key = f"{r['report_id']}|{r['table_pos']}"
            _meta[key] = r
    return _meta


def get_tables(ticker: str, year: int, stype: str, cons: bool = True) -> list:
    meta = _load_meta()
    sfx = "consolidated" if cons else "separate"
    pfx = f"{ticker}_financial_statements_{year}_{sfx}"
    res = [(t, r) for t, r in meta.items()
           if t.startswith(pfx) and r.get("statement_type") == stype]
    return sorted(res, key=lambda x: int(x[0].split("|")[1]))


# ---------------------------------------------------------------------------
# find_maso_col — C2 fix: sparse tables (len ≤ 5) use min_count=1
# ---------------------------------------------------------------------------

_LABEL_COLS = frozenset([
    "chỉ tiêu", "chỉtiêu", "tên chỉ tiêu", "diễn giải", "nội dung",
    "unnamed: 0", "tài sản", "nguồn vốn",
])


def find_maso_col(df: pd.DataFrame) -> str | None:
    min_count = 1 if len(df) <= 5 else 3
    candidates = []
    for c in df.columns:
        cs = str(c).casefold().strip()
        if cs in _LABEL_COLS:
            continue
        non_null = df[c].dropna()
        if len(non_null) > 0 and non_null.apply(
            lambda v: isinstance(v, str) and len(v) > 5
        ).mean() > 0.5:
            continue
        vals = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(vals) < 1:
            continue
        int_vals = vals[vals.apply(lambda v: v == int(v) and 1 <= int(v) <= 700)]
        if len(int_vals) < min_count:
            continue
        int_frac = len(int_vals) / len(vals)
        # For sparse tables bypass frac check; for normal tables require 0.8
        if len(df) > 5 and int_frac < 0.8:
            continue
        priority = 2 if any(x in cs for x in ["mã", "stt"]) else 0
        priority += 1 if any(x in cs for x in ["tm", "thuyết"]) else 0
        priority += 1 if len(int_vals) > 1 and int_vals.max() > 9 else 0
        candidates.append((int_frac + priority, c))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


# ---------------------------------------------------------------------------
# Value extraction
# ---------------------------------------------------------------------------

_MONETARY_THRESHOLD = 1e4
_VALUE_THRESHOLD = 1e3


def _get_monetary_in_order(df: pd.DataFrame) -> list:
    result = []
    for c in df.columns:
        nums = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(nums) == 0 or nums.abs().max() < _MONETARY_THRESHOLD:
            continue
        yr_match = re.search(r"(20\d{2})", str(c))
        yr = int(yr_match.group(1)) if yr_match else None
        cs = str(c).casefold()
        ic = any(m in cs for m in ["năm nay", "số cuối năm"])
        ip = any(m in cs for m in ["năm trước", "số đầu năm"])
        result.append((c, yr, nums.abs().max(), ic, ip))
    return result


def _get_row_val(row: pd.Series, vcols: list[str]) -> float | None:
    for vc in vcols:
        v = pd.to_numeric(row[vc], errors="coerce")
        if pd.notna(v) and abs(v) >= _VALUE_THRESHOLD:
            return float(v)
    return None


def _get_row_val_signed(row: pd.Series, vcols: list[str]) -> float | None:
    """Return value including negatives (no abs filter)."""
    for vc in vcols:
        v = pd.to_numeric(row[vc], errors="coerce")
        if pd.notna(v):
            return float(v)
    return None


def get_v(ticker: str, year: int, stype: str, maso: int) -> float | None:
    for tid, _ in get_tables(ticker, year, stype):
        df = load_frame(tid)
        mc = find_maso_col(df)
        if mc is None:
            continue
        rows = df[df[mc] == float(maso)]
        if rows.empty:
            continue
        monetary = _get_monetary_in_order(df)
        vcols = [c for c, yr, mx, ic, ip in monetary if ic]
        for c, yr, mx, ic, ip in monetary:
            if yr == year and c not in vcols:
                vcols.append(c)
        for c, yr, mx, ic, ip in sorted(monetary, key=lambda t: -t[2]):
            if not ip and c not in vcols:
                vcols.append(c)
        for c, yr, mx, ic, ip in monetary:
            if c not in vcols:
                vcols.append(c)
        v = _get_row_val(rows.iloc[0], vcols)
        if v is not None:
            return v
    return None


def get_v_signed(ticker: str, year: int, stype: str, maso: int) -> float | None:
    """get_v but returns negative values too (for sign-based qualification checks)."""
    for tid, _ in get_tables(ticker, year, stype):
        df = load_frame(tid)
        mc = find_maso_col(df)
        if mc is None:
            continue
        rows = df[df[mc] == float(maso)]
        if rows.empty:
            continue
        monetary = _get_monetary_in_order(df)
        vcols = [c for c, yr, mx, ic, ip in monetary if ic]
        for c, yr, mx, ic, ip in monetary:
            if yr == year and c not in vcols:
                vcols.append(c)
        for c, yr, mx, ic, ip in sorted(monetary, key=lambda t: -t[2]):
            if not ip and c not in vcols:
                vcols.append(c)
        for c, yr, mx, ic, ip in monetary:
            if c not in vcols:
                vcols.append(c)
        v = _get_row_val_signed(rows.iloc[0], vcols)
        if v is not None:
            return v
    return None


def get_v_prior(ticker: str, year: int, stype: str, maso: int) -> float | None:
    for tid, _ in get_tables(ticker, year, stype):
        df = load_frame(tid)
        mc = find_maso_col(df)
        if mc is None:
            continue
        rows = df[df[mc] == float(maso)]
        if rows.empty:
            continue
        monetary = _get_monetary_in_order(df)
        vcols = [c for c, yr, mx, ic, ip in monetary if ip and not ic]
        for c, yr, mx, ic, ip in monetary:
            if yr == year - 1 and c not in vcols:
                vcols.append(c)
        if not vcols:
            if len(monetary) >= 2:
                vcols = [monetary[1][0]]
            elif monetary:
                vcols = [monetary[0][0]]
        v = _get_row_val(rows.iloc[0], vcols)
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# Question computations
# ---------------------------------------------------------------------------

def compute(qid: int) -> float | None:  # noqa: C901
    if qid == 371:
        # BSR/PLX/PVT — CFO>0 → max GM → ICR
        results = {}
        for tk in ["BSR", "PLX", "PVT"]:
            cfo = get_v_signed(tk, 2024, "cash_flow", 20)
            if cfo is None or cfo <= 0:
                continue
            rev = get_v(tk, 2024, "income_statement", 10)
            gp = get_v(tk, 2024, "income_statement", 20)
            pbt = get_v(tk, 2024, "income_statement", 50)
            interest = get_v(tk, 2024, "income_statement", 23)
            if not (rev and gp and pbt is not None and interest):
                continue
            gm = gp / rev
            icr = (abs(pbt) + abs(interest)) / abs(interest)
            results[tk] = (gm, icr)
        if not results:
            return None
        winner = max(results, key=lambda k: results[k][0])
        return results[winner][1]

    if qid == 390:
        # HPG/HSG/NKG — min QR → Inv (nghìn tỷ)
        qr_inv = {}
        for tk in ["HPG", "HSG", "NKG"]:
            ca = get_v(tk, 2024, "balance_sheet", 100)
            inv = get_v(tk, 2024, "balance_sheet", 140)
            cl = get_v(tk, 2024, "balance_sheet", 310)
            if ca and inv and cl:
                qr_inv[tk] = ((ca - inv) / cl, inv)
        if not qr_inv:
            return None
        winner = min(qr_inv, key=lambda k: qr_inv[k][0])
        return qr_inv[winner][1] / 1e12  # nghìn tỷ

    if qid == 392:
        # MCH/QNS/OGC — max CFO/NPAT → QR
        results = {}
        for tk in ["MCH", "QNS", "OGC"]:
            cfo = get_v_signed(tk, 2024, "cash_flow", 20)
            npat = get_v_signed(tk, 2024, "income_statement", 60)
            ca = get_v(tk, 2024, "balance_sheet", 100)
            inv = get_v(tk, 2024, "balance_sheet", 140)
            cl = get_v(tk, 2024, "balance_sheet", 310)
            if cfo and npat and ca and inv and cl:
                results[tk] = (cfo / npat, (ca - inv) / cl)
        if not results:
            return None
        winner = max(results, key=lambda k: results[k][0])
        return results[winner][1]

    if qid == 396:
        # ASM/DBC/MSN/OGC — CFO>0 & NPAT>0 → max CFO/NPAT → QR
        results = {}
        for tk in ["ASM", "DBC", "MSN", "OGC"]:
            cfo = get_v_signed(tk, 2024, "cash_flow", 20)
            npat = get_v_signed(tk, 2024, "income_statement", 60)
            if cfo is None or npat is None or cfo <= 0 or npat <= 0:
                continue
            ca = get_v(tk, 2024, "balance_sheet", 100)
            inv = get_v(tk, 2024, "balance_sheet", 140)
            cl = get_v(tk, 2024, "balance_sheet", 310)
            if ca and inv and cl:
                results[tk] = (cfo / npat, (ca - inv) / cl)
        if not results:
            return None
        winner = max(results, key=lambda k: results[k][0])
        return results[winner][1]

    if qid == 409:
        # VIC/KBC/NLG/DXG/DIG — median inv/TA → avg NPM of above-median
        inv_ta: dict[str, float] = {}
        npm: dict[str, float] = {}
        for tk in ["VIC", "KBC", "NLG", "DXG", "DIG"]:
            inv = get_v(tk, 2024, "balance_sheet", 140)
            ta = get_v(tk, 2024, "balance_sheet", 270)
            npat = get_v_signed(tk, 2024, "income_statement", 60)
            rev = get_v(tk, 2024, "income_statement", 10)
            if inv and ta:
                inv_ta[tk] = inv / ta
            if npat and rev:
                npm[tk] = npat / rev
        if len(inv_ta) < 5:
            return None
        sorted_it = sorted(inv_ta.items(), key=lambda x: x[1])
        median_val = sorted_it[2][1]
        above = [k for k, v in sorted_it if v > median_val]
        if not above or any(k not in npm for k in above):
            return None
        return sum(npm[k] for k in above) / len(above) * 100  # phần trăm

    if qid == 414:
        # HPG/HSG/NKG — RevG>3% & Op>0 both → max DOL → OPM
        results = {}
        for tk in ["HPG", "HSG", "NKG"]:
            rev = get_v(tk, 2024, "income_statement", 10)
            rev_p = get_v_prior(tk, 2024, "income_statement", 10)
            op = get_v_signed(tk, 2024, "income_statement", 30)
            op_p = get_v_prior(tk, 2024, "income_statement", 30)
            if not (rev and rev_p and op is not None and op_p is not None):
                continue
            revg = (rev - rev_p) / abs(rev_p)
            if revg <= 0.03 or op <= 0 or op_p <= 0:
                continue
            dol = ((op - op_p) / abs(op_p)) / revg
            results[tk] = (dol, op / rev * 100)
        if not results:
            return None
        winner = max(results, key=lambda k: results[k][0])
        return results[winner][1]  # OPM %

    if qid == 422:
        # DCM/DPM/GVR/HPG/HT1 — above-median RevG → max NPAT-CFO → CFO/NPAT round 2dp
        revg: dict[str, float] = {}
        for tk in ["DCM", "DPM", "GVR", "HPG", "HT1"]:
            rev = get_v(tk, 2024, "income_statement", 10)
            rev_p = get_v_prior(tk, 2024, "income_statement", 10)
            if rev and rev_p:
                revg[tk] = (rev - rev_p) / abs(rev_p)
        if len(revg) < 5:
            return None
        median_revg = sorted(revg.values())[2]
        above = [k for k, v in revg.items() if v > median_revg]
        best_diff, best_ratio = None, None
        for tk in above:
            npat = get_v_signed(tk, 2024, "income_statement", 60)
            cfo = get_v_signed(tk, 2024, "cash_flow", 20)
            if npat is None or cfo is None:
                continue
            diff = npat - cfo
            if best_diff is None or diff > best_diff:
                best_diff = diff
                best_ratio = cfo / npat
        if best_ratio is None:
            return None
        return round(best_ratio, 2)

    if qid == 423:
        # GEX/HBC/PC1/SAM/VGC — QR < median → stress ICR → min round 2dp
        qr: dict[str, float] = {}
        stress: dict[str, float] = {}
        for tk in ["GEX", "HBC", "PC1", "SAM", "VGC"]:
            ca = get_v(tk, 2024, "balance_sheet", 100)
            inv = get_v(tk, 2024, "balance_sheet", 140)
            cl = get_v(tk, 2024, "balance_sheet", 310)
            pbt = get_v(tk, 2024, "income_statement", 50)
            interest = get_v(tk, 2024, "income_statement", 23)
            if ca and inv and cl:
                qr[tk] = (ca - inv) / cl
            if pbt is not None and interest:
                ebit = pbt + abs(interest)
                stress[tk] = ebit * 0.85 / abs(interest)
        if len(qr) < 5:
            return None
        median_qr = sorted(qr.values())[2]
        below = [k for k, v in qr.items() if v < median_qr]
        vals = [stress[k] for k in below if k in stress]
        return round(min(vals), 2) if vals else None

    if qid == 424:
        # DCM/GVR/HT1 — max DOH excess → free_up tỷ
        doh: dict[str, tuple] = {}
        for tk in ["DCM", "GVR", "HT1"]:
            inv = get_v(tk, 2024, "balance_sheet", 140)
            rev = get_v(tk, 2024, "income_statement", 10)
            gp = get_v(tk, 2024, "income_statement", 20)
            cogs = (rev - gp) if (rev and gp) else get_v(tk, 2024, "income_statement", 11)
            if inv and cogs:
                doh[tk] = (inv / cogs * 365, cogs)
        if len(doh) < 3:
            return None
        sorted_doh = sorted(doh.items(), key=lambda x: x[1][0])
        median_doh = sorted_doh[1][1][0]
        best_excess, best_free = None, None
        for tk, (d, cogs) in doh.items():
            excess = d - median_doh
            if excess <= 0:
                continue
            if best_excess is None or excess > best_excess:
                best_excess = excess
                best_free = excess / 365 * cogs / 1e9  # tỷ
        return round(best_free, 2) if best_free else None

    if qid == 429:
        # ASM/DBC/MSN/OGC/VNM — FAT < median → max AvgNFA (VND equiv) → FAT
        fat: dict[str, float] = {}
        avg_nfa_vnd: dict[str, float] = {}
        for tk in ["ASM", "DBC", "MSN", "OGC", "VNM"]:
            rev = get_v(tk, 2024, "income_statement", 10)
            nfa_end = get_v(tk, 2024, "balance_sheet", 220)
            nfa_beg = get_v_prior(tk, 2024, "balance_sheet", 220)
            if rev and nfa_end and nfa_beg:
                avg_nfa = (nfa_end + nfa_beg) / 2
                fat[tk] = rev / avg_nfa
                # MSN reports in triệu → multiply by 1e6 for VND-equivalent comparison
                avg_nfa_vnd[tk] = avg_nfa * (1e6 if tk == "MSN" else 1)
        if len(fat) < 5:
            return None
        sorted_fat = sorted(fat.items(), key=lambda x: x[1])
        median_fat = sorted_fat[2][1]
        below = [k for k, v in sorted_fat if v < median_fat]
        winner = max(below, key=lambda k: avg_nfa_vnd.get(k, 0))
        return fat[winner]

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    with open("data/eval/extended_gold.jsonl", encoding="utf-8") as fh:
        gold = [json.loads(line) for line in fh]

    # Only evaluate multi_company questions (ids defined by what we computed)
    mc_ids = {371, 390, 392, 396, 409, 414, 422, 423, 424, 429}
    mc_gold = [g for g in gold if g["id"] in mc_ids]

    print(f"Evaluating {len(mc_gold)} derived+multi_company gold questions\n")
    print(f"{'ID':>4}  {'Gold':>12}  {'Pred':>12}  {'Match':>6}  {'Conf'}")
    print("-" * 55)

    correct = 0
    for g in sorted(mc_gold, key=lambda x: x["id"]):
        qid = g["id"]
        gold_ans = g["answer"]
        pred = compute(qid)

        if pred is None:
            match_str = "NONE"
        elif abs(gold_ans) < 1e-9:
            match_str = "✓" if abs(pred) < 1e-9 else "✗"
        else:
            rel = abs(pred - gold_ans) / abs(gold_ans)
            match_str = "✓" if rel < 0.01 else f"✗ {rel:.2%}"

        if match_str == "✓":
            correct += 1

        print(f"{qid:>4}  {gold_ans:>12.6g}  "
              f"{pred if pred is not None else 'None':>12}  "
              f"{match_str:>6}  {g.get('confidence','')}")

    print("-" * 55)
    print(f"Score: {correct}/{len(mc_gold)} = {correct/len(mc_gold):.0%}")


if __name__ == "__main__":
    main()
