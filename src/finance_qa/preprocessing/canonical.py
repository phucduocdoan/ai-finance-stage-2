"""Offline row canonicalization for main financial statement tables.

Converts a DataFrame with a mã số column into {metric_id: {year: float}}
using Thông tư 200/2014/TT-BTC codes. Used by the REPL to replace raw schema
blocks with pre-computed financial metric values so the LLM skips structural
inspection and computes directly.
"""
from __future__ import annotations

import json
import re
import unicodedata

import pandas as pd

from finance_qa.paths import TABLE_METADATA_PATH

# ---------------------------------------------------------------------------
# Thông tư 200 mã số → metric_id
# Split by statement_type because IS and CF share overlapping code ranges.
# ---------------------------------------------------------------------------

MA_SO_BS: dict[str, str] = {
    "100": "current_assets",
    "110": "cash_and_equivalents",
    "120": "short_term_investments",
    "130": "receivables_short",
    "131": "receivables_customers_short",
    "132": "advance_payments_short",
    "133": "receivables_internal_short",
    "134": "loan_receivables_short",
    "135": "other_receivables_short",
    "140": "inventory",
    "150": "other_current_assets",
    "200": "non_current_assets",
    "210": "long_term_receivables",
    "220": "fixed_assets",
    "221": "tangible_fixed_assets_net",
    "222": "finance_lease_assets_net",
    "223": "intangible_assets_net",
    "227": "intangible_assets_net",
    "230": "real_estate_investment",
    "240": "long_term_investments",
    "241": "investments_in_subsidiaries",
    "242": "investments_in_associates",
    "243": "investments_in_jv",
    "244": "other_long_term_investments",
    "250": "other_non_current_assets",
    "254": "capex_in_progress",
    "260": "goodwill",
    "270": "total_assets",
    "300": "total_debt",
    "310": "short_term_debt",
    "311": "payables_to_suppliers_short",
    "312": "advance_from_customers_short",
    "313": "taxes_payable",
    "314": "payables_to_employees",
    "315": "accrued_expenses",
    "319": "other_short_term_payables",
    "320": "short_term_borrowings",
    "321": "bonds_issued_short",
    "322": "short_term_finance_lease",
    "323": "provision_short",
    "324": "bonus_welfare_fund",
    "330": "long_term_debt",
    "331": "payables_to_suppliers_long",
    "332": "advance_from_customers_long",
    "333": "security_deposits_received",
    "335": "other_long_term_payables",
    "336": "long_term_borrowings",
    "337": "bonds_issued_long",
    "338": "long_term_finance_lease",
    "339": "convertible_bonds",
    "340": "deferred_tax_liabilities",
    "341": "provision_long",
    "342": "science_tech_fund",
    "400": "equity",
    "410": "owners_equity",
    "411": "share_capital",
    "412": "share_premium",
    "413": "bond_conversion_option",
    "415": "treasury_shares",
    "417": "fx_translation_reserve",
    "418": "investment_development_fund",
    "419": "sci_tech_fund_equity",
    "420": "retained_earnings",
    "421": "retained_earnings_prior",
    "422": "retained_earnings_current",
    "430": "minority_interest",
    "440": "total_liabilities_and_equity",
}

MA_SO_IS: dict[str, str] = {
    "01": "revenue",
    "02": "revenue_deductions",
    "10": "net_revenue",
    "11": "cogs",
    "20": "gross_profit",
    "21": "finance_income",
    "22": "finance_expense",
    "23": "interest_expense",
    "24": "share_of_profit_associates",
    "25": "selling_expense",
    "26": "admin_expense",
    "30": "operating_profit",
    "31": "other_income",
    "32": "other_expense",
    "40": "other_profit",
    "50": "profit_before_tax",
    "51": "current_income_tax_expense",
    "52": "deferred_income_tax_expense",
    "60": "net_profit",
    "61": "minority_net_profit",
    "62": "net_profit_attributable_to_owners",
    "70": "eps_basic",   # "Lãi cơ bản trên cổ phiếu" — EPS, not net profit
    "71": "eps_diluted",
}

