"""Structured fact solver over the normalized main-statement fact table.

This is deliberately narrower than the raw-grid codegen path. It handles the
class where the current solver fails most often: derived metrics over the main
VAS statements, especially selection questions across years or companies. The
LLM may choose a plan, but it never writes executable code or SQL; all formulae
and data access live here.

Compatibility facade: the implementation lives in `finance_qa.modules.solve.facts`
submodules (metrics, schema, store, execute, planner). This module re-exports
their public names so existing imports of
`finance_qa.modules.solve.facts.structured_facts` keep working unchanged.
"""
from __future__ import annotations

from finance_qa.modules.solve.facts.execute import execute_plan, supported_v1_plan
from finance_qa.modules.solve.facts.metrics import (
    DERIVED_ALIASES,
    EXPRESSION_KEYS,
    METRIC_KEYS,
    PRIMITIVES,
    _norm,
    canonical_measure,
    canonical_metric,
    metric_source_unit,
    metrics_in_text,
)
from finance_qa.modules.solve.facts.planner import (
    aplan_structured,
    asolve_structured_facts,
    heuristic_plan,
    normalize_plan,
)
from finance_qa.modules.solve.facts.schema import (
    MetricFilter,
    PlannerMetricFilter,
    StructuredPlan,
    StructuredPlannerOutput,
    StructuredSelectionPlan,
    UnsupportedStructuredPlan,
)
from finance_qa.modules.solve.facts.store import StatementFactStore, StructuredFactError

__all__ = [
    "METRIC_KEYS",
    "PRIMITIVES",
    "EXPRESSION_KEYS",
    "MetricFilter",
    "PlannerMetricFilter",
    "StatementFactStore",
    "StructuredFactError",
    "StructuredPlannerOutput",
    "StructuredSelectionPlan",
    "StructuredPlan",
    "UnsupportedStructuredPlan",
    "aplan_structured",
    "asolve_structured_facts",
    "canonical_metric",
    "canonical_measure",
    "execute_plan",
    "heuristic_plan",
    "metric_source_unit",
    "metrics_in_text",
    "supported_v1_plan",
]
