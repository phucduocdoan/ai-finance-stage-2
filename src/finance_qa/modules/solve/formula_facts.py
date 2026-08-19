"""Deterministic formula solver over main-statement facts.

This is a narrower sibling of ``structured_facts``. It handles non-selection
questions whose answer is one catalog metric/formula over a fixed ticker/year
scope: direct ratio, growth, difference, average, or median. The LLM only fills
a bounded schema; DuckDB/Python own fact access, formulae, and unit conversion.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.codegen import STRUCTURED_METHOD
from finance_qa.modules.solve.intent import (
    AVG_CUE as _AVG_CUE,
    DIFF_CUE_STRICT as _DIFF_CUE,
    GROWTH_CUE as _GROWTH_CUE,
    MEDIAN_CUE as _MEDIAN_CUE,
    SELECTION_MARKER_ACCENTED as _SELECTION_MARKER,
)
from finance_qa.modules.solve.structured_facts import (
    METRIC_KEYS,
    StructuredFactError,
    StructuredPlan,
    _norm,
    canonical_metric,
    execute_plan,
    metric_source_unit,
    metrics_in_text,
)
from finance_qa.modules.solve.units import MONEY_SCALE, unit_from_hint


FormulaOperation = Literal["lookup", "ratio", "growth", "diff", "avg", "median"]
DocType = Literal["consolidated", "separate", "unknown"]
PlannerMetric = Literal[*METRIC_KEYS]
PlannerTargetUnit = Literal[
    "",
    "vnd",
    "thousand_vnd",
    "million_vnd",
    "billion_vnd",
    "hundred_billion_vnd",
    "trillion_vnd",
    "percent",
    "ratio",
    "count",
    "year",
    "unknown",
]

METRIC_SCHEMA_DESCRIPTION = (
    "Catalog metric key over VAS main statements. Direct facts: net_revenue, "
    "cogs, gross_profit, interest_expense, financial_income, profit_before_tax, net_profit, cfo, "
    "current_assets, cash_and_equivalents, inventory, total_assets, liabilities, "
    "current_liabilities, equity. Derived facts: de_ratio, debt_to_assets, "
    "current_ratio, quick_ratio, working_capital, gross_margin, net_margin, "
    "roe, roa, interest_coverage, cfo_to_net_profit, cfo_to_revenue, "
    "cfo_to_current_liabilities, inventory_to_assets, inventory_days."
)

_FORMULA_CUE = re.compile(
    r"\b(?:roe|roa|d/e|cfo/lnst|cfo/dtt)\b|"
    r"t[ỷy]\s*(?:l[ệe]|s[oố]|su[aấ]t|tr[oọ]ng)|h[ệe]\s*s[oố]|bi[eê]n\s+l[ợo]i|"
    r"t[aă]ng\s+tr[uư][ởo]ng|ch[eê]nh\s+l[ệe]ch|trung\s+b[iì]nh|b[iì]nh\s+qu[aâ]n|"
    r"trung\s+v[ịi]|so\s+v[ớo]i|chia\s+cho",
    re.I,
)
_SEGMENT_QUALIFIER = re.compile(
    r"\b(?:doanh\s+thu|l[ợo]i\s+nhu[ậa]n|chi\s+ph[ií])\b[^?.]{0,50}"
    r"\bt[ừu]\s+ho[ạa]t\s+[đd][ộo]ng\b|\bm[ảa]ng\b|\bng[aà]nh\b|\bl[ĩi]nh\s+v[ựu]c\b",
    re.I,
)
_BORROWING_MARKER = re.compile(
    r"\bn[ợo]\s+vay\b|\bvay\s+ng[ắa]n\s+h[ạa]n\b|\bkho[ảa]n\s+vay\b",
    re.I,
)
_NOTE_LIKE_MARKER = re.compile(
    r"t[aà]i\s+s[ảa]n\s+c[ốo]\s+[đd][ịi]nh|"
    r"b[ấa]t\s+[đd][ộo]ng\s+s[ảa]n\s+[đd][ầa]u\s+t[ưu]|"
    r"thu[ếe]\s+thu\s+nh[ậa]p\s+ho[aã]n\s+l[ạa]i|"
    r"ch[ứu]ng\s+kho[aá]n|cho\s+vay|d[ựu]\s+ph[oò]ng|c[ổo]\s+phi[ếe]u",
    re.I,
)
_DETAIL_QUALIFIER_TERMS = (
    "nguyen vat lieu",
    "gia goc",
    "the chap",
    "cam co",
    "chiet khau",
    "khu vuc",
    "mien bac",
    "mien trung",
    "mien nam",
    "lai vay phai tra",
    "nguoi ban",
)
_MONEY_UNITS = frozenset(MONEY_SCALE)


class FormulaSupportedPlan(BaseModel):
    """One non-selection formula over a fixed candidate set."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["formula"] = Field(default="formula")
    operation: FormulaOperation = Field(
        description=(
            "lookup/ratio: one ticker and one year; growth: one ticker and two "
            "years; diff: two tickers in one year or one ticker in two years; "
            "avg/median: one ticker over multiple years."
        )
    )
    tickers: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    doc_type: DocType = Field(default="unknown")
    answer_metric: PlannerMetric = Field(description=METRIC_SCHEMA_DESCRIPTION)
    target_unit: PlannerTargetUnit = Field(default="")
    reason: str = Field(default="")

    @field_validator("tickers", mode="before")
    @classmethod
    def _tickers(cls, value):
        return [str(v).upper().strip() for v in (value or []) if str(v).strip()]

    @field_validator("years", mode="before")
    @classmethod
    def _years(cls, value):
        return sorted({int(v) for v in (value or []) if str(v).strip().isdigit()})

    def to_structured_plan(self) -> StructuredPlan:
        return StructuredPlan(
            supported=True,
            operation=self.operation,
            tickers=self.tickers,
            years=self.years,
            doc_type=self.doc_type,
            answer_metric=self.answer_metric,
            target_unit=self.target_unit,
        )


