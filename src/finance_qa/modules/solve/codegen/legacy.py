"""Legacy expression codegen adapter.

This is the current free-form pandas-expression generator. Keeping the import
behind this module makes it explicit that new plan-based codegen can sit beside
it without changing the graph contract.
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

