"""Unit tests for the deterministic plan validator/compiler (no LLM calls)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.execution.query import run_query
from finance_qa.planning.ir import (
    binding_alignment_errors,
    compile_plan,
    parse_plan_response,
    prune_unused_bindings,
    repair_binding_alignment,
    repair_binding_column,
    repair_formula_binding_names,
    repair_repeated_select_answers,
    repair_select_answer_years,
    validate_plan,
)


frames = {
    "df1": pd.DataFrame({"label": ["Revenue", "Profit"], "2023": [100.0, 20.0]}),
    "df2": pd.DataFrame({"label": ["Revenue", "Profit"], "2024": [150.0, 45.0]}),
}


def binding(binding_id: str, variable: str, row: int, column: str) -> dict:
    return {
        "id": binding_id,
        "variable": variable,
        "row_index": row,
        "column": column,
        "source_unit": "vnd",
        "meaning": binding_id,
    }


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


lookup = {
    "bindings": [binding("revenue", "df1", 0, "2023")],
    "formula": "revenue",
    "output_unit": "million_vnd",
}
query = compile_plan(lookup, frames)
check("compiler owns unit conversion", run_query(query, frames) == 0.0001)

growth = {
    "bindings": [
        binding("old", "df1", 0, "2023"),
        binding("new", "df2", 0, "2024"),
    ],
    "formula": "(new - old) / old * 100",
    "output_unit": "percent",
}
check("growth compile + execute", run_query(compile_plan(growth, frames), frames) == 50.0)

nested = {
    "bindings": [
        binding("rank_2023", "df1", 0, "2023"),
        binding("rank_2024", "df2", 0, "2024"),
        binding("answer_2023", "df1", 1, "2023"),
        binding("answer_2024", "df2", 1, "2024"),
    ],
    "formula": (
        "select(argmax({'2023': rank_2023, '2024': rank_2024}), "
        "{'2023': answer_2023, '2024': answer_2024})"
    ),
    "output_unit": "vnd",
}
check("nested argmax/select", run_query(compile_plan(nested, frames), frames) == 45.0)

filtered = {
    "bindings": [
        binding("a", "df1", 1, "2023"),
        binding("b", "df2", 1, "2024"),
    ],
    "formula": "mean_where([a, b], [a > 30, b > 30])",
    "output_unit": "vnd",
}
check("filtered aggregation", run_query(compile_plan(filtered, frames), frames) == 45.0)

bad = {
    "bindings": [binding("x", "df1", 99, "missing")],
    "formula": "x",
    "output_unit": "vnd",
}
errors = validate_plan(bad, frames)
check("invalid row and column rejected", len(errors) == 2)

unused = {
    "bindings": [binding("x", "df1", 0, "2023"), binding("y", "df2", 0, "2024")],
    "formula": "x",
    "output_unit": "vnd",
}
check("unused binding rejected", any("không được formula dùng" in e for e in validate_plan(unused, frames)))
pruned, removed = prune_unused_bindings(unused)
check("unused planner scratch binding pruned", len(pruned["bindings"]) == 1 and len(removed) == 1)

raw = '<think>abc</think>\n```json\n{"bindings": [], "formula": "x"}\n```'
check("parse JSON after think/fence", parse_plan_response(raw) == {"bindings": [], "formula": "x"})

wrong_row = {
    "bindings": [binding("service_income", "df1", 0, "2023")],
    "formula": "service_income",
    "output_unit": "vnd",
}
label_frames = {
    "df1": pd.DataFrame(
        {"label": ["Thu nhập lãi thuần", "Lãi thuần từ hoạt động dịch vụ"], "2023": [10.0, 20.0]}
    )
}
alignment = binding_alignment_errors(
    "Lãi thuần từ hoạt động dịch vụ năm 2023 là bao nhiêu?", wrong_row, label_frames
)
check("semantic row mismatch flagged", len(alignment) == 1 and "row 1" in alignment[0])
repaired, changes = repair_binding_alignment(
    "Lãi thuần từ hoạt động dịch vụ năm 2023 là bao nhiêu?", wrong_row, label_frames
)
check(
    "unique stronger row auto-repaired",
    repaired["bindings"][0]["row_index"] == 1 and len(changes) == 1,
)

# A derived metric need not spell out every component in the question.  The
# binding meaning is therefore part of the semantic contract: a binding called
# "doanh thu thuần" must not silently point at an expense row.
derived_frames = {
    "df1": pd.DataFrame(
        {
            "label": [
                "Doanh thu thuần về bán hàng và cung cấp dịch vụ",
                "Chi phí quản lý doanh nghiệp",
                "Lợi nhuận sau thuế TNDN",
            ],
            "2016": [100.0, -30.0, 20.0],
        }
    )
}
wrong_derived = {
    "bindings": [
        {
            **binding("net_sales_2016", "df1", 1, "2016"),
            "meaning": "Doanh thu thuần năm 2016",
        }
    ],
    "formula": "net_sales_2016",
    "output_unit": "vnd",
}
repaired, changes = repair_binding_alignment(
    "Tỷ suất lợi nhuận ròng năm 2016 là bao nhiêu phần trăm?",
    wrong_derived,
    derived_frames,
)
check(
    "derived binding meaning repairs a mismatched row",
    repaired["bindings"][0]["row_index"] == 0 and len(changes) == 1,
)

# Currency scale conversion belongs to the compiler.  Accepting it in formula
# causes a second conversion when output_unit is compiled (the q820 failure).
double_conversion = {
    "bindings": [binding("revenue", "df1", 0, "2023")],
    "formula": "revenue / 1e9",
    "output_unit": "hundred_billion_vnd",
}
check(
    "formula-side currency conversion rejected",
    any("đổi đơn vị" in error for error in validate_plan(double_conversion, frames)),
)

unicode_binding = {
    "bindings": [binding("vốn_cổ_phần_2020", "df1", 0, "2023")],
    "formula": "vốn_cổ_phần_2020",
    "output_unit": "vnd",
}
check(
    "unicode snake_case binding id is valid",
    not validate_plan(unicode_binding, frames)
    and run_query(compile_plan(unicode_binding, frames), frames) == 100.0,
)

fake_dependency = {
    "bindings": [
        binding("rank_2023", "df1", 0, "2023"),
        binding("rank_2024", "df2", 0, "2024"),
        {
            **binding("quy_2024", "df2", 1, "2024"),
            "meaning": "Quỹ khen thưởng năm 2024",
        },
    ],
    "formula": (
        "select(argmax({'2023': rank_2023, '2024': rank_2024}), "
        "{'2023': quỹ_2024, '2024': quỹ_2024})"
    ),
    "output_unit": "vnd",
}
check(
    "repeated select branches are rejected",
    any("không thực sự phụ thuộc" in error for error in validate_plan(fake_dependency, frames)),
)
name_repaired, name_changes = repair_formula_binding_names(fake_dependency)
dependency_repaired, dependency_changes = repair_repeated_select_answers(name_repaired)
check(
    "diacritic-only binding alias is repaired",
    "quỹ_2024" not in dependency_repaired["formula"] and len(name_changes) == 2,
)
check(
    "repeated answer map becomes selected-year assertion",
    "'2023': quy_2024" not in dependency_repaired["formula"]
    and len(dependency_changes) == 1
    and not validate_plan(dependency_repaired, frames)
    and run_query(compile_plan(dependency_repaired, frames), frames) == 45.0,
)

partial_mismatch = {
    **fake_dependency,
    "formula": (
        "select(argmax({'2023': rank_2023, '2024': rank_2024}), "
        "{'2023': quy_2024, '2024': quy_2024 + 0})"
    ),
}
year_repaired, year_changes = repair_select_answer_years(partial_mismatch)
check(
    "select branch year must match answer binding year",
    year_repaired["formula"].count("'2023'") == 1
    and len(year_changes) == 1
    and not validate_plan(year_repaired, frames),
)

boolean_formula = {
    "bindings": [binding("x", "df1", 0, "2023")],
    "formula": "count_true([x > 0, true])",
    "output_unit": "count",
}
check("JSON-style boolean accepted", run_query(compile_plan(boolean_formula, frames), frames) == 2.0)

# load_frame joins hierarchical headers with ' | '; the model names the leaf, so a
# unique leaf must rebind to the flattened column -- otherwise the plan is rejected
# and falls back to unguarded direct code (the q818 unit failure).
piped = {
    "df1": pd.DataFrame(
        columns=[
            "label",
            "Số cuối năm | Tham chiếu",
            "Số cuối năm | Số đầu năm",
            "Số cuối năm | Số cuối năm",
            "Số đầu năm",
        ]
    ),
    "df2": pd.DataFrame(columns=["a | val", "b | val"]),
}
leaf_plan = {"bindings": [binding("x", "df1", 0, "Số cuối năm")]}
repaired, changes = repair_binding_column(leaf_plan, piped)
check(
    "a unique leaf rebinds to the flattened column",
    repaired["bindings"][0]["column"] == "Số cuối năm | Số cuối năm" and len(changes) == 1,
)
exact_plan = {"bindings": [binding("x", "df1", 0, "Số cuối năm | Số đầu năm")]}
_, exact_changes = repair_binding_column(exact_plan, piped)
check("an exact column is left untouched", exact_changes == [])
ambiguous_plan = {"bindings": [binding("x", "df2", 0, "val")]}
_, ambiguous_changes = repair_binding_column(ambiguous_plan, piped)
check("an ambiguous leaf is left to the repair loop", ambiguous_changes == [])

print("tất cả PASS")
