"""Understand node: LLM extracts structured intent from the question.

Tickers are resolved rule-based from the BTC-provided code_stock.csv *before*
the LLM call (the map is authoritative, and the 8B otherwise hallucinated codes
like "Nam Kim" -> NKM instead of NKG). The resolved list is both fed to the LLM
as context and used as the final answer; the LLM only decides operation/metric/
shape, which have no authoritative source.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from finance_qa.agents.finance.prompts import UNDERSTAND_SYSTEM
from finance_qa.agents.finance.state import FinanceState
from finance_qa.agents.finance.utils import expand_years
from finance_qa.core.llm import get_chat_model
from finance_qa.modules.data.preprocessing.questions import (
    build_name_index,
    find_tickers,
    load_ticker_data,
)

_VALID_TICKERS, _TICKER_NAMES = load_ticker_data()
_NAME_INDEX = build_name_index(_TICKER_NAMES)

Operation = Literal["lookup", "formula", "compare", "multi_step"]
DocType = Literal["consolidated", "separate", "unknown"]
AnswerShape = Literal["single_cell", "derived"]


class UnderstandIntent(BaseModel):
    """Semantic intent extracted from a finance question."""

    tickers: list[str] = Field(default_factory=list, description="Stock tickers mentioned in the question.")
    years: list[int] = Field(default_factory=list, description="Fiscal years or range endpoints mentioned in the question.")
    metric: str = Field(default="", description="Main financial metric, e.g. net_revenue, roe, de_ratio.")
    operation: Operation = Field(default="multi_step", description="High-level reasoning route.")
    doc_type: DocType = Field(default="unknown", description="Report scope requested by the question.")
    multi_year: bool = Field(default=False, description="True when the question spans multiple years.")
    multi_company: bool = Field(default=False, description="True when the question compares multiple companies.")
    unit_hint: str = Field(default="", description="Requested output unit, if any.")
    answer_shape: AnswerShape = Field(default="derived", description="single_cell for direct lookup, derived for computed answers.")

    @field_validator("tickers", mode="before")
    @classmethod
    def _normalise_tickers(cls, value):
        if not value:
            return []
        return [str(ticker).upper().strip() for ticker in value if str(ticker).strip()]


def _resolve_tickers(question: str) -> list[str]:
    """Ticker codes in the question, by direct code + company-name match."""
    return find_tickers(question, _VALID_TICKERS, _NAME_INDEX)


def make_understand(cfg):
    """Build the understand node bound to agent config `cfg`."""

    def understand(state: FinanceState) -> dict:
        resolved = _resolve_tickers(state["question"])
        try:
            user = state["question"]
            if resolved:
                user += f"\n\n(Mã cổ phiếu đã xác định sẵn: {', '.join(resolved)})"
            result = get_chat_model(
                thinking=cfg.understand_thinking,
                max_tokens=512,
            ).with_structured_output(UnderstandIntent).invoke(
                [
                    SystemMessage(content=UNDERSTAND_SYSTEM),
                    HumanMessage(content=user),
                ]
            )
            if not isinstance(result, UnderstandIntent):
                result = UnderstandIntent.model_validate(result)
        except Exception as e:
            return {
                "tickers": resolved, "years": [], "metric": "", "operation": "multi_step",
                "doc_type": "unknown", "multi_year": False,
                "multi_company": len(resolved) > 1,
                "unit_hint": "", "answer_shape": "derived",
                "errors": (state.get("errors") or []) + [f"understand: {e}"],
            }

        years = expand_years(result.years)
        # BTC's code_stock.csv is authoritative: use rule-based tickers, falling
        # back to the LLM's guess only when name matching found nothing.
        tickers = resolved or result.tickers

        return {
            "tickers":       tickers,
            "years":         years,
            "metric":        result.metric,
            "operation":     result.operation,
            "doc_type":      result.doc_type,
            "multi_year":    bool(result.multi_year or len(years) > 1),
            "multi_company": bool(result.multi_company or len(tickers) > 1),
            "unit_hint":     result.unit_hint,
            "answer_shape":  result.answer_shape,
        }

    return understand