class FormulaUnsupportedPlan(BaseModel):
    """Explicit fallback branch for questions outside the formula schema."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["unsupported"] = Field(default="unsupported")
    reason: str = Field(description="Why this question needs raw-table codegen.")

    def to_structured_plan(self) -> StructuredPlan:
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason=self.reason,
        )


FormulaPlan = Annotated[
    FormulaSupportedPlan | FormulaUnsupportedPlan,
    Field(discriminator="kind"),
]


class FormulaPlannerOutput(BaseModel):
    """LLM-facing root schema for the formula facts branch."""

    model_config = ConfigDict(extra="forbid")

    plan: FormulaPlan

    def to_structured_plan(self) -> StructuredPlan:
        return self.plan.to_structured_plan()


class FormulaFactError(StructuredFactError):
    """Unsupported formula plan or missing primitive facts."""


def _metric_hint_present(question: str, metric: str = "") -> bool:
    return bool(
        metrics_in_text(question)
        or _FORMULA_CUE.search(question)
    )


def _metric_anchors(question: str) -> set[str]:
    """Catalog metrics explicitly grounded by the question text."""
    return set(metrics_in_text(question))


def _has_detail_qualifier(question: str) -> bool:
    norm = f" {_norm(question)} "
    return any(f" {term} " in norm for term in _DETAIL_QUALIFIER_TERMS)


def _resolved_scope(state: dict[str, Any]) -> tuple[list[str], list[int], str]:
    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    years = sorted({int(y) for y in (state.get("years") or []) if y})
    doc_type = str(state.get("doc_type") or "unknown")
    if doc_type not in {"consolidated", "separate"}:
        doc_type = "unknown"
    return tickers, years, doc_type


def _ratio_anchor(anchors: set[str]) -> str:
    candidates = sorted(metric for metric in anchors if metric_source_unit(metric) == "ratio")
    return candidates[0] if len(candidates) == 1 else ""


def deterministic_formula_plan(state: dict[str, Any]) -> StructuredPlan:
    """Build a formula plan without an LLM when text and scope are unambiguous."""
    attempt, reason = should_attempt_formula_facts(state)
    if not attempt:
        return StructuredPlan(supported=False, operation="unsupported", reason=reason)

    question = str(state.get("question") or "")
    unit_hint = str(state.get("unit_hint") or "")
    tickers, years, doc_type = _resolved_scope(state)
    anchors = _metric_anchors(question)
    target = unit_from_hint(question) or unit_from_hint(unit_hint) or ""
    norm_question = _norm(question)

    operation: FormulaOperation | None = None
    answer_metric = ""
    if len(tickers) == 1 and len(years) == 1:
        ratio = _ratio_anchor(anchors)
        if ratio:
            operation = "ratio"
            answer_metric = ratio
        elif "working_capital" in anchors:
            operation = "lookup"
            answer_metric = "working_capital"
    elif len(tickers) == 1 and len(years) == 2 and len(anchors) == 1:
        metric = next(iter(anchors))
        if metric_source_unit(metric) in _MONEY_UNITS:
            if _GROWTH_CUE.search(norm_question):
                operation = "growth"
                answer_metric = metric
            elif _DIFF_CUE.search(norm_question):
                operation = "diff"
                answer_metric = metric
    elif len(tickers) == 2 and len(years) == 1 and len(anchors) == 1:
        metric = next(iter(anchors))
        if metric_source_unit(metric) in _MONEY_UNITS and _DIFF_CUE.search(norm_question):
            operation = "diff"
            answer_metric = metric
    elif len(tickers) == 1 and len(years) >= 2 and len(anchors) == 1:
        metric = next(iter(anchors))
        if metric_source_unit(metric) in _MONEY_UNITS:
            if _MEDIAN_CUE.search(norm_question):
                operation = "median"
                answer_metric = metric
            elif _AVG_CUE.search(norm_question):
                operation = "avg"
                answer_metric = metric

    if not operation or not answer_metric:
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason="no deterministic formula plan",
        )

    plan = StructuredPlan(
        supported=True,
        operation=operation,
        tickers=tickers,
        years=years,
        doc_type=doc_type,
        answer_metric=answer_metric,
        target_unit=target,
    )
    ok, reason = supported_formula_plan(plan, question, unit_hint, str(state.get("metric") or ""))
    if not ok:
        return StructuredPlan(supported=False, operation="unsupported", reason=reason)
    return plan


def should_attempt_formula_facts(state: dict[str, Any]) -> tuple[bool, str]:
    """Cheap fail-closed gate before spending a planner call."""
    question = str(state.get("question") or "")
    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    years = [int(y) for y in (state.get("years") or []) if y]
    if not tickers or not years:
        return False, "needs resolved ticker/year scope"
    if _SELECTION_MARKER.search(question):
        return False, "selection question"
    if _SEGMENT_QUALIFIER.search(question):
        return False, "segment metric outside main-statement facts"
    if _BORROWING_MARKER.search(question):
        return False, "borrowings metric outside main-statement facts"
    if _NOTE_LIKE_MARKER.search(question):
        return False, "note-like metric outside main-statement facts"
    if _has_detail_qualifier(question):
        return False, "detail metric outside main-statement facts"
    if not _metric_hint_present(question, str(state.get("metric") or "")):
        return False, "no formula cue"
    if not _metric_anchors(question):
        return False, "no supported metric anchor"
    return True, ""


def _answer_source_unit(plan: StructuredPlan) -> str:
    if plan.operation == "growth":
        return "ratio"
    return metric_source_unit(plan.answer_metric)


def _unit_compatible(source_unit: str, target_unit: str) -> bool:
    if not target_unit or target_unit == "unknown":
        return True
    if source_unit == "ratio":
        return target_unit in {"ratio", "percent"}
    if source_unit in _MONEY_UNITS:
        return target_unit in _MONEY_UNITS
    if source_unit == "year":
        return target_unit == "year"
    if source_unit in {"count", "share"}:
        return target_unit in {"count", "share"}
    return True


def _resolved_target(question: str, unit_hint: str, plan: StructuredPlan, source_unit: str) -> str:
    return (
        (plan.target_unit if plan.target_unit != "unknown" else "")
        or unit_from_hint(question)
        or unit_from_hint(unit_hint)
        or source_unit
    )


def supported_formula_plan(
    plan: StructuredPlan,
    question: str,
    unit_hint: str = "",
    metric: str = "",
) -> tuple[bool, str]:
    """Validate the non-selection slice before it touches facts."""
    if not plan.supported or plan.operation == "unsupported":
        return False, plan.reason or "plan unsupported"
    if _SELECTION_MARKER.search(question):
        return False, "selection question outside formula_facts"
    if plan.operation not in {"lookup", "ratio", "growth", "diff", "avg", "median"}:
        return False, f"operation {plan.operation} outside formula_facts"
    if not canonical_metric(plan.answer_metric):
        return False, "answer_metric is not in the catalog"
    anchors = _metric_anchors(question)
    if plan.answer_metric not in anchors:
        return False, f"answer_metric {plan.answer_metric} is not anchored in the question"
    if plan.answer_metric in {"net_revenue", "gross_profit", "net_profit", "cogs"}:
        if _SEGMENT_QUALIFIER.search(question):
            return False, "segment metric outside main-statement facts"
    if plan.answer_metric in {
        "liabilities", "current_liabilities", "de_ratio", "debt_to_assets",
        "current_ratio", "quick_ratio",
    } and _BORROWING_MARKER.search(question):
        return False, "borrowings metric outside main-statement facts"
    if plan.answer_expression or plan.selector_metric or plan.filters or plan.year_offset:
        return False, "selection/expression fields are outside formula_facts"

    n_tickers = len(plan.tickers)
    n_years = len(plan.years)
    if plan.operation in {"lookup", "ratio"} and (n_tickers != 1 or n_years != 1):
        return False, "lookup/ratio needs exactly one ticker and one year"
    if plan.operation == "growth" and (n_tickers != 1 or n_years < 2):
        return False, "growth needs one ticker and at least two years"
    if plan.operation == "diff":
        if not ((n_tickers == 2 and n_years == 1) or (n_tickers == 1 and n_years >= 2)):
            return False, "diff needs two tickers in one year or one ticker in two years"
    if plan.operation in {"avg", "median"} and (n_tickers != 1 or n_years < 2):
        return False, "avg/median needs one ticker and at least two years"

    source_unit = _answer_source_unit(plan)
    target = _resolved_target(question, unit_hint, plan, source_unit)
    if not _unit_compatible(source_unit, target):
        return False, f"{source_unit} answer cannot target {target}"
    return True, ""


def execute_formula_plan(
    plan: StructuredPlan,
    *,
    question: str,
    unit_hint: str = "",
    metric: str = "",
) -> dict[str, Any]:
    ok, reason = supported_formula_plan(plan, question, unit_hint, metric)
    if not ok:
        raise FormulaFactError(reason)
    return execute_plan(plan, question=question, unit_hint=unit_hint)


FORMULA_PLAN_SYSTEM = """\
Bạn điền schema FormulaPlannerOutput cho executor fact tài chính.
Chỉ trả về schema. Không viết code.

