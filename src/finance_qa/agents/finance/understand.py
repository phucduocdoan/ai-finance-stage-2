"""Understand node: LLM extracts structured intent from the question.

Tickers are resolved rule-based from the BTC-provided code_stock.csv *before*
the LLM call (the map is authoritative, and the 8B otherwise hallucinated codes
like "Nam Kim" -> NKM instead of NKG). The resolved list is both fed to the LLM
as context and used as the final answer; the LLM only decides operation/metric/
shape, which have no authoritative source.
"""
from __future__ import annotations

import re
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


# Same reasoning as the ticker map above: when the question states the report
# scope in so many words, the words are authoritative and the 8B is not. It
# returned `unknown` for all six questions below, so the shortlist filter
# applied its unknown-means-consolidated default and every table submitted for
# them was the wrong scope -- and scope is not cosmetic: across the 97k
# (ticker, year, mã số, period) cells that carry both, consolidated and
# separate differ by >1% in 82% of cases (median 33-44%).
#
#   #780 "dự phòng ... của ngân hàng mẹ Bắc Á"
#   #783 "xét riêng khối ngân hàng mẹ"
#   #790 "trên BCTC riêng của VIB"
#   #795 "trên BCTC riêng của GAS"
#   #798 "(BCTC riêng)"
#   #890 "trên báo cáo tài chính riêng"
#
# Anchored to a preceding noun rather than a bare `riêng` / `mẹ`: both are
# unambiguous across all 1012 visible questions, but bare `riêng` would fire on
# ordinary prose like "nói riêng" and bare `mẹ` on a company name.
_SEPARATE_SCOPE = re.compile(
    r"(?:công ty|ngân hàng|tổng công ty)\s+mẹ"
    r"|(?:bctc|báo cáo tài chính|báo cáo)\s+riêng"
    r"|riêng lẻ",
    re.IGNORECASE,
)
_CONSOLIDATED_SCOPE = re.compile(r"hợp nhất", re.IGNORECASE)


def _explicit_separate_scope(question: str) -> bool:
    """True when the question names the separate/parent-only scope outright.

    One-directional on purpose: it only promotes `unknown`, never overrides a
    scope the model did commit to. 363 questions carry an explicit separate
    marker and the model labels every one of them correctly; this is the
    backstop for the handful it drops, so a miss here costs nothing beyond the
    behaviour we already have.

    A question naming *both* scopes is not a question this can answer: `doc_type`
    is one field for the whole question, and #952 ("báo cáo công ty mẹ các năm
    2022, 2023 và báo cáo hợp nhất các năm 2024, 2025") needs one scope per year.
    Committing to either half would hard-filter the other half's tables out,
    where leaving it `unknown` at least keeps both in the candidate pool. One
    such question in 1012 -- the guard is here so the rule keeps meaning "the
    question states one scope outright", not because the case is common.
    """
    return bool(
        _SEPARATE_SCOPE.search(question) and not _CONSOLIDATED_SCOPE.search(question)
    )


def make_understand(cfg):
    """Build the understand node bound to agent config `cfg`."""

    async def understand(state: FinanceState) -> dict:
        resolved = _resolve_tickers(state["question"])
        stated_separate = _explicit_separate_scope(state["question"])
        try:
            user = state["question"]
            if resolved:
                user += f"\n\n(Mã cổ phiếu đã xác định sẵn: {', '.join(resolved)})"
            result = await get_chat_model(
                thinking=cfg.understand_thinking,
                max_tokens=512,
            ).with_structured_output(UnderstandIntent).ainvoke(
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
                "doc_type": "separate" if stated_separate else "unknown",
                "multi_year": False,
                "multi_company": len(resolved) > 1,
                "unit_hint": "", "answer_shape": "derived",
                "errors": (state.get("errors") or []) + [f"understand: {e}"],
            }

        years = expand_years(result.years)
        # BTC's code_stock.csv is authoritative: use rule-based tickers, falling
        # back to the LLM's guess only when name matching found nothing.
        tickers = resolved or result.tickers
        doc_type = (
            "separate"
            if result.doc_type == "unknown" and stated_separate
            else result.doc_type
        )

        return {
            "tickers":       tickers,
            "years":         years,
            "metric":        result.metric,
            "operation":     result.operation,
            "doc_type":      doc_type,
            "multi_year":    bool(result.multi_year or len(years) > 1),
            "multi_company": bool(result.multi_company or len(tickers) > 1),
            "unit_hint":     result.unit_hint,
            "answer_shape":  result.answer_shape,
        }

    return understand
