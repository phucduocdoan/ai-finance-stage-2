"""Deterministic unit detection and conversion for evidence tables.

This is the module that exists because of a measured failure. Question 45 asks
for BAB's total liabilities "bao nhiêu triệu đồng"; the gold cell reads
`108.950.874` in a table whose first data row is literally
``["Triệu VND", "Triệu VND", NaN, NaN, NaN]`` — the unit is declared *inside the
grid*, not in a column name. The old planner emitted
``df1.iloc[12]['31/12/2020'] / 1000000.0`` (answer 108.950874 instead of
108,950,874) and reported ``errors=[]``, because its validator only checked
whether the *column name* contained "triệu". Over a 500-table random sample,
24.2% of tables declare their unit only in grid cells, so that blind spot is not
an edge case.

Two rules follow from that, and they are the whole design:

1. Detection is deterministic and reads the grid, not just the header. The LLM's
   own `source_unit` is only a fallback for tables that declare nothing.
2. The LLM never writes the scaling arithmetic. It extracts the cell as printed;
   `scale_expression` appends the factor derived from (detected source unit,
   unit the question asked for). A model that cannot multiply cannot be wrong
   about multiplying.
"""
from __future__ import annotations

import re

import pandas as pd

# Measured on the 27 gold rows whose true source scale is derivable from
# (raw cell, gold answer, gold unit): detection is right 14/15 when the table
# declares anything, and when it declares nothing the cell is raw VND in 9 of 12
# cases. The model's own `source_unit` was wrong in 4 of the 4 failures inspected
# — it reports the *magnitude of the number* ("4.26 nghìn tỷ") rather than the
# unit the table prints in. Hence: money scale is never taken from the model.

# Canonical unit vocabulary. Money units carry a scale to VND; the rest are
# scale-free and exist so a plan can say "this is a percent, do not touch it".
MONEY_SCALE: dict[str, float] = {
    "vnd": 1.0,
    "thousand_vnd": 1e3,
    "million_vnd": 1e6,
    "billion_vnd": 1e9,
    "hundred_billion_vnd": 1e11,
    "trillion_vnd": 1e12,
}
SCALE_FREE_UNITS = frozenset({"percent", "ratio", "count", "share", "year", "unknown"})
UNITS = frozenset(MONEY_SCALE) | SCALE_FREE_UNITS

# Order matters: "nghìn tỷ đồng" must win over "tỷ đồng", which must win over the
# bare-VND pattern. Every money pattern requires a currency word after the
# magnitude word, because a bare `tỷ` matches "tỷ lệ" (= ratio) — that mistake
# inflated an earlier measurement of billion-unit tables from 0.2% to 19.0%.
#
# Thousand has two spellings and only one of them was here. HAG and HNG print
# every statement with a column named "Ngàn VND Số đầu năm"; `ngh[ìi]n` misses
# "ngàn", the bare-VND pattern below then claims the column, and the table is
# read as raw VND. qid139 asks HAG's 2020 net revenue in nghìn đồng and gold is
# 3.176.645.956 against a submitted 3.176.645,956 — exactly 1000x, from this one
# missing alternative. The OCR also sometimes renders the same banner as
# "Ngân VND", which must be treated as the same scale when followed by a currency
# word. 1,832 tables in the corpus declare "ngàn <currency>" and nothing else,
# across 50 reports, all of them HAG (1,070), HNG (754) or SNZ (8).
_THOUSAND = r"(?:ngh[ìi]n|ng[àaâ]n)"
_MONEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("trillion_vnd", re.compile(rf"{_THOUSAND}\s*t[ỷy]\s*(?:đ[ồô]ng|vnd|vnđ)", re.I)),
    ("hundred_billion_vnd", re.compile(r"tr[ăa]m\s*t[ỷy]\s*(?:đ[ồô]ng|vnd|vnđ)", re.I)),
    ("billion_vnd", re.compile(r"t[ỷy]\s*(?:đ[ồô]ng|vnd|vnđ)", re.I)),
    ("million_vnd", re.compile(r"tri[ệê]u\s*(?:đ[ồô]ng|vnd|vnđ)", re.I)),
    ("thousand_vnd", re.compile(rf"{_THOUSAND}\s*(?:đ[ồô]ng|vnd|vnđ)", re.I)),
    ("vnd", re.compile(r"(?:^|[^\w])(?:vnd|vnđ|đ[ồô]ng)(?:[^\w]|$)", re.I)),
)

