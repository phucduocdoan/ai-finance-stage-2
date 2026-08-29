"""Typed linking primitives shared by table-based solvers."""

from finance_qa.modules.solve.solvers.table_profiles.columns import (
    ColumnSemanticRole,
    LinkedColumnProfile,
    build_column_group_candidates,
    build_column_profiles,
)
from finance_qa.modules.solve.solvers.table_profiles.rows import (
    MAX_PATH_DEPTH,
    LinkedRowProfile,
    build_row_profiles,
)
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    DocType,
    RatioAggregate,
    RawCandidateKind,
    RawCellCandidate,
    RawCellRef,
    RawGroupCandidate,
    RawGroupOperation,
    RawLinkRequest,
    RawLinkedCandidate,
    RawOperation,
    RawScopeSlot,
    ValueTransform,
)

__all__ = [
    "ColumnSemanticRole",
    "DocType",
    "LinkedColumnProfile",
    "LinkedRowProfile",
    "MAX_PATH_DEPTH",
    "RatioAggregate",
    "RawCandidateKind",
    "RawCellCandidate",
    "RawCellRef",
    "RawGroupCandidate",
    "RawGroupOperation",
    "RawLinkRequest",
    "RawLinkedCandidate",
    "RawOperation",
    "RawScopeSlot",
    "ValueTransform",
    "build_column_group_candidates",
    "build_column_profiles",
    "build_row_profiles",
]
