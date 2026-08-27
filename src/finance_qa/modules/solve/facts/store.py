"""DuckDB-backed access to the normalized main-statement fact table."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from finance_qa.core.paths import DATA_DIR, LONG_FORMAT_PATH, TABLE_METADATA_PATH
from finance_qa.modules.solve.common.units import conversion_factor, detect_unit
from finance_qa.modules.solve.facts.metrics import PrimitiveMetric, _norm
from finance_qa.modules.tools.numeric import parse_number


@dataclass(frozen=True)
class Fact:
    value: float
    table_id: str
    row: dict[str, Any]


class StructuredFactError(RuntimeError):
    """Unsupported plan or missing fact."""


_BANK_LABEL_FALLBACK_METRICS = frozenset({
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


def _bank_label_matches(metric_key: str, label: object) -> bool:
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


def _bank_label_column(df) -> str:
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


def _bank_period_columns(df, meta: dict[str, Any], label_col: str) -> list[str]:
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


class StatementFactStore:
    """DuckDB-backed access to ``long_format.parquet``."""

    def __init__(self, path=LONG_FORMAT_PATH):
        import duckdb

        self.path = str(path)
        self._metadata_by_scope: dict[tuple[str, int, str], list[dict[str, Any]]] | None = None
        self.conn = duckdb.connect(database=":memory:")
        escaped = self.path.replace("'", "''")
        self.conn.execute(
            "CREATE VIEW statement_facts AS "
            f"SELECT * FROM read_parquet('{escaped}')"
        )

    def rows(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        statement_type: str,
        ma_so: str,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [ticker.upper(), int(year), statement_type, str(ma_so)]
        where = [
            "ticker = ?", "year = ?", "statement_type = ?", "ma_so = ?",
        ]
        if doc_type in {"consolidated", "separate"}:
            where.append("doc_type = ?")
            params.append(doc_type)
        sql = (
            "SELECT report_id, ticker, year, doc_type, statement_type, "
            "statement_subtype, table_pos, ma_so, label, note_id, period, value "
            "FROM statement_facts WHERE "
            + " AND ".join(where)
        )
        return self.conn.execute(sql, params).fetch_df().to_dict("records")

    def value(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        metric: PrimitiveMetric,
        period_kind: str = "end",
    ) -> Fact:
        rows = self.rows(
            ticker=ticker, year=year, doc_type=doc_type,
            statement_type=metric.statement_type, ma_so=metric.ma_so,
        )
        ranked = sorted(
            (row for row in rows if _finite(row.get("value"))),
            key=lambda row: _row_rank(row, year, period_kind, doc_type),
        )
        if not ranked:
            ranked = self._bank_label_fallback_rows(
                ticker=ticker,
                year=year,
                doc_type=doc_type,
                metric=metric,
                period_kind=period_kind,
            )
        if not ranked:
            raise StructuredFactError(
                f"missing fact: {ticker} {year} {doc_type} "
                f"{metric.statement_type} ma_so={metric.ma_so}"
            )
        row = ranked[0]
        if doc_type == "unknown" and row.get("doc_type") != "consolidated":
            raise StructuredFactError(
                f"missing consolidated fact: {ticker} {year} "
                f"{metric.statement_type} ma_so={metric.ma_so}"
            )
        table_id = f"{row['report_id']}|{int(row['table_pos'])}"
        return Fact(float(row["value"]), table_id, row)

    def _metadata_index(self) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
        if self._metadata_by_scope is not None:
            return self._metadata_by_scope
        by_scope: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
        with TABLE_METADATA_PATH.open(encoding="utf-8") as fp:
            for line in fp:
                rec = json.loads(line)
                ticker = str(rec.get("ticker") or "").upper()
                year = rec.get("year")
                statement_type = str(rec.get("statement_type") or "")
                if not ticker or not year or statement_type not in {"balance_sheet", "income_statement", "cash_flow"}:
                    continue
                by_scope.setdefault((ticker, int(year), statement_type), []).append(rec)
        self._metadata_by_scope = by_scope
        return by_scope

    def _bank_label_fallback_rows(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        metric: PrimitiveMetric,
        period_kind: str,
    ) -> list[dict[str, Any]]:
        if metric.key not in _BANK_LABEL_FALLBACK_METRICS:
            return []
        candidates = self._metadata_index().get(
            (ticker.upper(), int(year), metric.statement_type), []
        )
        rows: list[dict[str, Any]] = []
        for meta in candidates:
            if meta.get("industry_segment") != "bank":
                continue
            if meta.get("has_ma_so_column"):
                continue
            if doc_type in {"consolidated", "separate"} and meta.get("doc_type") != doc_type:
                continue
            rows.extend(self._read_bank_label_rows(meta, metric))

        ranked = sorted(
            (row for row in rows if _finite(row.get("value"))),
            key=lambda row: _row_rank(row, year, period_kind, doc_type),
        )
        return ranked

    def _read_bank_label_rows(self, meta: dict[str, Any], metric: PrimitiveMetric) -> list[dict[str, Any]]:
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

        label_col = _bank_label_column(df)
        period_cols = _bank_period_columns(df, meta, label_col)
        if not period_cols:
            return []

        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            label = str(row.get(label_col, "")).strip()
            if not _bank_label_matches(metric.key, label):
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


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _period_kind(period: object, year: int) -> str:
    text = str(period or "").lower()
    if (
        re.search(r"(?<!\d)0?1[/.]0?1(?!\d)", text)
        or "đầu" in text
        or str(year - 1) in text
    ):
        return "begin"
    if re.search(r"(?<!\d)31[/.]12(?!\d)", text) or "cuối" in text or str(year) in text:
        return "end"
    return "current"


def _row_rank(row: dict[str, Any], year: int, wanted: str, doc_type: str) -> tuple:
    period = _period_kind(row.get("period"), year)
    label = str(row.get("label") or "").strip()
    if doc_type == "unknown":
        doc_penalty = 0 if row.get("doc_type") == "consolidated" else 1
    else:
        doc_penalty = 0 if row.get("doc_type") == doc_type else 1
    period_penalty = 0 if period == wanted else (1 if period == "current" else 2)
    label_penalty = 1 if label == str(row.get("ma_so")) else 0
    return (doc_penalty, period_penalty, label_penalty, int(row.get("table_pos") or 999))


@lru_cache(maxsize=1)
def default_store() -> StatementFactStore:
    return StatementFactStore()


__all__ = [
    "Fact",
    "StatementFactStore",
    "StructuredFactError",
    "default_store",
]
