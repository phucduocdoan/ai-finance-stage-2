"""Regression tests for opt-in table profiles in codegen prompts."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve import codegen  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


frames = {"df1": pd.DataFrame({"Chỉ tiêu": ["Doanh thu thuần"], "Năm nay": [100.0]})}
names = {"df1": "AAA_financial_statements_2024_consolidated|7"}
old_profile_context = codegen.table_profile_context

try:
    codegen.table_profile_context = lambda table_id, df: f"Bản đồ bảng: {table_id}"  # type: ignore[assignment]
    default_prompt = codegen.build_prompt("Doanh thu thuần là bao nhiêu?", frames, names)
    profiled_prompt = codegen.build_prompt(
        "Doanh thu thuần là bao nhiêu?",
        frames,
        names,
        use_table_profiles=True,
    )
    check("table profiles are opt-in", "Bản đồ bảng:" not in default_prompt)
    check("profile block is included when enabled", "Bản đồ bảng: AAA_financial_statements_2024_consolidated|7" in profiled_prompt)

    def broken_profile(table_id, df):
        raise RuntimeError("boom")

    codegen.table_profile_context = broken_profile  # type: ignore[assignment]
    prompt = codegen.build_prompt(
        "Doanh thu thuần là bao nhiêu?",
        frames,
        names,
        use_table_profiles=True,
    )
    check("profile errors are prompt-local", "Bản đồ bảng: không tạo được (RuntimeError: boom)" in prompt)
finally:
    codegen.table_profile_context = old_profile_context  # type: ignore[assignment]

print("tất cả PASS")
