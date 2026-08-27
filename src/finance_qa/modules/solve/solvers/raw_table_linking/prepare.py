"""Top-level prepare orchestration for the raw-table linker."""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.modules.solve.solvers.raw_table_linking import candidates as _candidates
from finance_qa.modules.solve.solvers.raw_table_linking import decision as _decision
from finance_qa.modules.solve.solvers.raw_table_linking import planner as _planner
from finance_qa.modules.solve.solvers.raw_table_linking import ratio_options as _ratio_options
from finance_qa.modules.solve.solvers.raw_table_linking import render as _render
from finance_qa.modules.solve.solvers.raw_table_linking import request as _request
from finance_qa.modules.solve.solvers.raw_table_linking import solution as _solution
from finance_qa.modules.solve.solvers.raw_table_linking import validate as _validate
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioOptionDecision,
    RawSearchPlan,
    RawSemanticPlan,
    RawTableLinkError,
)


async def aprepare_raw_table_linker(
    state: Mapping[str, Any],
    *,
    use_planner: bool = False,
    planner_thinking: bool = False,
    use_ratio_groups: bool = False,
    build_request_func=_request.build_request,
    build_ratio_candidates_func=_candidates.build_ratio_candidates,
    build_candidates_func=_candidates.build_candidates,
    prefer_ratio_option_surface_func=_ratio_options._prefer_ratio_option_surface,
    build_ratio_options_func=_ratio_options.build_ratio_options,
    deterministic_ratio_option_decision_func=_ratio_options.deterministic_ratio_option_decision,
    ratio_decision_from_options_func=_validate.ratio_decision_from_options,
    aplan_raw_ratio_options_func=_planner.aplan_raw_ratio_options,
    aplan_raw_ratio_linker_func=_planner.aplan_raw_ratio_linker,
    build_ratio_solution_func=_solution.build_ratio_solution,
    candidate_table_ids_func=_render._candidate_table_ids,
    deterministic_decision_func=_decision.deterministic_decision,
    aplan_raw_search_func=_planner.aplan_raw_search,
    request_with_search_plan_func=_planner.request_with_search_plan,
    search_expansion_adds_slot_coverage_func=_decision.search_expansion_adds_slot_coverage,
    aplan_raw_table_linker_func=_planner.aplan_raw_table_linker,
    normalize_planner_decision_func=_decision.normalize_planner_decision,
    build_solution_func=_solution.build_solution,
) -> dict[str, Any]:
    """Prepare a validated raw-table plan for graph execution."""
    request, reason = build_request_func(state)
    if request is None:
        raise RawTableLinkError(reason)
    candidate_limit = 32 if request.operation == "ratio" else 12
    if request.operation == "ratio" and use_ratio_groups:
        candidates, cand_diag = build_ratio_candidates_func(
            request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            cell_limit_per_slot=max(candidate_limit, 80),
        )
    else:
        candidates, cand_diag = build_candidates_func(
            request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            limit_per_slot=candidate_limit,
        )
    if request.operation == "ratio":
        missing_candidate_slots = [
            slot.key for slot in request.slots
            if not any(candidate.slot_key == slot.key for candidate in candidates)
        ]
        if missing_candidate_slots:
            raise RawTableLinkError(f"missing ratio candidates for slots {missing_candidate_slots}")
        if not candidates:
            raise RawTableLinkError("no raw ratio candidates")
        if not use_planner:
            raise RawTableLinkError("ratio raw linker requires planner")
        decision_source = "ratio_candidate_planner"
        ratio_diag: dict[str, Any] = {}
        use_option_surface = use_ratio_groups or prefer_ratio_option_surface_func(request)
        if use_option_surface:
            options, option_diag = build_ratio_options_func(request, candidates, max_options_per_side=6)
            if use_ratio_groups and option_diag["missing_options"]:
                raise RawTableLinkError(f"missing ratio options for {option_diag['missing_options']}")
            option_decision = (
                deterministic_ratio_option_decision_func(request, options)
                if not option_diag["missing_options"]
                else RawRatioOptionDecision(
                    supported=False,
                    operation="ratio",
                    reason=f"missing ratio options for {option_diag['missing_options']}",
                )
            )
            if option_decision.supported:
                decision_source = "ratio_option_deterministic"
                ratio_decision = ratio_decision_from_options_func(request, option_decision, options)
            else:
                if use_ratio_groups:
                    option_decision = await aplan_raw_ratio_options_func(
                        question=str(state.get("question") or ""),
                        request=request,
                        options=options,
                        planner_thinking=planner_thinking,
                    )
                    decision_source = "ratio_option_planner"
                    ratio_decision = ratio_decision_from_options_func(request, option_decision, options)
                else:
                    ratio_decision = await aplan_raw_ratio_linker_func(
                        question=str(state.get("question") or ""),
                        request=request,
                        candidates=candidates,
                        planner_thinking=planner_thinking,
                    )
            ratio_diag = {
                "option_summary": option_diag,
                "options": [option.model_dump() for option in options],
                "option_decision": option_decision.model_dump(),
            }
        else:
            ratio_decision = await aplan_raw_ratio_linker_func(
                question=str(state.get("question") or ""),
                request=request,
                candidates=candidates,
                planner_thinking=planner_thinking,
            )
        solution, frames, names, chosen = build_ratio_solution_func(request, ratio_decision, candidates)
        return {
            "solution": solution,
            "frames": frames,
            "names": names,
            "table_ids": list(dict.fromkeys(
                table_id for candidate in chosen for table_id in candidate_table_ids_func(candidate)
            )),
            "diag": {
                "done": True,
                "request": request.model_dump(),
                "candidate_summary": cand_diag,
                "decision_source": decision_source,
                "decision": ratio_decision.model_dump(),
                "chosen": [candidate.model_dump() for candidate in chosen],
                **ratio_diag,
            },
        }

    deterministic = deterministic_decision_func(request, candidates)
    solution_request = request
    solution_candidates = candidates
    solution_cand_diag = cand_diag
    search_plan: RawSearchPlan | None = None
    semantic_plan: RawSemanticPlan | None = None
    semantic_decision: RawLinkerDecision | None = None
    expanded_cand_diag: dict[str, Any] | None = None
    search_expansion_used = False
    decision_source = "deterministic"
    decision = deterministic
    if not deterministic.supported:
        if not use_planner:
            if cand_diag["missing_slots"]:
                raise RawTableLinkError(f"missing candidates for slots {cand_diag['missing_slots']}")
            if not candidates:
                raise RawTableLinkError("no raw cell candidates")
            raise RawTableLinkError(f"deterministic raw linker: {deterministic.reason}")
        decision_source = "candidate_planner"
        search_plan = await aplan_raw_search_func(
            question=str(state.get("question") or ""),
            request=request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            planner_thinking=planner_thinking,
        )
        expanded_request = request_with_search_plan_func(request, search_plan)
        expanded_candidates, expanded_cand_diag = (
            (candidates, cand_diag)
            if expanded_request == request
            else build_candidates_func(
                expanded_request,
                table_ids=list(state.get("table_ids") or []),
                shortlist=list(state.get("shortlist") or []),
            )
        )
        if search_expansion_adds_slot_coverage_func(
            request, search_plan, candidates, expanded_candidates,
        ):
            solution_request = expanded_request
            solution_candidates = expanded_candidates
            solution_cand_diag = expanded_cand_diag
            search_expansion_used = True
            decision_source = "search_expanded_candidate_planner"
        decision = await aplan_raw_table_linker_func(
            question=str(state.get("question") or ""),
            request=solution_request,
            candidates=solution_candidates,
            planner_thinking=planner_thinking,
        )
        decision = normalize_planner_decision_func(solution_request, decision)
    solution, frames, names, chosen = build_solution_func(solution_request, decision, solution_candidates)
    return {
        "solution": solution,
        "frames": frames,
        "names": names,
        "table_ids": list(dict.fromkeys(candidate.table_id for candidate in chosen)),
        "diag": {
            "done": True,
            "request": solution_request.model_dump(),
            "initial_request": request.model_dump(),
            "candidate_summary": solution_cand_diag,
            "initial_candidate_summary": cand_diag,
            "decision_source": decision_source,
            "deterministic_decision": deterministic.model_dump(),
            "search_plan": search_plan.model_dump() if search_plan else None,
            "search_expansion_used": search_expansion_used,
            "expanded_candidate_summary": expanded_cand_diag,
            "semantic_plan": semantic_plan.model_dump() if semantic_plan else None,
            "semantic_decision": semantic_decision.model_dump() if semantic_decision else None,
            "decision": decision.model_dump(),
            "chosen": [candidate.model_dump() for candidate in chosen],
        },
    }


__all__ = ["aprepare_raw_table_linker"]
