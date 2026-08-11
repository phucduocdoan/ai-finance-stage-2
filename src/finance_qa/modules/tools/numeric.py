"""Numeric parsing helpers."""
from __future__ import annotations

import re

_NUM_CHARS = re.compile(r"^[\d.,]+$")

# A lone dash is the accounting convention for nil.
NIL_MARKS = {"-", "–", "—", "nan"}


def parse_number(text: str) -> float | None:
    """Parse Vietnamese/English formatted accounting numbers."""
    value = text.strip()
    if not value:
        return None
    neg = False
    if value.startswith("(") and value.endswith(")"):
        neg, value = True, value[1:-1].strip()
    if value[:1] in "-+":
        neg, value = neg or value[0] == "-", value[1:].strip()
    if not value or not _NUM_CHARS.fullmatch(value) or not any(c.isdigit() for c in value):
        return None

    has_dot, has_comma = "." in value, "," in value
    if has_dot and has_comma:
        decimal = "." if value.rfind(".") > value.rfind(",") else ","
        value = value.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        grouped = re.fullmatch(rf"\d{{1,3}}(\{sep}\d{{3}})+", value) is not None
        value = value.replace(sep, "") if grouped else value.replace(sep, ".")

    try:
        parsed = float(value)
    except ValueError:
        return None
    return -parsed if neg else parsed


__all__ = ["NIL_MARKS", "parse_number"]