# How many leading rows can carry a unit banner. Measured on the 500-table
# sample: a declaration that appears in the grid at all appears within the first
# four rows in 100% of cases.
_BANNER_ROWS = 4

# Units that name a magnitude. A bare "VND" found in a *data cell* is weak
# evidence: bank notes routinely label rows "- Bằng VND" (= denominated in VND),
# and reading one as a table banner cost qid280 its answer — that table's own
# column names say "31.12.2022Triệu đồng". A magnitude word in a cell, by
# contrast, is a unit banner essentially every time.
_STRONG = frozenset(MONEY_SCALE) - {"vnd"}

# "Đơn vị tính: Triệu đồng Việt Nam" printed above the table, kept in metadata as
# `context_page_text`. This is the only signal for the tables whose banner row was
# lost in extraction — 3 of the 12 undeclared gold tables, all bank statements
# printed in millions. Gated to an explicit "đơn vị" declaration so that a page
# merely *mentioning* "triệu" cannot rescale a table.
_UNIT_DECLARATION = re.compile(r"đ[ơo]n\s*v[ịi][^\n]{0,40}", re.I)


def unit_in_text(text: str) -> str | None:
    """The money unit declared by ``text``, or None."""
    if not text:
        return None
    for unit, pattern in _MONEY_PATTERNS:
        if pattern.search(text):
            return unit
    return None


_PERCENT = re.compile(r"%|ph[ầâ]n\s*tr[ăa]m", re.I)
_RATIO = re.compile(r"\bl[ầâ]n\b|\bt[ỷy]\s*l[ệê]\b", re.I)


def unit_from_hint(text: str) -> str | None:
    """Canonical unit requested by question text (or by ``unit_hint``).

    Money first: "bao nhiêu triệu đồng" is the whole reason this module exists.
    Percent and ratio only matter as a signal to leave the value alone, which
    `conversion_factor` already does for anything scale-free.
    """
    if not text:
        return None
    money = unit_in_text(text)
    if money:
        return money
    if _PERCENT.search(text):
        return "percent"
    if _RATIO.search(text):
        return "ratio"
    return None


def detect_column_unit(df: pd.DataFrame, column: str) -> tuple[str | None, str]:
    """Unit declared by one column: its name first, then its banner cells.

    Per-column beats table-level because a single table can mix scales — a note
    stating "Đơn vị: triệu đồng" above a column of raw-VND share prices, for
    instance. Falling back to the table banner is `detect_table_unit`'s job.
    """
    if column in df.columns:
        unit = unit_in_text(str(column))
        if unit:
            return unit, f"column name {column!r}"
        series = df[column].head(_BANNER_ROWS)
        for i, cell in enumerate(series):
            unit = unit_in_text(str(cell)) if isinstance(cell, str) else None
            if unit:
                return unit, f"{column!r} row {i}"
    return None, ""


def unit_in_declaration(page_text: str) -> tuple[str | None, str]:
    """Unit from an "Đơn vị tính: ..." declaration in the page text around a table."""
    for match in _UNIT_DECLARATION.finditer(page_text or ""):
        unit = unit_in_text(match.group(0))
        if unit:
            return unit, f"page text {match.group(0).strip()[:48]!r}"
    return None, ""


