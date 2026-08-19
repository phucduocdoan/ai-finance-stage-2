"""Shared typed primitives for raw-table linking.

These models describe bounded table evidence. They do not decide answers and do
not run retrieval; solvers use them to ask the LLM for semantic selection while
Python keeps validation and pandas execution deterministic.
"""
from __future__ import annotations

from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, Field

from finance_qa.modules.solve.cell_locator import PeriodIntent
from finance_qa.modules.solve.codegen import Unit


RawOperation = Literal["direct", "diff", "sum", "avg", "ratio", "select"]
RatioAggregate = Literal["none", "avg"]
DocType = Literal["consolidated", "separate", "unknown"]
ValueTransform = Literal["as_reported", "abs"]
RawCandidateKind = Literal["cell", "group"]
RawGroupOperation = Literal["sum"]


class RawScopeSlot(BaseModel):
    """One required ticker/year scope in a fixed-scope question."""

    ticker: str
    year: int

    @property
    def key(self) -> str:
        return f"{self.ticker}:{self.year}"


class RawLinkRequest(BaseModel):
    """A bounded raw-table linking request derived from understand state."""

    operation: RawOperation
    slots: list[RawScopeSlot] = Field(default_factory=list)
    doc_type: DocType = "unknown"
    period: PeriodIntent = "unknown"
    value_transform: ValueTransform = "as_reported"
    target_unit: Unit = "unknown"
    query_norm: str = ""
    query_tokens: list[str] = Field(default_factory=list)
    identity_tokens: list[str] = Field(default_factory=list)
    wants_total: bool = False
    ratio_aggregate: RatioAggregate = "none"


class RawCellRef(BaseModel):
    """One physical cell reference in a normalized DataFrame."""

    table_id: str
    row_position: int
    column: str
    value: float
    source_unit: Unit = "unknown"
    source_unit_from: str = ""

    def query(self, variable: str, transform: ValueTransform = "as_reported") -> str:
        raw = f"{variable}.iloc[{self.row_position}][{self.column!r}]"
        return f"abs({raw})" if transform == "abs" else raw


class RawCellCandidate(RawCellRef):
    """One real raw-table cell that can be referenced by pandas."""

    kind: RawCandidateKind = "cell"
    id: str
    slot_key: str
    ticker: str
    year: int
    row_label: str
    # Section headers above the row, outermost first. A leaf label such as
    # `Số cuối năm` only becomes linkable together with them.
    row_path: list[str] = Field(default_factory=list)
    is_total_row: bool = False
    row_score: float = 0.0
    table_score: float = 0.0
    column_score: float = 0.0
    score: float = 0.0
    table_context: str = ""

    @property
    def row_path_text(self) -> str:
        return " > ".join([*self.row_path, self.row_label]) if self.row_label else " > ".join(self.row_path)

    def ref(self) -> RawCellRef:
        return RawCellRef(
            table_id=self.table_id,
            row_position=self.row_position,
            column=self.column,
            value=self.value,
            source_unit=self.source_unit,
            source_unit_from=self.source_unit_from,
        )


class RawGroupCandidate(BaseModel):
    """A bounded expression over real cells, such as a row/column group sum."""

    kind: RawCandidateKind = "group"
    id: str
    slot_key: str
    ticker: str
    year: int
    label: str
    cells: list[RawCellRef] = Field(default_factory=list)
    group_op: RawGroupOperation = "sum"
    semantic_role: str = ""
    source_unit: Unit = "unknown"
    score: float = 0.0
    table_context: str = ""

    @property
    def table_ids(self) -> list[str]:
        return list(dict.fromkeys(cell.table_id for cell in self.cells))

    @property
    def value(self) -> float:
        if self.group_op == "sum":
            return sum(cell.value for cell in self.cells)
        raise ValueError(f"unsupported group operation {self.group_op}")

    def query(
        self,
        table_to_var: Mapping[str, str],
        transform: ValueTransform = "as_reported",
    ) -> str:
        if not self.cells:
            raise ValueError(f"group candidate {self.id} has no cells")
        terms = [cell.query(table_to_var[cell.table_id], transform) for cell in self.cells]
        if len(terms) == 1:
            return terms[0]
        if self.group_op == "sum":
            return "(" + " + ".join(terms) + ")"
        raise ValueError(f"unsupported group operation {self.group_op}")

    def unit_kinds(self) -> set[str]:
        return {cell.source_unit for cell in self.cells}


RawLinkedCandidate = RawCellCandidate | RawGroupCandidate
RawCandidateSequence = Sequence[RawLinkedCandidate]


__all__ = [
    "DocType",
    "RatioAggregate",
    "RawCandidateKind",
    "RawCandidateSequence",
    "RawCellCandidate",
    "RawCellRef",
    "RawGroupCandidate",
    "RawGroupOperation",
    "RawLinkRequest",
    "RawLinkedCandidate",
    "RawOperation",
    "RawScopeSlot",
    "ValueTransform",
]
