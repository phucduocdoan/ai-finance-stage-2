"""Core intermediate representation: plan schema, unit system, compile_plan.

The LLM does two jobs only:
1. bind semantic quantities to concrete cells in the retrieved DataFrames;
2. express the calculation over symbolic binding names.

It never writes pandas. ``compile_plan`` validates every row/column coordinate
and compiles a deliberately small formula language to one pandas expression.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from finance_qa.core.paths import QUESTION_METADATA_PATH


# ---------------------------------------------------------------------------
# Unit system
# ---------------------------------------------------------------------------

SOURCE_UNITS = {
    "vnd", "million_vnd", "billion_vnd", "percent", "percentage_point",
    "count", "ratio", "year",
}

OUTPUT_UNITS = SOURCE_UNITS | {"hundred_billion_vnd", "trillion_vnd"}

SOURCE_MULTIPLIERS = {
    "vnd": 1.0, "million_vnd": 1e6, "billion_vnd": 1e9,
    "percent": 1.0, "percentage_point": 1.0, "count": 1.0, "ratio": 1.0, "year": 1.0,
}

OUTPUT_DIVISORS = {
    "vnd": 1.0, "million_vnd": 1e6, "billion_vnd": 1e9,
    "hundred_billion_vnd": 1e11, "trillion_vnd": 1e12,
    "percent": 1.0, "percentage_point": 1.0, "count": 1.0, "ratio": 1.0, "year": 1.0,
}

MONEY_UNITS = {"vnd", "million_vnd", "billion_vnd", "hundred_billion_vnd", "trillion_vnd"}
MONEY_SCALES = {1e6, 1e9, 1e11, 1e12}

# Maps detect_unit() hint → valid output_unit(s). Single source of truth for unit validation.
UNIT_HINT_MAP: dict[str, set[str]] = {
    "đồng": {"vnd"},
    "triệu": {"million_vnd"},
    "tỷ": {"billion_vnd"},
    "trăm tỷ": {"hundred_billion_vnd"},
    "nghìn tỷ": {"trillion_vnd"},
    "phần trăm": {"percent", "percentage_point"},
    "lần": {"ratio"},
    "count": {"count"},
}

# Whitelist of functions the formula language exposes.
_FUNCTIONS = {
    "abs", "sum", "mean", "median", "min", "max",
    "argmax", "argmin", "select",
    "mean_where", "sum_where", "min_where", "max_where",
    "argmax_where", "argmin_where",
    "count_true", "true", "false",
}


# ---------------------------------------------------------------------------
# Question metadata cache
# ---------------------------------------------------------------------------

_QUESTION_CONTEXTS: dict[str, dict] | None = None


def question_context(question: str) -> dict:
    """Return enriched metadata for a question, loaded once from disk."""
    global _QUESTION_CONTEXTS
    if _QUESTION_CONTEXTS is None:
        with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
            _QUESTION_CONTEXTS = {
                record["question"]: record
                for line in fh
                if (record := json.loads(line))
            }
    return _QUESTION_CONTEXTS.get(question, {})


# ---------------------------------------------------------------------------
# Structured plan schema
# ---------------------------------------------------------------------------

class PlanBinding(BaseModel):
    """One semantic quantity bound to a concrete DataFrame cell."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique snake_case binding name used by formula.")
    variable: str = Field(description="DataFrame variable name, e.g. df1.")
    row_index: int = Field(description="Zero-based pandas/DataFrame row index.")
    column: str = Field(description="Exact DataFrame column name.")
    source_unit: str = Field(description="Unit of the source cell before compiler conversion.")
    meaning: str = Field(default="", description="Short natural-language description of the binding.")


