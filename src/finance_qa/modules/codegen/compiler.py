"""Compiler service for symbolic plans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from finance_qa.modules.codegen.ir import compile_plan as compile_plan_expression
from finance_qa.modules.codegen.ir import validate_plan


@dataclass(frozen=True)
class PlanCompiler:
    """Validate a symbolic plan and compile it to a pandas expression."""

    def validate(self, plan: object, frames: dict[str, pd.DataFrame]) -> list[str]:
        return validate_plan(plan, frames)

    def compile(self, plan: dict[str, Any], frames: dict[str, pd.DataFrame]) -> str:
        return compile_plan_expression(plan, frames)


DEFAULT_PLAN_COMPILER = PlanCompiler()


def compile_plan(plan: dict[str, Any], frames: dict[str, pd.DataFrame]) -> str:
    return DEFAULT_PLAN_COMPILER.compile(plan, frames)
