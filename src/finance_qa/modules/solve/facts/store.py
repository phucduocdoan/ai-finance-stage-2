"""DuckDB-backed access to the normalized main-statement fact table."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from finance_qa.core.paths import LONG_FORMAT_PATH, TABLE_METADATA_PATH
from finance_qa.modules.solve.facts import bank_fallback as _bank_fallback
from finance_qa.modules.solve.facts.metrics import PrimitiveMetric


@dataclass(frozen=True)
class Fact:
    value: float
    table_id: str
    row: dict[str, Any]


class StructuredFactError(RuntimeError):
    """Unsupported plan or missing fact."""


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
        if metric.key not in _bank_fallback.BANK_LABEL_FALLBACK_METRICS:
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
            rows.extend(_bank_fallback.read_label_rows(meta, metric))

        ranked = sorted(
            (row for row in rows if _finite(row.get("value"))),
            key=lambda row: _row_rank(row, year, period_kind, doc_type),
        )
        return ranked


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
