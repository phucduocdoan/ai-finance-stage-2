"""Deterministic fact-table materialization for typed financial planning.

Formula planning works best when the model chooses operations over a normalized
table of facts instead of reasoning over raw statements. This module is the
service boundary for that table; callers pass canonical data and receive stable
rows keyed by ticker/year with requested raw and derived metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from finance_qa.modules.tools.metrics import CanonicalData, _candidate_rows, metric_ids, metric_value


@dataclass(frozen=True)
class FactRow:
    ticker: str
    year: int
    metrics: dict[str, float | None]

    def get(self, metric_id: str) -> float | None:
        return self.metrics.get(metric_id)

    def to_dict(self) -> dict[str, Any]:
        return {"ticker": self.ticker, "year": self.year, **self.metrics}


@dataclass(frozen=True)
class FactTable:
    rows: list[FactRow]
    metrics: tuple[str, ...]

    def to_records(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.rows]

    def available_metrics(self) -> dict[str, int]:
        """metric_id -> number of rows with a finite value."""
        return {
            metric: sum(1 for row in self.rows if row.metrics.get(metric) is not None)
            for metric in self.metrics
        }


def materialize_fact_table(
    data: CanonicalData,
    *,
    tickers: Iterable[str] | None = None,
    years: Iterable[int] | None = None,
    metrics: Iterable[str] | None = None,
) -> FactTable:
    """Return normalized ticker/year rows with raw and derived metric values."""
    requested = tuple(metrics or metric_ids())
    known = set(metric_ids())
    unknown = [metric for metric in requested if metric not in known]
    if unknown:
        raise ValueError("unknown metrics: " + ", ".join(sorted(unknown)))

    rows = []
    for row in _candidate_rows(data, list(tickers or []), [int(y) for y in years or []]):
        values = {
            metric: metric_value(row["metrics"], metric)
            for metric in requested
        }
        rows.append(FactRow(ticker=row["ticker"], year=int(row["year"]), metrics=values))
    return FactTable(rows=rows, metrics=requested)