MA_SO_CF: dict[str, str] = {
    "20": "net_cash_operating",
    "30": "net_cash_investing",
    "40": "net_cash_financing",
    "50": "net_cash_change",
    "60": "cash_beginning",
    "61": "fx_effect_on_cash",
    "70": "cash_end",
}

_DICT_BY_TYPE: dict[str, dict[str, str]] = {
    "balance_sheet": MA_SO_BS,
    "income_statement": MA_SO_IS,
    "cash_flow": MA_SO_CF,
}

_CURRENT_COL_MARKERS = ("năm nay", "số cuối năm", "cuối năm", "cuối kỳ", "kỳ này")
_PRIOR_COL_MARKERS = ("năm trước", "số đầu năm", "đầu năm", "đầu kỳ", "kỳ trước")


def _col_norm(s: str) -> str:
    """NFC-normalize, casefold, strip spaces — handles NFD/NFC and OCR dropped-space variants."""
    return unicodedata.normalize("NFC", str(s)).casefold().replace(" ", "").strip()


_MASO_NORM = _col_norm("mã số")  # "mãsố"

# ---------------------------------------------------------------------------
# Metadata lazy singleton (statement_type + has_ma_so_column per table)
# ---------------------------------------------------------------------------

_META: dict[str, dict] | None = None


def _get_table_meta(table_id: str) -> dict:
    global _META
    if _META is None:
        meta: dict[str, dict] = {}
        with TABLE_METADATA_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                key = f"{r['report_id']}|{r['table_pos']}"
                meta[key] = {
                    "statement_type": r.get("statement_type") or "",
                    "has_ma_so_column": bool(r.get("has_ma_so_column", False)),
                    "ticker": r.get("ticker") or "",
                }
        _META = meta
    return _META.get(table_id, {"statement_type": "", "has_ma_so_column": False, "ticker": ""})


# ---------------------------------------------------------------------------
# Year-map helper (same logic as table_profile.py + explicit year in col name)
# ---------------------------------------------------------------------------

# Separates value columns from the mã số column (codes ≤ 700) and thuyết minh
# note references (small ints / text) purely by magnitude — no name matching.
_MONETARY_THRESHOLD = 1e4


def _monetary_cols(df: pd.DataFrame) -> list[str]:
    """Value columns in table order: numeric with monetary magnitude."""
    cols: list[str] = []
    for col in df.columns:
        nums = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(nums) and nums.abs().max() >= _MONETARY_THRESHOLD:
            cols.append(str(col))
    return cols


