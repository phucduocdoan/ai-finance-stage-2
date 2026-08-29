"""Pandas-expression codegen adapter.

This is the current, only live codegen path in production — not a legacy
fallback. It re-exports `codegen.codegen`'s free-form pandas-expression
generator for the pipeline nodes to import.
"""

from finance_qa.modules.solve.codegen.codegen import (
    CODEGEN_SYSTEM,
    MAX_TOKENS,
    FindRows,
    ShowTable,
    agenerate,
    build_prompt,
)

__all__ = [
    "CODEGEN_SYSTEM",
    "MAX_TOKENS",
    "FindRows",
    "ShowTable",
    "agenerate",
    "build_prompt",
]

