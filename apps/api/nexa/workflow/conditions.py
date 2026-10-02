"""Safe condition expressions for workflow branches.

Grammar (Python-like, evaluated over an AST whitelist - no calls except the
helpers below, no attribute access on objects, no imports):

    intent == "book" and not empty(slots.records)
    count(slots.records) > 2 or patient.record.id != null
"""

from __future__ import annotations

import ast
from typing import Any

from nexa.tools.templating import resolve_path


class ConditionError(ValueError):
    pass


_FUNCS = {
    "empty": lambda v: v in (None, "", [], {}),
    "count": lambda v: len(v) if isinstance(v, (list, dict, str)) else 0,
    "lower": lambda v: str(v).lower() if v is not None else "",
}
_NAMES = {"true": True, "false": False, "null": None, "none": None, "True": True, "False": False, "None": None}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def evaluate(expr: str, variables: dict[str, Any]) -> bool:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"Invalid condition: {expr}") from exc
    return bool(_eval(tree.body, variables))


def _eval(node: ast.AST, v: dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        vals = (_eval(x, v) for x in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, v)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, v)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, v)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, v)
            try:
                ok = {
                    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
                    ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
                    ast.In: lambda a, b: a in (b or []), ast.NotIn: lambda a, b: a not in (b or []),
                }[type(op)](left, right)
            except KeyError as exc:
                raise ConditionError("Unsupported comparison") from exc
            except TypeError:
                ok = False
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, ast.List):
        return [_eval(e, v) for e in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
        return _FUNCS[node.func.id](_eval(node.args[0], v))
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    path = _dotted(node)
    if path is not None:
        if any(part.startswith("_") for part in path.split(".")):
            raise ConditionError("Names starting with '_' are not allowed")
        return resolve_path(v, path)
    raise ConditionError("Unsupported expression")
