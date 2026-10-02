"""Table/field permissions for database integrations.

Integration config example::

    {"permissions": {"tables": {
        "public.patients": {
            "operations": ["read", "create"],
            "fields": {"id": "read", "full_name": "read_write", "phone": "read_write", "national_id": "deny"}
        }
    }}}

Anything not listed is denied. The LLM never writes SQL: it fills the inputs of a
pre-configured action, which this validator has approved field by field.
"""

from __future__ import annotations

from typing import Any

from nexa.schemas.tool_definition import DatabaseToolConfig, ToolDefinition

OPERATION_PERMISSION = {
    "get_record": "read",
    "search_records": "read",
    "create_record": "create",
    "update_record": "update",
    "delete_record": "delete",
}
READABLE = {"read", "read_write"}
WRITABLE = {"write", "read_write"}


class TablePermissions:
    def __init__(self, permissions: dict[str, Any], schema: str, table: str):
        tables = permissions.get("tables", {})
        self.rules = tables.get(f"{schema}.{table}") or (tables.get(table) if schema == "public" else None) or {}
        self.operations = set(self.rules.get("operations", []))
        self.fields: dict[str, str] = self.rules.get("fields", {})

    @property
    def exists(self) -> bool:
        return bool(self.rules)

    def can(self, op: str) -> bool:
        return op in self.operations

    def readable(self, field: str) -> bool:
        return self.fields.get(field, "deny") in READABLE

    def writable(self, field: str) -> bool:
        return self.fields.get(field, "deny") in WRITABLE

    def readable_fields(self) -> list[str]:
        return [f for f, p in self.fields.items() if p in READABLE]


def check_database_tool(defn: ToolDefinition, cfg: DatabaseToolConfig, permissions: dict[str, Any]) -> list[str]:
    """Return business-language problems (empty list means allowed)."""
    perms = TablePermissions(permissions, cfg.db_schema, cfg.table)
    label = defn.display_name or defn.name
    if not perms.exists:
        return [f'The table "{cfg.table}" is not shared with the AI agent. Allow it in the database permissions.']
    problems = []
    op = OPERATION_PERMISSION[cfg.operation]
    if not perms.can(op):
        problems.append(f'"{label}" needs permission to {op} records in "{cfg.table}".')
    for f in cfg.return_fields:
        if not perms.readable(f):
            problems.append(f'"{label}" returns "{f}", which the agent is not allowed to read.')
    if not cfg.return_fields and not perms.readable_fields():
        problems.append(f'No fields in "{cfg.table}" are readable by the agent.')
    for flt in cfg.filters:
        if not perms.readable(flt.field):
            problems.append(f'"{label}" searches by "{flt.field}", which the agent is not allowed to read.')
        if flt.arg and flt.arg not in defn.input_schema.get("properties", {}):
            problems.append(f'"{label}" uses the input "{flt.arg}" which is not defined.')
    for f in cfg.values:
        if not perms.writable(f):
            problems.append(f'"{label}" writes "{f}", which the agent is not allowed to change.')
    for o in cfg.order_by:
        if not perms.readable(o.lstrip("-")):
            problems.append(f'"{label}" sorts by "{o.lstrip("-")}", which the agent is not allowed to read.')
    return problems