Chỉ dùng kind=formula khi câu hỏi là phép tính trực tiếp trên một metric catalog
với ticker/year đã xác định: lookup, ratio, growth, diff, avg, hoặc median.
Nếu câu hỏi cần chọn năm/công ty theo cao nhất/thấp nhất, cần thuyết minh, entity
table, equity_change, hoặc metric ngoài catalog, dùng kind=unsupported.
Metric/unit hợp lệ đã được ràng buộc trong schema enum.
"""


async def aplan_formula_facts(
    *,
    question: str,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    metric: str = "",
    operation: str = "",
    unit_hint: str = "",
    planner_thinking: bool = False,
) -> StructuredPlan:
    """Ask the LLM for a bounded formula plan; never infer semantics on failure."""
    try:
        user = (
            f"Câu hỏi: {question}\n"
            f"Tickers đã resolve: {tickers}\n"
            f"Years đã resolve: {years}\n"
            f"doc_type: {doc_type}\n"
            f"understand.metric: {metric}\n"
            f"understand.operation: {operation}\n"
            f"unit_hint: {unit_hint}\n"
        )
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            FormulaPlannerOutput,
            method=STRUCTURED_METHOD,
        ).ainvoke([
            SystemMessage(content=FORMULA_PLAN_SYSTEM),
            HumanMessage(content=user),
        ])
        output = (
            result
            if isinstance(result, FormulaPlannerOutput)
            else FormulaPlannerOutput.model_validate(result)
        )
        plan = output.to_structured_plan()
    except Exception as exc:  # noqa: BLE001 - fallback is product behaviour
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason=f"formula planner unavailable: {type(exc).__name__}: {exc}",
        )

    if plan.supported:
        if not plan.tickers:
            plan.tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not plan.years:
            plan.years = sorted({int(y) for y in years if y})
        if plan.doc_type == "unknown":
            plan.doc_type = doc_type if doc_type in {"consolidated", "separate"} else "unknown"
        resolved_unit = unit_from_hint(unit_hint) or unit_from_hint(question)
        if resolved_unit:
            plan.target_unit = resolved_unit
    return plan


async def asolve_formula_facts(
    state: dict[str, Any],
    *,
    planner_thinking: bool = False,
) -> dict[str, Any]:
    """Plan and execute one non-selection formula answer."""
    attempt, reason = should_attempt_formula_facts(state)
    if not attempt:
        raise FormulaFactError(reason)
    deterministic = deterministic_formula_plan(state)
    if deterministic.supported:
        return execute_formula_plan(
            deterministic,
            question=state["question"],
            unit_hint=state.get("unit_hint") or "",
            metric=state.get("metric") or "",
        )
    plan = await aplan_formula_facts(
        question=state["question"],
        tickers=list(state.get("tickers") or []),
        years=list(state.get("years") or []),
        doc_type=state.get("doc_type") or "unknown",
        metric=state.get("metric") or "",
        operation=state.get("operation") or "",
        unit_hint=state.get("unit_hint") or "",
        planner_thinking=planner_thinking,
    )
    return execute_formula_plan(
        plan,
        question=state["question"],
        unit_hint=state.get("unit_hint") or "",
        metric=state.get("metric") or "",
    )


__all__ = [
    "FORMULA_PLAN_SYSTEM",
    "FormulaFactError",
    "FormulaPlannerOutput",
    "FormulaSupportedPlan",
    "FormulaUnsupportedPlan",
    "aplan_formula_facts",
    "asolve_formula_facts",
    "deterministic_formula_plan",
    "execute_formula_plan",
    "should_attempt_formula_facts",
    "supported_formula_plan",
]
