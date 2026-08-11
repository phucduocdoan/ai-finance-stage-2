"""Cell-level coverage probe for the mã-số accessor (get_v family from eval_gold.py).

Measures, per gold question: how many of the (ticker, year, statement, mã_số) cells
the correct solution touches can the accessor actually resolve — a/b ô.

Probes against the FULL corpus metadata (not the retrieval pool), so a miss here is a
real accessor/data gap; a question that fails in the pipeline only due to retrieval
year-gap (e.g. Q363) will still show full coverage here — isolating accessor vs retrieval.

Run:
    PYTHONPATH=src .venv_bge/bin/python scripts/probe_accessor_coverage.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from eval_gold import get_v_signed, get_v_prior  # reuse the accessor

# mã số reference used below:
#   BS: 100 CA · 140 Inv · 220 NFA · 270 TA · 300 total-liab · 310 CL · 400 equity
#   IS: 10 rev · 11 COGS · 20 gross-profit · 30 op-profit · 50 PBT · 60 NPAT · 23 interest
#   CF: 20 CFO
BS, IS, CF = "balance_sheet", "income_statement", "cash_flow"

# Per multi_year question: ticker, year list, and the (statement, mã_số) cells each
# year needs for the metrics in that question. Probe every year × cell.
MULTI_YEAR = {
    363: ("KBC", range(2016, 2021), [(BS, 300), (BS, 400), (IS, 50), (IS, 23)]),   # D/E → ICR
    372: ("VRE", range(2021, 2025), [(BS, 100), (BS, 140), (BS, 310), (CF, 20)]),  # QR → CFO/CL
    378: ("HPG", range(2018, 2025), [(IS, 10), (IS, 20), (CF, 20), (IS, 60), (BS, 400)]),  # GM→CFO/rev→ROE
    381: ("HPG", range(2017, 2024), [(CF, 20), (IS, 60), (BS, 140), (BS, 270)]),   # CFO/NPAT → inv/TA
    387: ("HPG", range(2021, 2025), [(CF, 20), (IS, 60), (IS, 50), (IS, 23)]),     # CFO/NPAT → ICR
    407: ("MWG", range(2021, 2025), [(CF, 20), (IS, 60), (BS, 100), (BS, 310)]),   # CFO/NPAT → next-yr current ratio
    415: ("HPG", range(2020, 2025), [(IS, 10), (BS, 100), (BS, 310)]),             # max rev → current ratio
    426: ("FPT", range(2021, 2025), [(CF, 20), (IS, 60)]),                         # CFO/NPAT → NPAT-CFO
    440: ("DIG", range(2021, 2025), [(BS, 300), (BS, 400), (IS, 50), (IS, 23)]),   # D/E → ICR
    439: ("HPG", range(2018, 2025), [(IS, 10), (IS, 20), (CF, 20), (IS, 60), (BS, 300), (BS, 400)]),  # GM→CFO/rev→D/E
}

# Multi_company questions are fully solved end-to-end by eval_gold.py (10/10 ✓),
# which means every cell they touch already resolves. Listed here for the summary only.
MULTI_COMPANY_SOLVED = [371, 390, 392, 396, 409, 414, 422, 423, 424, 429]


def probe_cell(ticker: str, year: int, stype: str, maso: int) -> bool:
    """True if the accessor resolves this cell (prior-year cells fall back to get_v_prior)."""
    if get_v_signed(ticker, year, stype, maso) is not None:
        return True
    # some cells are only present as a prior-year column of the next report
    return get_v_prior(ticker, year + 1, stype, maso) is not None


def main() -> None:
    print(f"{'QID':>4}  {'Ticker':>6}  {'a/b ô':>8}  {'%':>5}  missing cells")
    print("-" * 78)

    grand_hit = grand_tot = 0
    for qid in sorted(MULTI_YEAR):
        ticker, years, cells = MULTI_YEAR[qid]
        hit = 0
        tot = 0
        missing: list[str] = []
        for y in years:
            for stype, maso in cells:
                tot += 1
                if probe_cell(ticker, y, stype, maso):
                    hit += 1
                else:
                    missing.append(f"{y}·{stype[:2]}{maso}")
        grand_hit += hit
        grand_tot += tot
        miss_str = ", ".join(missing) if missing else "—"
        print(f"{qid:>4}  {ticker:>6}  {hit:>3}/{tot:<4}  {hit/tot:>4.0%}  {miss_str}")

    print("-" * 78)
    print(f"multi_year total: {grand_hit}/{grand_tot} = {grand_hit/grand_tot:.0%} cells resolved")
    print(f"multi_company:    10/10 questions solved end-to-end (eval_gold.py) "
          f"→ all cells resolve")


if __name__ == "__main__":
    main()