def _build_year_map(df: pd.DataFrame, table_id: str) -> dict[str, int]:
    m = re.search(r"financial_statements_(20\d{2})", table_id)
    report_year = int(m.group(1)) if m else None
    result: dict[str, int] = {}
    for col in df.columns:
        cf = unicodedata.normalize("NFC", str(col)).strip().casefold()
        if report_year and any(mk in cf for mk in _CURRENT_COL_MARKERS):
            result[str(col)] = report_year
        elif report_year and any(mk in cf for mk in _PRIOR_COL_MARKERS):
            result[str(col)] = report_year - 1
        else:
            # "31/12/2022" → 2022 (current); "01/01/2022" or "1/1/2022" → 2021 (prior)
            date_m = re.match(r"(\d{1,2})/(\d{1,2})/(20\d{2})", str(col).strip())
            if date_m:
                day, month, yr = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
                result[str(col)] = yr - 1 if (month == 1 and day <= 5) else yr
            else:
                ym = re.search(r"20\d{2}", str(col))
                if ym:
                    result[str(col)] = int(ym.group())

    # Fallback for OCR-mangled headers ("Tại ngày", "Unnamed: N") with no
    # recoverable year: TT200 statements print the current period before the
    # prior one, so the leftmost monetary column is report_year, the next is
    # report_year - 1. setdefault leaves any header-derived year untouched.
    if report_year:
        for i, col in enumerate(_monetary_cols(df)[:2]):
            result.setdefault(col, report_year - i)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def canonical_frame(
    df: pd.DataFrame,
    table_id: str,
    statement_type: str,
) -> dict[str, dict[int, float]]:
    """Convert a financial statement DataFrame to {metric_id: {year: float}}.

    Returns empty dict if no mã số column found or statement_type is not
    one of {balance_sheet, income_statement, cash_flow}.
    """
    ma_so_dict = _DICT_BY_TYPE.get(statement_type)
    if ma_so_dict is None:
        return {}

    ma_col: str | None = None
    for col in df.columns:
        if _col_norm(col) == _MASO_NORM:
            ma_col = col
            break
    if ma_col is None:
        return {}

    year_map = _build_year_map(df, table_id)
    value_cols = [(col, yr) for col, yr in year_map.items() if col in df.columns]
    if not value_cols:
        return {}

    ma_is_numeric = pd.api.types.is_numeric_dtype(df[ma_col])
    result: dict[str, dict[int, float]] = {}
    for _, row in df.iterrows():
        raw = row[ma_col]
        # numeric mã số (float due to normalize_frame) → strip decimal: 100.0 → "100"
        if ma_is_numeric:
            try:
                raw_code = str(int(float(raw)))
            except (ValueError, TypeError):
                continue
        else:
            raw_code = str(raw).strip()
        metric_id = ma_so_dict.get(raw_code)
        if metric_id is None:
            continue
        for col, yr in value_cols:
            val = row[col]
            try:
                f = float(val)
                if f != f:  # nan
                    continue
                result.setdefault(metric_id, {})[yr] = f
            except (TypeError, ValueError):
                continue

    return result


# High-priority metrics shown first in the canonical block (most useful for ratios)
_PRIORITY_METRICS = [
    "total_assets", "current_assets", "non_current_assets",
    "total_debt", "short_term_debt", "long_term_debt",
    "short_term_borrowings", "long_term_borrowings",
    "equity", "owners_equity", "minority_interest",
    "total_liabilities_and_equity",
    "net_revenue", "gross_profit", "operating_profit",
    "profit_before_tax", "net_profit", "interest_expense",
    "net_cash_operating", "net_cash_investing", "net_cash_financing",
    "cash_end", "cash_beginning",
]
_PRIORITY_INDEX = {m: i for i, m in enumerate(_PRIORITY_METRICS)}


def _metric_sort_key(metric_id: str) -> tuple:
    return (_PRIORITY_INDEX.get(metric_id, len(_PRIORITY_METRICS)), metric_id)


def canonical_schema_block(var: str, table_id: str, df: pd.DataFrame) -> str | None:
    """Return a compact canonical schema text for the REPL, or None if not applicable.

    Replaces the raw column/dtype/label block with pre-computed metric values
    so the LLM can skip structural inspection and compute ratios directly.
    Priority metrics (D/E, ROE, ROA inputs) appear first.
    """
    tmeta = _get_table_meta(table_id)
    statement_type = tmeta["statement_type"]
    data = canonical_frame(df, table_id, statement_type)
    if not data:
        return None

    years = sorted({yr for vals in data.values() for yr in vals})
    yr_header = "       ".join(str(y) for y in years)

    lines = [
        f"### {var}  ({table_id})  [{statement_type}]",
        f"canonical[\"{var}\"]: metric_id → {{year: float (đồng)}}",
        f"  {'metric_id':<36}  {yr_header}",
    ]
    for metric_id in sorted(data, key=_metric_sort_key):
        yr_vals = data[metric_id]
        parts = []
        for yr in years:
            if yr in yr_vals:
                parts.append(f"{yr_vals[yr]:>20,.0f}")
            else:
                parts.append(f"{'N/A':>20}")
        lines.append(f"  {metric_id:<36}  {'  '.join(parts)}")

    lines.append(f"Dùng get_val({var}, '<tên VN>') cho chỉ tiêu không có trong canonical.")
    return "\n".join(lines)