# A scale banner with no "Đơn vị tính:" in front of it. HAG's and HNG's auditor
# prints the scale as a bare run in the page header — "... kết thúc ngày 31 tháng
# 12 năm 2019 Ngàn VND Nguyễn Văn Tiên ..." — so `unit_in_declaration` never sees
# it and the table falls through to the raw-VND default. qid919 averages three
# payables balances and two of them come from pages like that; gold is 720.218,69
# triệu đồng against a submitted 54.263,14, because the two ngàn-VND terms were
# added to a VND term as if all three matched.
#
# Thousand only, and that restriction is measured rather than cautious. Extending
# the same rule to `triệu` and `tỷ` fires on 40 tables in the referenced set and is
# wrong on all 40, because those scales appear in note prose that this gate cannot
# tell from a banner: SCR's page says "nắm giữ tỷ lệ ... VND" and OGC's says
# "... nghìn tỷ đồng", which would rescale a raw-VND table by 1e9 and 1e12. The
# thousand scale is the one with no other route in: `triệu` and `tỷ` tables
# overwhelmingly print an "Đơn vị tính:" line or a grid banner, and HAG/HNG print
# neither.
#
# Gated on the preceding token: a magnitude word after an *amount* is prose about
# one figure, not a declaration about the table. A bare four-digit year does not
# disqualify it, because the banner sits at the end of a statement title and that
# title ends in a date: HAG's is "... cho năm tài chính kết thúc ngày 31 tháng 12
# năm 2019 Ngàn VND". A formatted amount always carries a group separator, which
# is what tells the two apart.
_PAGE_BANNER = re.compile(rf"(\S+[ \t]+)?({_THOUSAND}[ \t]*(?:đ[ồô]ng|vnd|vnđ))", re.I)
_AMOUNT_PREFIX = re.compile(r"(?<!\d)\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\s*$|\d[\d.,]*[.,]\d+\s*$")


def unit_in_page_banner(page_text: str) -> tuple[str | None, str]:
    """Unit from a bare scale banner in the page text, skipping prose amounts."""
    for match in _PAGE_BANNER.finditer(page_text or ""):
        if _AMOUNT_PREFIX.search(match.group(1) or ""):
            continue
        unit = unit_in_text(match.group(0))
        if unit:
            return unit, f"page banner {match.group(2).strip()[:32]!r}"
    return None, ""


def detect_table_unit(df: pd.DataFrame, page_text: str = "") -> tuple[str | None, str]:
    """Unit declared anywhere in the table's banner rows, header, or page text.

    Returns ``(unit, where)``; ``where`` is a human-readable provenance string
    that goes into the run diagnostics, so a wrong scale is traceable to the cell
    that caused it rather than being guessed at after the fact.

    Banner rows are checked before column names because a banner ("Đơn vị: triệu
    đồng") is a statement about the whole table, whereas a unit inside a column
    name is a statement about *that* column — and reading it as table-wide gets
    the neighbouring columns wrong when a table mixes scales. But only a *strong*
    banner cell wins that way; a bare "VND" in a cell is held back as a last
    resort, because it is far more often a row label than a declaration.
    """
    weak: tuple[str, str] | None = None
    for i in range(min(_BANNER_ROWS, len(df))):
        for column in df.columns:
            cell = df.iloc[i][column]
            unit = unit_in_text(str(cell)) if isinstance(cell, str) else None
            if unit in _STRONG:
                return unit, f"row {i}, column {column!r}"
            if unit and weak is None:
                weak = (unit, f"row {i}, column {column!r}")
    for column in df.columns:
        unit = unit_in_text(str(column))
        if unit:
            return unit, f"column name {column!r}"
    unit, where = unit_in_declaration(page_text)
    if unit:
        return unit, where
    if weak:
        return weak
    return unit_in_page_banner(page_text)


def detect_unit(
    df: pd.DataFrame, column: str | None, page_text: str = ""
) -> tuple[str | None, str]:
    """Declared unit for the cell the plan targets: column-level, then table-level."""
    if column:
        unit, where = detect_column_unit(df, column)
        if unit:
            return unit, where
    return detect_table_unit(df, page_text)


def resolve_source_unit(detected: str | None, model_unit: str | None) -> tuple[str, str]:
    """The unit a value is printed in, and where that came from.

    The model is trusted for exactly one thing here: saying that a value is *not*
    money. It has no reliable read on money scale — asked what unit
    ``4.263.610.960.357`` is printed in it answers "trillion_vnd", describing the
    number's magnitude rather than the table, and `conversion_factor` then finds
    nothing to convert. So when the deterministic layer finds no declaration the
    fallback is raw VND, which is what 9 of 12 undeclared gold tables print.
    """
    if detected:
        return detected, ""
    if model_unit in SCALE_FREE_UNITS and model_unit != "unknown":
        return model_unit, f"model ({model_unit} is scale-free)"
    return "vnd", "mặc định vnd (bảng không khai đơn vị)"


