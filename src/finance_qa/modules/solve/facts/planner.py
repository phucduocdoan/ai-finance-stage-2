"""LLM planner for the structured fact executor."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.facts.execute import execute_plan, supported_v1_plan
from finance_qa.modules.solve.facts.metrics import canonical_metric
from finance_qa.modules.solve.facts.schema import StructuredPlan, StructuredPlannerOutput
from finance_qa.modules.solve.facts.store import StructuredFactError

PLAN_SYSTEM = """\
Bạn điền schema StructuredPlannerOutput cho bộ executor fact tài chính.
Chỉ trả về schema. Không viết code.

Fact table chỉ bao phủ balance_sheet, income_statement, cash_flow có mã số VAS.
Nếu câu hỏi cần thuyết minh, entity_info, equity_change, ngân hàng/CTCK đặc thù hoặc
không biểu diễn được bằng schema thì đặt supported=false.

Metric/expression/unit hợp lệ đã được ràng buộc trong schema enum.
Tickers, years, doc_type là scope đã resolve sẵn.
"""


async def aplan_structured(
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
    """Ask the LLM for a bounded plan.

    A bad or missing plan must fall back to raw-grid codegen, not to regex-derived
    solve semantics here. This function only fills retrieval-owned scope fields
    if the model omitted them.
    """
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
            max_tokens=8192 if planner_thinking else 768,
        ).with_structured_output(
            StructuredPlannerOutput
        ).ainvoke([
            SystemMessage(content=PLAN_SYSTEM),
            HumanMessage(content=user),
        ])
        planner_output = (
            result
            if isinstance(result, StructuredPlannerOutput)
            else StructuredPlannerOutput.model_validate(result)
        )
        plan = planner_output.to_structured_plan()
    except Exception as exc:
        return heuristic_plan(
            question=question, tickers=tickers, years=years, doc_type=doc_type,
            metric=metric, operation=operation, unit_hint=unit_hint,
            reason=f"structured planner unavailable: {type(exc).__name__}: {exc}",
        )
    if not plan.tickers:
        plan.tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not plan.years:
        plan.years = sorted({int(y) for y in years if y})
    if plan.doc_type == "unknown":
        plan.doc_type = doc_type if doc_type in {"consolidated", "separate"} else "unknown"
    resolved_unit = unit_from_hint(unit_hint) or unit_from_hint(question)
    if resolved_unit:
        plan.target_unit = resolved_unit
    return normalize_plan(plan)


def normalize_plan(plan: StructuredPlan) -> StructuredPlan:
    """Deterministic normalization that does not infer solve semantics."""
    if plan.axis == "year":
        plan.missing_policy = "fail"
    return plan


def heuristic_plan(
    *,
    question: str,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    metric: str = "",
    operation: str = "",
    unit_hint: str = "",
    reason: str = "structured planner unavailable",
) -> StructuredPlan:
    """No semantic fallback: planner failures should route to raw-table codegen."""
    _ = question, operation, unit_hint
    return normalize_plan(StructuredPlan(
        supported=False,
        operation="unsupported",
        axis="ticker" if len(tickers) > 1 else ("year" if len(years) > 1 else ""),
        tickers=tickers,
        years=years,
        doc_type=doc_type if doc_type in {"consolidated", "separate"} else "unknown",
        answer_metric=canonical_metric(metric),
        reason=reason,
    ))


async def asolve_structured_facts(
    state: dict[str, Any],
    *,
    planner_thinking: bool = False,
) -> dict[str, Any]:
    """Plan and execute a structured fact answer for one graph state."""
    plan = await aplan_structured(
        question=state["question"],
        tickers=list(state.get("tickers") or []),
        years=list(state.get("years") or []),
        doc_type=state.get("doc_type") or "unknown",
        metric=state.get("metric") or "",
        operation=state.get("operation") or "",
        unit_hint=state.get("unit_hint") or "",
        planner_thinking=planner_thinking,
    )
    ok, reason = supported_v1_plan(
        plan, state["question"], state.get("unit_hint") or "",
    )
    if not ok:
        raise StructuredFactError(reason)
    return execute_plan(
        plan,
        question=state["question"],
        unit_hint=state.get("unit_hint") or "",
    )


__all__ = [
    "aplan_structured",
    "asolve_structured_facts",
    "heuristic_plan",
    "normalize_plan",
]
