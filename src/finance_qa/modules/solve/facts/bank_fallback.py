"""Bank primary-statement fallback: read facts straight from a raw CSV.

Bank statements often carry no VAS `mã số` column, so `StatementFactStore`'s
normal ma_so-keyed lookup finds nothing for them. This module conservatively
matches a fixed allowlist of Vietnamese row labels for a small set of metrics
and reads the value straight out of the original CSV, bypassing the
long-format table entirely.
"""
from __future__ import annotations

import re
from typing import Any

from finance_qa.core.paths import DATA_DIR
from finance_qa.modules.solve.common.units import conversion_factor, detect_unit
from finance_qa.modules.solve.facts.metrics import PrimitiveMetric, _norm
from finance_qa.modules.tools.numeric import parse_number

BANK_LABEL_FALLBACK_METRICS = frozenset({
    "total_assets",
    "liabilities",
    "equity",
    "interest_expense",
    "profit_before_tax",
    "net_profit",
    "cfo",
})
_NON_VALUE_COLUMNS = frozenset({"stt", "tm", "thuyet minh", "ma so", "mau so"})
_LEADING_LABEL_CODE = re.compile(r"^(?:[ivxlcdm]+|\d+|[a-z])\s+")


def _semantic_label(label: object) -> str:
    text = _norm(label)
    for _ in range(3):
        stripped = _LEADING_LABEL_CODE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text


def label_matches(metric_key: str, label: object) -> bool:
    """Conservative row-label matcher for bank primary statements without VAS mã số."""
    core = _semantic_label(label)
    if metric_key == "total_assets":
        return core in {"tong tai san co", "tong tai san", "tong cong tai san"}
    if metric_key == "liabilities":
        return core == "tong no phai tra"
    if metric_key == "equity":
        return core in {"von chu so huu", "tong von chu so huu", "von va cac quy"}
    if metric_key == "interest_expense":
        return core.startswith("chi phi lai va cac chi phi tuong tu") or core == "chi phi lai"
    if metric_key == "profit_before_tax":
        return core in {"tong loi nhuan truoc thue", "loi nhuan truoc thue"}
    if metric_key == "net_profit":
        return core.startswith("loi nhuan sau thue") and "truoc" not in core
    if metric_key == "cfo":
        return (
            core.startswith("luu chuyen tien thuan tu hoat dong kinh doanh")
            and "truoc nhung thay doi" not in core
        )
    return False


def _label_column(df) -> str:
    for col in df.columns:
        if "chi tieu" in _norm(col):
            return col

    best_col = df.columns[0]
    best_score = -1
    for col in list(df.columns)[:3]:
        if _norm(col) in _NON_VALUE_COLUMNS:
            continue
        score = 0
        for value in df[col].head(80):
            text = _norm(value)
            if len(text) >= 3 and parse_number(str(value)) is None:
                score += 1
        if score > best_score:
            best_col, best_score = col, score
    return best_col


def _period_columns(df, meta: dict[str, Any], label_col: str) -> list[str]:
    raw_periods = {str(col).strip() for col in (meta.get("period_columns_raw") or [])}
    exact = [col for col in df.columns if str(col).strip() in raw_periods]
    if exact:
        return exact

    period_cols: list[str] = []
    for col in df.columns:
        norm_col = _norm(col)
        if col == label_col or norm_col in _NON_VALUE_COLUMNS:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", norm_col) or "nam" in norm_col or "31 12" in norm_col:
            period_cols.append(col)
    return period_cols


def read_label_rows(meta: dict[str, Any], metric: PrimitiveMetric) -> list[dict[str, Any]]:
    """Read one bank statement's raw CSV and return rows whose label matches `metric`."""
    import pandas as pd

    csv_path = DATA_DIR / str(meta.get("csv_path") or "")
    if not csv_path.exists():
        return []
    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception:
        return []
    if df.empty:
        return []

    label_col = _label_column(df)
    period_cols = _period_columns(df, meta, label_col)
    if not period_cols:
        return []

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        label = str(row.get(label_col, "")).strip()
        if not label_matches(metric.key, label):
            continue
        for period_col in period_cols:
            parsed = parse_number(str(row.get(period_col, "")))
            if parsed is None:
                continue
            source_unit, source_where = detect_unit(
                df, str(period_col), str(meta.get("context_page_text") or "")
            )
            source_unit = source_unit or "vnd"
            value = float(parsed) * conversion_factor(source_unit, metric.unit)
            out.append(
                {
                    "report_id": meta["report_id"],
                    "ticker": meta["ticker"],
                    "year": int(meta["year"]),
                    "doc_type": meta["doc_type"],
                    "statement_type": meta["statement_type"],
                    "statement_subtype": meta.get("statement_subtype"),
                    "table_pos": meta["table_pos"],
                    "ma_so": metric.ma_so,
                    "label": label,
                    "note_id": meta.get("note_id") or None,
                    "period": str(period_col).strip(),
                    "value": value,
                    "fact_source": "bank_label_fallback",
                    "source_unit": source_unit,
                    "source_unit_from": source_where,
                }
            )
    return out


__all__ = [
    "BANK_LABEL_FALLBACK_METRICS",
    "label_matches",
    "read_label_rows",
]