def conversion_factor(source_unit: str, target_unit: str) -> float:
    """Multiplier taking a value from ``source_unit`` to ``target_unit``.

    1.0 whenever either side is scale-free: a percent asked for as a percent, or
    a money cell whose target the question never stated, must pass through
    untouched. Silently rescaling those is how "0" answers were produced.
    """
    if source_unit == target_unit:
        return 1.0
    if source_unit in MONEY_SCALE and target_unit in MONEY_SCALE:
        return MONEY_SCALE[source_unit] / MONEY_SCALE[target_unit]
    return 1.0


def _factor_literal(factor: float) -> str:
    """Render a factor as an exact Python literal.

    Powers of ten go out as ``1e6`` rather than ``1000000.0``; the query is
    submitted verbatim and re-run by the grader, so the text matters.
    """
    if factor >= 1.0 and float(factor).is_integer():
        exponent = len(str(int(factor))) - 1
        if factor == 10.0**exponent:
            return f"1e{exponent}" if exponent else "1"
    inverse = 1.0 / factor
    if inverse >= 1.0 and float(inverse).is_integer():
        exponent = len(str(int(inverse))) - 1
        if inverse == 10.0**exponent:
            return f"1e-{exponent}" if exponent else "1"
    return repr(factor)


# Powers of ten a model would only ever write for a unit conversion. 100 is
# excluded deliberately: turning a ratio into a percent is `* 100` and *is* the
# model's job, because `conversion_factor` leaves scale-free units alone.
_STRIP_FACTORS = {10.0**k for k in range(3, 16)} | {10.0**-k for k in range(3, 16)}
_TRAILING_FACTOR = re.compile(r"\s*([*/])\s*([\d_]+(?:\.\d+)?|1[eE][-+]?\d+)\s*$")


def strip_scale_factor(query: str) -> tuple[str, list[str]]:
    """Remove trailing unit arithmetic the model wrote itself.

    The prompt tells the model to read the cell as printed and let code convert.
    It disobeys: five of the measured failures carried the model's own factor
    (``df1.iloc[0, 1] / 1e11``, ``df1.iloc[0, 3] * 1000``) and `scale_expression`
    then applied a second conversion, landing 1e15 or 1e-10 away from gold. Only a
    trailing literal power of ten is removed, so a genuine ratio ``a / b``, a
    percent ``* 100``, and anything inside parentheses are all left alone; the
    result is re-compiled and the strip reverted if it did not parse.
    """
    out, removed = query.strip(), []
    while (match := _TRAILING_FACTOR.search(out)) is not None:
        try:
            value = float(match.group(2).replace("_", ""))
        except ValueError:
            break
        if value not in _STRIP_FACTORS:
            break
        candidate = out[: match.start()].strip()
        try:
            compile(candidate, "<query>", "eval")
        except SyntaxError:
            break
        removed.append(match.group(0).strip())
        out = candidate
    return out, removed


def scale_expression(query: str, source_unit: str, target_unit: str) -> str:
    """Wrap a raw-cell query with the deterministic unit conversion.

    The returned string *is* the submitted ``pandas_query``, so the conversion is
    visible to the grader and re-executes to the same answer.
    """
    factor = conversion_factor(source_unit, target_unit)
    if factor == 1.0:
        return query
    return f"({query}) * {_factor_literal(factor)}"


__all__ = [
    "MONEY_SCALE",
    "SCALE_FREE_UNITS",
    "UNITS",
    "conversion_factor",
    "detect_column_unit",
    "detect_table_unit",
    "detect_unit",
    "resolve_source_unit",
    "scale_expression",
    "strip_scale_factor",
    "unit_from_hint",
    "unit_in_declaration",
    "unit_in_page_banner",
    "unit_in_text",
]
