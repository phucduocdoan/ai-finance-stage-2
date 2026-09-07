"""Detect and canonicalize count-of-conditions queries.

Part of the `codegen.execute` facade: see `execute/__init__.py`.
"""
from __future__ import annotations

import ast


def _peel_count(node: ast.expr) -> ast.expr:
    """Strip the wrappers a counting query is habitually dressed in.

    `int(...)`, `abs(...)`, `round(...)`, `.sum()` and `.astype(int)` all leave
    the value's dimensionality alone, so the question of whether the expression
    underneath counts conditions or measures money is decided below them.

    `abs` earns its place here twice over: it is also what `apply_units` itself
    wraps a magnitude answer in, so a submitted query read back from a run file
    arrives already wearing it.
    """
    while True:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"int", "float", "bool", "abs", "round"} and node.args:
            node = node.args[0]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"sum", "astype", "item"}:
            node = node.func.value
        elif isinstance(node, ast.Attribute) and node.attr in {"values", "size"}:
            node = node.value
        else:
            return node


def _condition_leaves(node: ast.expr) -> list[ast.expr] | None:
    """The conditions summed by an addition tree, or None if it sums quantities.

    A comparison and a boolean operator both evaluate to a truth value, so an
    addition over nothing but those is a count: dimensionless by construction,
    not by guesswork about the Vietnamese phrasing. One quantity anywhere in the
    tree and this is money being added up instead, so the whole thing declines.
    """
    inner = _peel_count(node)
    if isinstance(inner, (ast.Compare, ast.BoolOp)):
        return [inner]
    if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.Add):
        left, right = _condition_leaves(inner.left), _condition_leaves(inner.right)
        if left is None or right is None:
            return None
        return left + right
    # `sum([int(c1), int(c2), ...])`, which is the shape the model reaches for
    # when it gets the count right on its own. Observed live on q435.
    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "sum" and len(inner.args) == 1:
        listed = inner.args[0]
        if isinstance(listed, (ast.List, ast.Tuple)):
            leaves = [_condition_leaves(el) for el in listed.elts]
            if listed.elts and all(leaf is not None for leaf in leaves):
                return [leaf for group in leaves for leaf in group]
    return None


def is_count_query(query: str) -> bool:
    """Does this query evaluate to a count of satisfied conditions?

    Used to keep `apply_units` off it. "Có bao nhiêu trong số các ngân hàng A, B,
    C có X trên 1000 triệu đồng" names a unit only inside the *threshold*, and
    `unit_from_hint` reads it off the question as if it were the answer's unit;
    the answer is a count of banks and has no unit at all. Measured on the
    submitted run: q563, q932, q949 and q983 all shipped a bare count multiplied
    by 1e-9 or 1e-12.

    Decided on the query rather than the question because the question is
    ambiguous and the query is not. q577 asks "doanh thu thuần thấp nhất là bao
    nhiêu", which does want a unit, and a question-side rule keyed on "bao nhiêu"
    would wrongly silence the conversion there.
    """
    try:
        root = ast.parse(query, mode="eval").body
    except SyntaxError:
        return False
    return _condition_leaves(root) is not None


def canonical_count(query: str) -> str | None:
    """Rewrite a count over named conditions as an explicit integer sum.

    numpy defines `+` on booleans as logical *or*, so the shape the model
    reaches for first, ``(c1) + (c2) + (c3)``, saturates at True instead of
    counting: three companies over the threshold and one company over it both
    answer 1, silently and without an error. `int(c1) + int(c2) + int(c3)`
    counts. Measured on the submitted run: q855 and q965 both shipped 1.0 from a
    saturated sum.

    Returns None for a count over a column (``(df1["x"] > 5).sum()``), where the
    conditions are rows rather than named operands: that shape counts correctly
    already, and `int()` cannot wrap a Series.
    """
    try:
        root = ast.parse(query, mode="eval").body
    except SyntaxError:
        return None
    leaves = _condition_leaves(root)
    if leaves is None or len(leaves) < 2:
        return None
    return " + ".join(f"int({ast.unparse(leaf)})" for leaf in leaves)
