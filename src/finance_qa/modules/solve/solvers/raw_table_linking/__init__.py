"""Raw-table linker internals split out of the legacy facade."""

from finance_qa.modules.solve.solvers.raw_table_linking.candidates import (
    build_candidates,
    build_ratio_candidates,
)
from finance_qa.modules.solve.solvers.raw_table_linking.decision import (
    decision_from_semantic_plan,
    deterministic_decision,
    normalize_planner_decision,
    search_expansion_adds_slot_coverage,
)
from finance_qa.modules.solve.solvers.raw_table_linking.planner import (
    RAW_LINKER_SYSTEM,
    RAW_RATIO_LINKER_SYSTEM,
    RAW_RATIO_OPTION_SYSTEM,
    RAW_SEARCH_SYSTEM,
    RAW_SEMANTIC_SYSTEM,
    aplan_raw_ratio_linker,
    aplan_raw_ratio_options,
    aplan_raw_search,
    aplan_raw_semantics,
    aplan_raw_table_linker,
    request_with_search_plan,
    semantic_plan_from_search_plan,
)
from finance_qa.modules.solve.solvers.raw_table_linking.ratio_options import (
    build_ratio_options,
    deterministic_ratio_option_decision,
)
from finance_qa.modules.solve.solvers.raw_table_linking.request import (
    build_request,
    should_attempt_raw_table_linker,
)
from finance_qa.modules.solve.solvers.raw_table_linking.render import (
    render_candidates,
    render_ratio_options,
    render_table_contexts,
)
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioDecision,
    RawRatioOption,
    RawRatioOptionDecision,
    RawRatioOptionSlotDecision,
    RawRatioSlotDecision,
    RawSearchPlan,
    RawSemanticPlan,
    RawSlotSemanticConstraint,
    RawTableLinkError,
)
from finance_qa.modules.solve.solvers.raw_table_linking.validate import (
    ratio_decision_from_options,
    validate_decision,
    validate_ratio_decision,
)

__all__ = [
    "RAW_LINKER_SYSTEM",
    "RAW_RATIO_LINKER_SYSTEM",
    "RAW_RATIO_OPTION_SYSTEM",
    "RAW_SEARCH_SYSTEM",
    "RAW_SEMANTIC_SYSTEM",
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
    "aplan_raw_ratio_linker",
    "aplan_raw_ratio_options",
    "aplan_raw_search",
    "aplan_raw_semantics",
    "aplan_raw_table_linker",
    "build_candidates",
    "build_request",
    "build_ratio_options",
    "build_ratio_candidates",
    "decision_from_semantic_plan",
    "deterministic_ratio_option_decision",
    "deterministic_decision",
    "normalize_planner_decision",
    "render_candidates",
    "render_ratio_options",
    "render_table_contexts",
    "request_with_search_plan",
    "ratio_decision_from_options",
    "search_expansion_adds_slot_coverage",
    "semantic_plan_from_search_plan",
    "should_attempt_raw_table_linker",
    "validate_decision",
    "validate_ratio_decision",
]
