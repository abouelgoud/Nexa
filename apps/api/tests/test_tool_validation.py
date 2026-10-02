import uuid

import pytest
from pydantic import ValidationError

from nexa.schemas.tool_definition import ToolDefinition, builtin_tools
from nexa.tools.templating import expand_dotted, extract_mapped, render
from nexa.tools.validation import coerce_arguments, validate_arguments

BOOK = {
    "name": "book_appointment",
    "description": "Book an appointment",
    "category": "rest_api",
    "executor": "rest_api",
    "input_schema": {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}, "doctor_id": {"type": "string"},
                       "date": {"type": "string", "format": "date"}, "time": {"type": "string"}},
        "required": ["customer_id", "doctor_id", "date", "time"],
    },
    "requires_confirmation": True,
    "config": {"integration_id": str(uuid.uuid4()), "method": "POST", "path": "/appointments"},
}


def test_spec_tool_example_is_valid():
    td = ToolDefinition.model_validate(BOOK)
    assert td.requires_confirmation
    schema = td.llm_schema()
    assert schema["function"]["name"] == "book_appointment"
    # The LLM sees name/description/inputs only - never configuration or integration details
    assert "config" not in str(schema) and "integration_id" not in str(schema)


@pytest.mark.parametrize("patch,msg", [
    ({"name": "Bad Name"}, "name"),
    ({"input_schema": {"type": "string"}}, "object"),
    ({"input_schema": {"type": "object", "properties": {}, "required": ["x"]}}, "Required inputs"),
    ({"config": {"method": "POST"}}, "integration_id"),
    ({"executor": "shell"}, "executor"),
])
def test_invalid_tool_definitions(patch, msg):
    with pytest.raises(ValidationError, match=msg):
        ToolDefinition.model_validate({**BOOK, **patch})


def test_database_tool_rules():
    base = {"name": "delete_all", "description": "danger", "category": "database", "executor": "database",
            "config": {"integration_id": str(uuid.uuid4()), "operation": "delete_record", "table": "customers"}}
    with pytest.raises(ValidationError, match="must specify which record"):
        ToolDefinition.model_validate(base)
    with pytest.raises(ValidationError, match="Invalid identifier"):
        ToolDefinition.model_validate({**base, "config": {**base["config"], "table": "x; drop table y",
                                                          "filters": [{"field": "id", "arg": "id"}]}})


def test_argument_coercion_and_validation():
    schema = {"type": "object", "properties": {"slot_id": {"type": "integer"}, "date": {"type": "string", "format": "date"},
                                               "time": {"type": "string", "format": "time"}},
              "required": ["slot_id"], "additionalProperties": False}
    args = coerce_arguments(schema, {"slot_id": "١٢", "date": "2026-10-05", "time": "7 مساء"})
    assert args == {"slot_id": 12, "date": "2026-10-05", "time": "19:00"}
    assert validate_arguments(schema, args) == []
    assert "missing required information: slot_id" in validate_arguments(schema, {})[0]
    assert validate_arguments(schema, {"slot_id": "abc"})
    assert validate_arguments(schema, {"slot_id": 1, "evil": "x"})


def test_empty_values_treated_as_missing():
    schema = {"type": "object", "properties": {"doctor_id": {"type": "integer"}}}
    assert coerce_arguments(schema, {"doctor_id": ""}) == {}


def test_templating():
    v = {"slot": {"value": 5, "label": "الأحد"}, "slots": {"records": [{"label_ar": "أ", "label_en": "A"},
                                                                       {"label_ar": "ب", "label_en": "B"}]}}
    assert render("{{slot.value}}", v) == 5
    assert render("موعدك {{slot.label}}", v) == "موعدك الأحد"
    assert render("عندي {{slots.records|list:label}}", v, "ar") == "عندي أ وب"
    assert render("I have {{slots.records|list:label}}", v, "en") == "I have A or B"
    assert render("{{missing.path}}", v) is None
    assert render("{{x|default:none}}", v) == "none"


def test_body_and_response_mapping():
    assert expand_dotted({"customer.fullName": "Ali", "doctor.doctorId": 3}) == {
        "customer": {"fullName": "Ali"}, "doctor": {"doctorId": 3}}
    data = {"data": {"items": [{"id": 1, "time": "18:30"}, {"id": 2, "time": "19:00"}]}}
    assert extract_mapped(data, "data.items[].id") == [1, 2]
    assert extract_mapped(data, "data.items") == data["data"]["items"]


def test_builtins_are_valid():
    names = {b.name for b in builtin_tools()}
    assert {"transfer_call", "end_call", "search_knowledge"} <= names