class OperationPlan(BaseModel):
    """Typed plan emitted by the planner LLM and executed by the compiler."""

    model_config = ConfigDict(extra="ignore")

    bindings: list[PlanBinding] = Field(default_factory=list)
    formula: str = Field(default="", description="Expression over binding ids in the restricted formula language.")
    output_unit: str = Field(default="", description="Requested answer unit.")
    explanation: str = Field(default="", description="Brief consistency check for the plan.")

    def to_plan_dict(self) -> dict[str, Any]:
        """Return the historical dict shape consumed by repairs/validators/compiler."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Legacy plan parsing
# ---------------------------------------------------------------------------

def parse_plan_response(raw: str) -> dict[str, Any] | None:
    """Find the first JSON object after an optional Qwen think block.

    Kept for diagnostic scripts that inspect raw model text. The production
    planner path uses ``OperationPlan`` structured output instead.
    """
    raw = raw.split("</think>")[-1].strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            value, _ = decoder.raw_decode(raw[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------

def _valid_binding_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isidentifier()
        and not value.startswith("_")
        and value == value.casefold()
        and all(char == "_" or char.isalnum() for char in value)
    )


def _formula_names(formula: str) -> set[str]:
    tree = ast.parse(formula, mode="eval")
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _numeric_constant(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _numeric_constant(node.operand)
        if value is not None:
            return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        base = _numeric_constant(node.left)
        exponent = _numeric_constant(node.right)
        if base is not None and exponent is not None:
            try:
                return base**exponent
            except (OverflowError, ZeroDivisionError):
                return None
    return None


def _formula_unit_conversion_errors(tree: ast.AST, output_unit: object) -> list[str]:
    if output_unit not in MONEY_UNITS:
        return []
    reciprocal_scales = {1 / scale for scale in MONEY_SCALES}
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        if isinstance(node.op, ast.Div):
            divisor = _numeric_constant(node.right)
            if divisor is not None and abs(divisor) in MONEY_SCALES:
                return ["formula tự đổi đơn vị tiền; compiler đã chuẩn hoá source_unit và output_unit"]
        if isinstance(node.op, ast.Mult):
            constants = {
                abs(value) for child in (node.left, node.right)
                if (value := _numeric_constant(child)) is not None
            }
            if constants & (MONEY_SCALES | reciprocal_scales):
                return ["formula tự đổi đơn vị tiền; compiler đã chuẩn hoá source_unit và output_unit"]
    return []


def _selection_dependency_errors(
    tree: ast.AST, bindings: dict[str, dict[str, Any]]
) -> list[str]:
    body = tree.body if isinstance(tree, ast.Expression) else tree
    if not (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "select"
        and len(body.args) == 2
        and isinstance(body.args[1], ast.Dict)
        and len(body.args[1].values) > 1
    ):
        return []
    values = {ast.dump(value, include_attributes=False) for value in body.args[1].values}
    errors = []
    if len(values) == 1:
        errors.append("select map lặp cùng một đáp án cho mọi key nên kết quả không thực sự phụ thuộc bước chọn")
    for key, value in zip(body.args[1].keys, body.args[1].values):
        if not isinstance(key, ast.Constant):
            continue
        key_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", str(key.value))}
        names = {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}
        claimed_years = {
            int(year) for name in names
            for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", f"{name} {bindings.get(name, {}).get('meaning', '')}")
        }
        if key_years and claimed_years and key_years.isdisjoint(claimed_years):
            errors.append(
                f"select key {key.value!r} dùng đáp án được binding gắn năm {sorted(claimed_years)}"
            )
    return errors


def validate_plan(plan: object, frames: dict[str, pd.DataFrame]) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan phải là JSON object"]
    bindings = plan.get("bindings")
    formula = plan.get("formula")
    output_unit = plan.get("output_unit")
    if not isinstance(bindings, list) or not bindings:
        errors.append("bindings phải là list không rỗng")
        bindings = []
    if not isinstance(formula, str) or not formula.strip():
        errors.append("formula phải là string không rỗng")
        formula = ""
    if output_unit not in OUTPUT_UNITS:
        errors.append(f"output_unit không hợp lệ: {output_unit!r}")

    ids: set[str] = set()
    for i, binding in enumerate(bindings):
        prefix = f"bindings[{i}]"
        if not isinstance(binding, dict):
            errors.append(f"{prefix} phải là object")
            continue
        binding_id = binding.get("id")
        variable = binding.get("variable")
        row = binding.get("row_index")
        column = binding.get("column")
        source_unit = binding.get("source_unit")
        if not _valid_binding_id(binding_id):
            errors.append(f"{prefix}.id không phải snake_case hợp lệ")
        elif binding_id in ids:
            errors.append(f"binding id bị trùng: {binding_id}")
        else:
            ids.add(binding_id)
        if variable not in frames:
            errors.append(f"{prefix}.variable không tồn tại: {variable!r}")
            continue
        df = frames[variable]
        if not isinstance(row, int) or isinstance(row, bool) or not 0 <= row < len(df):
            errors.append(f"{prefix}.row_index ngoài phạm vi 0..{len(df) - 1}: {row!r}")
        if not isinstance(column, str) or column not in df.columns:
            errors.append(f"{prefix}.column không tồn tại trong {variable}: {column!r}")
        elif isinstance(row, int) and not isinstance(row, bool) and 0 <= row < len(df):
            value = df.iloc[row][column]
            if not pd.api.types.is_number(value) or pd.isna(value):
                errors.append(
                    f"{prefix} trỏ tới ô không phải số: "
                    f"{variable}.iloc[{row}][{column!r}]={value!r}"
                )
        if source_unit not in SOURCE_UNITS:
            errors.append(f"{prefix}.source_unit không hợp lệ: {source_unit!r}")
        elif (
            isinstance(column, str)
            and "triệu" in column.casefold()
            and source_unit != "million_vnd"
        ):
            errors.append(
                f"{prefix}.column ghi Triệu nhưng source_unit={source_unit!r}, phải là 'million_vnd'"
            )

    # Detect self-subtraction: two bindings pointing to the same (variable, row, column).
    # This always produces X - X = 0 and is never intentional.
    slots: dict[tuple, str] = {}
    for b in bindings:
        if not isinstance(b, dict):
            continue
        slot = (b.get("variable"), b.get("row_index"), b.get("column"))
        if None not in slot:
            if slot in slots:
                errors.append(
                    f"binding {b.get('id')!r} và {slots[slot]!r} trỏ cùng ô "
                    f"{slot[0]}.iloc[{slot[1]}][{slot[2]!r}] — tự trừ"
                )
            else:
                slots[slot] = b.get("id", "")

    if formula:
        try:
            tree = ast.parse(formula, mode="eval")
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        except SyntaxError as exc:
            errors.append(f"formula sai cú pháp: {exc.msg}")
        else:
            unknown = names - ids - _FUNCTIONS
            if unknown:
                errors.append("formula dùng tên không khai báo: " + ", ".join(sorted(unknown)))
            used = names & ids
            if not used:
                errors.append("formula không dùng binding nào")
            unused = ids - used
            if unused:
                errors.append("bindings không được formula dùng: " + ", ".join(sorted(unused)))
            errors.extend(_formula_unit_conversion_errors(tree, output_unit))
            errors.extend(_selection_dependency_errors(
                tree, {b["id"]: b for b in bindings if isinstance(b.get("id"), str)}
            ))
    return errors


# ---------------------------------------------------------------------------
# Compiler: symbolic formula → pandas expression
# ---------------------------------------------------------------------------

class _Compiler:
    """Compile the small symbolic formula language; reject every other AST node."""

    def __init__(self, bindings: dict[str, dict[str, Any]]):
        self.bindings = bindings

    def compile(self, node: ast.AST) -> str:
        method = getattr(self, f"c_{type(node).__name__}", None)
        if method is None:
            raise ValueError(f"formula không cho phép {type(node).__name__}")
        return method(node)

    def c_Expression(self, node: ast.Expression) -> str:
        return self.compile(node.body)

    def c_Name(self, node: ast.Name) -> str:
        if node.id == "true":
            return "True"
        if node.id == "false":
            return "False"
        if node.id not in self.bindings:
            raise ValueError(f"tên không phải binding: {node.id}")
        binding = self.bindings[node.id]
        cell = f"{binding['variable']}.iloc[{binding['row_index']}][{binding['column']!r}]"
        multiplier = SOURCE_MULTIPLIERS[binding["source_unit"]]
        return cell if multiplier == 1 else f"({cell} * {multiplier!r})"

    def c_Constant(self, node: ast.Constant) -> str:
        if not isinstance(node.value, (str, int, float, bool)):
            raise ValueError(f"hằng số không được phép: {node.value!r}")
        return repr(node.value)

    def c_List(self, node: ast.List) -> str:
        return "[" + ", ".join(self.compile(x) for x in node.elts) + "]"

    def c_Tuple(self, node: ast.Tuple) -> str:
        return "[" + ", ".join(self.compile(x) for x in node.elts) + "]"

    def c_Dict(self, node: ast.Dict) -> str:
        pairs = [
            f"{self.compile(key)}: {self.compile(value)}"
            for key, value in zip(node.keys, node.values)
            if key is not None
        ]
        if len(pairs) != len(node.values):
            raise ValueError("dict unpack không được phép")
        return "{" + ", ".join(pairs) + "}"

    _BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**", ast.Mod: "%"}

    def c_BinOp(self, node: ast.BinOp) -> str:
        symbol = self._BINOPS.get(type(node.op))
        if symbol is None:
            raise ValueError(f"toán tử không được phép: {type(node.op).__name__}")
        return f"({self.compile(node.left)} {symbol} {self.compile(node.right)})"

    def c_UnaryOp(self, node: ast.UnaryOp) -> str:
        symbols = {ast.UAdd: "+", ast.USub: "-", ast.Not: "not "}
        symbol = symbols.get(type(node.op))
        if symbol is None:
            raise ValueError(f"toán tử một ngôi không được phép: {type(node.op).__name__}")
        return f"({symbol}{self.compile(node.operand)})"

    def c_BoolOp(self, node: ast.BoolOp) -> str:
        symbol = " and " if isinstance(node.op, ast.And) else " or "
        return "(" + symbol.join(self.compile(x) for x in node.values) + ")"

    _CMPOPS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}

    def c_Compare(self, node: ast.Compare) -> str:
        parts = [self.compile(node.left)]
        for op, comparator in zip(node.ops, node.comparators):
            symbol = self._CMPOPS.get(type(op))
            if symbol is None:
                raise ValueError(f"so sánh không được phép: {type(op).__name__}")
            parts.extend((symbol, self.compile(comparator)))
        return "(" + " ".join(parts) + ")"

    @staticmethod
    def _series(value: str, dtype: str = "float") -> str:
        return f"pd.Series({value}, dtype={dtype!r})"

    def c_Call(self, node: ast.Call) -> str:
        if node.keywords or not isinstance(node.func, ast.Name):
            raise ValueError("chỉ cho phép gọi hàm tên đơn giản, không có keyword")
        name = node.func.id
        args = [self.compile(arg) for arg in node.args]
        if name == "abs" and len(args) == 1:
            return f"abs({args[0]})"
        if name in {"sum", "mean", "median", "min", "max"} and len(args) == 1:
            method = {"min": "min", "max": "max"}.get(name, name)
            return f"{self._series(args[0])}.{method}()"
        if name in {"argmax", "argmin"} and len(args) == 1:
            method = "idxmax" if name == "argmax" else "idxmin"
            return f"{self._series(args[0])}.{method}()"
        if name == "select" and len(args) == 2:
            return f"{self._series(args[1])}.loc[{args[0]}]"
        if name == "count_true" and len(args) == 1:
            return f"{self._series(args[0], 'bool')}.sum()"
        if name in {"mean_where", "sum_where", "min_where", "max_where"} and len(args) == 2:
            method = name.removesuffix("_where")
            return f"{self._series(args[0])}[{self._series(args[1], 'bool')}].{method}()"
        if name in {"argmax_where", "argmin_where"} and len(args) == 2:
            method = "idxmax" if name == "argmax_where" else "idxmin"
            return f"{self._series(args[0])}[{self._series(args[1], 'bool')}].{method}()"
        raise ValueError(f"hàm hoặc số đối số không hợp lệ: {name}/{len(args)}")


def compile_plan(plan: dict[str, Any], frames: dict[str, pd.DataFrame]) -> str:
    errors = validate_plan(plan, frames)
    if errors:
        raise ValueError("; ".join(errors))
    bindings = {binding["id"]: binding for binding in plan["bindings"]}
    tree = ast.parse(plan["formula"], mode="eval")
    expression = _Compiler(bindings).compile(tree)
    divisor = OUTPUT_DIVISORS[plan["output_unit"]]
    return expression if divisor == 1 else f"({expression} / {divisor!r})"
