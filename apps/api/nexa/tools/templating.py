"""Tiny, safe templating for tool configuration and workflow texts.

``{{path.to.value}}`` reads from a variables dict. A template that is exactly one
expression returns the raw value (keeps integers/lists). Supported filters:
``|list:field`` (join records naturally in the conversation language) and
``|default:text``. No code execution is possible.
"""

from __future__ import annotations

import re
from typing import Any

EXPR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_MISSING = object()


def resolve_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part, _MISSING)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else _MISSING
        else:
            return None
        if cur is _MISSING:
            return None
    return cur


def localized(record: Any, field: str, language: str) -> Any:
    if not isinstance(record, dict):
        return record
    for key in (f"{field}_{language}", field, f"{field}_ar", f"{field}_en"):
        if record.get(key) not in (None, ""):
            return record[key]
    return None


def join_natural(items: list[str], language: str) -> str:
    items = [str(i) for i in items if i not in (None, "")]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if language == "ar":
        return "، ".join(items[:-1]) + " و" + items[-1]
    return ", ".join(items[:-1]) + " or " + items[-1]


def _eval(expr: str, variables: dict[str, Any], language: str) -> Any:
    parts = [p.strip() for p in expr.split("|")]
    value = resolve_path(variables, parts[0])
    for flt in parts[1:]:
        name, _, arg = flt.partition(":")
        if name == "list":
            records = value if isinstance(value, list) else []
            value = join_natural([localized(r, arg, language) if arg else r for r in records], language)
        elif name == "default":
            value = value if value not in (None, "", []) else arg
        elif name == "count":
            value = len(value) if isinstance(value, list) else 0
    return value


def render(template: Any, variables: dict[str, Any], language: str = "ar") -> Any:
    if isinstance(template, dict):
        return {k: render(v, variables, language) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, variables, language) for v in template]
    if not isinstance(template, str):
        return template
    m = EXPR_RE.fullmatch(template.strip())
    if m:
        return _eval(m.group(1), variables, language)

    def repl(match: re.Match) -> str:
        v = _eval(match.group(1), variables, language)
        if isinstance(v, dict):
            v = localized(v, "label", language) or ""
        return "" if v is None else str(v)

    return re.sub(r"\s{2,}", " ", EXPR_RE.sub(repl, template)).strip()


def expand_dotted(data: dict[str, Any]) -> dict[str, Any]:
    """{"customer.fullName": x} -> {"customer": {"fullName": x}} (for API body mapping)."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            value = expand_dotted(value)
        cur = out
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    return out


def extract_mapped(data: Any, path: str) -> Any:
    """Read ``a.b[].c`` style paths from an API response."""
    if not path:
        return data
    head, _, rest = path.partition(".")
    if head.endswith("[]"):
        key = head[:-2]
        items = resolve_path(data, key) if key else data
        if not isinstance(items, list):
            return []
        return [extract_mapped(i, rest) for i in items] if rest else items
    value = resolve_path(data, head)
    return extract_mapped(value, rest) if rest else value


def drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, "")}
