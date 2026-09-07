"""Decision and planner schemas for the raw-table linker."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.solution import Unit
from finance_qa.modules.solve.solvers.table_profiles.link_schema import RawOperation


class RawLinkerDecision(BaseModel):
    """LLM output: choose cells and an operation, not code."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when the candidates do not support the question.")
    operation: RawOperation = Field(default="direct")
    candidate_ids: list[str] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("candidate_ids", mode="before")
    @classmethod
    def _candidate_ids(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioSlotDecision(BaseModel):
    """LLM output for one scoped ratio: numerator cells over denominator cells."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    numerator_candidate_ids: list[str] = Field(default_factory=list)
    denominator_candidate_ids: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("numerator_candidate_ids", "denominator_candidate_ids", mode="before")
    @classmethod
    def _candidate_ids(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioDecision(BaseModel):
    """LLM output for ratio-from-components questions."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when candidates cannot express all numerator/denominator components.")
    operation: Literal["ratio"] = "ratio"
    slots: list[RawRatioSlotDecision] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawRatioOption(BaseModel):
    """One complete numerator or denominator option shown to the ratio planner."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slot_key: str
    side: Literal["numerator", "denominator"]
    candidate_ids: list[str] = Field(default_factory=list)
    source_kind: Literal["cell", "group"] = "cell"
    label: str = ""
    semantic_role: str = ""
    value: float = 0.0
    unit: Unit = "unknown"
    table_ids: list[str] = Field(default_factory=list)
    context: str = ""
    score: float = 0.0

    @field_validator("candidate_ids", "table_ids", mode="before")
    @classmethod
    def _string_list(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioOptionSlotDecision(BaseModel):
    """LLM output for one scoped ratio over pre-partitioned options."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    numerator_option_id: str
    denominator_option_id: str
    reason: str = ""


class RawRatioOptionDecision(BaseModel):
    """LLM output over ratio options, not raw mixed candidates."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when options cannot answer every slot.")
    operation: Literal["ratio"] = "ratio"
    slots: list[RawRatioOptionSlotDecision] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawSlotSemanticConstraint(BaseModel):
    """Semantic constraints for one required slot, emitted by the planner."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    row_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in the candidate row label.",
    )
    context_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in table/note context.",
    )
    include_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in the correct row/column/table context.",
    )
    exclude_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that identify close-but-wrong candidates.",
    )
    prefer_total_row: bool = False
    requires_component_sum: bool = False

    @field_validator("row_phrases", "context_phrases", "include_phrases", "exclude_phrases", mode="before")
    @classmethod
    def _phrases(cls, value):
        seen: set[str] = set()
        out: list[str] = []
        for raw in value or []:
            phrase = str(raw).strip()
            norm = _norm(phrase)
            if not phrase or not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(phrase[:120])
        return out[:8]


class RawSemanticPlan(BaseModel):
    """Planner output: semantic constraints, not candidate ids or code."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when candidates do not contain enough semantic evidence.")
    operation: RawOperation = Field(default="direct")
    slots: list[RawSlotSemanticConstraint] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawSearchPlan(BaseModel):
    """Planner output before candidate building: semantic query expansion."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when the question is too ambiguous for raw-table linking.")
    row_phrases: list[str] = Field(
        default_factory=list,
        description="Likely row-label phrases or discriminative row-label fragments.",
    )
    context_phrases: list[str] = Field(
        default_factory=list,
        description="Likely note/table context phrases.",
    )
    include_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that can appear in row, column, or table context.",
    )
    exclude_phrases: list[str] = Field(
        default_factory=list,
        description="Close-but-wrong phrases to reject if present.",
    )
    prefer_total_row: bool = False
    requires_component_sum: bool = Field(
        default=False,
        description="True only when the answer must sum multiple component rows/cells, not when row_phrases are synonyms.",
    )
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("row_phrases", "context_phrases", "include_phrases", "exclude_phrases", mode="before")
    @classmethod
    def _phrases(cls, value):
        seen: set[str] = set()
        out: list[str] = []
        for raw in value or []:
            phrase = str(raw).strip()
            norm = _norm(phrase)
            if not phrase or not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(phrase[:120])
        return out[:8]


class RawTableLinkError(Exception):
    """Unsupported or ambiguous raw-table linking plan."""


__all__ = [
    "RawLinkerDecision",
    "RawRatioDecision",
    "RawRatioOption",
    "RawRatioOptionDecision",
    "RawRatioOptionSlotDecision",
    "RawRatioSlotDecision",
    "RawSearchPlan",
    "RawSemanticPlan",
    "RawSlotSemanticConstraint",
    "RawTableLinkError",
]
