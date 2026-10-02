import uuid

from nexa.schemas.tool_definition import ToolDefinition
from nexa.tools.permissions import TablePermissions, check_database_tool

PERMS = {"tables": {"public.customers": {
    "operations": ["read", "update"],
    "fields": {"id": "read", "name": "read", "phone": "read", "email": "read_write", "password": "deny"}}}}


def tool(**config) -> ToolDefinition:
    base = {"integration_id": str(uuid.uuid4()), "operation": "search_records", "table": "customers"}
    return ToolDefinition.model_validate({
        "name": "find_customer", "description": "Find a customer", "category": "database", "executor": "database",
        "input_schema": {"type": "object", "properties": {"phone": {"type": "string"}, "email": {"type": "string"}}},
        "config": {**base, **config}})


def check(t: ToolDefinition) -> list[str]:
    return check_database_tool(t, t.typed_config(), PERMS)


def test_allowed_read():
    assert check(tool(return_fields=["id", "name", "phone"], filters=[{"field": "phone", "arg": "phone"}])) == []


def test_denied_field_cannot_be_returned():
    problems = check(tool(return_fields=["name", "password"]))
    assert any("password" in p for p in problems)


def test_denied_field_cannot_be_filtered():
    assert check(tool(filters=[{"field": "password", "arg": "phone"}]))


def test_unlisted_table_denied():
    assert check(tool(table="payments"))[0].startswith('The table "payments" is not shared')


def test_operation_permissions():
    assert any("create" in p for p in check(tool(operation="create_record", values={"name": "{{phone}}"})))
    assert check(tool(operation="update_record", values={"email": "{{email}}"},
                      filters=[{"field": "id", "value": 1}])) == []
    assert check(tool(operation="update_record", values={"name": "{{email}}"},
                      filters=[{"field": "id", "value": 1}]))  # name is read-only


def test_filter_argument_must_exist():
    assert any("not defined" in p for p in check(tool(filters=[{"field": "phone", "arg": "mobile"}])))


def test_readable_fields_default_excludes_denied():
    p = TablePermissions(PERMS, "public", "customers")
    assert "password" not in p.readable_fields()
    assert not p.readable("unknown_column")
