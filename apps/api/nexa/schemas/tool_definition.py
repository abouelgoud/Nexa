"""Declarative tool definitions.

The LLM (or the workflow engine) may *request* a tool by name with arguments.
The backend validates the request against ``input_schema``, checks
permissions/confirmation policy and executes it - the model never executes
anything itself and never sees credentials.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOOL_NAME_RE = r"^[a-z][a-z0-9_]{1,63}$"
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class ToolCategory(StrEnum):
    database = "database"
    rest_api = "rest_api"
    calendar = "calendar"
    crm = "crm"
    sms = "sms"
    email = "email"
    whatsapp = "whatsapp"
    voice = "voice"
    workflow = "workflow"
    human_handoff = "human_handoff"
    knowledge = "knowledge"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# --- Database -----------------------------------------------------------------

DbOperation = Literal["get_record", "search_records", "create_record", "update_record", "delete_record"]
FilterOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "like", "ilike", "in", "is_null", "not_null"]


class DbFilter(Strict):
    field: str
    op: FilterOp = "eq"
    # Either an input argument name, or a constant value.
    arg: str | None = None
    value: Any = None
    # When the argument is missing the filter is skipped (e.g. optional doctor).
    optional: bool = False

    @field_validator("field")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT_RE.match(v):
            raise ValueError(f"Invalid field name: {v}")
        return v


class DatabaseToolConfig(Strict):
    integration_id: UUID
    operation: DbOperation
    db_schema: str = "public"
    table: str
    filters: list[DbFilter] = Field(default_factory=list)
    return_fields: list[str] = Field(default_factory=list)
    # column -> "{{argument}}" template or constant
    values: dict[str, Any] = Field(default_factory=dict)
    order_by: list[str] = Field(default_factory=list)  # "field" or "-field"
    limit: int = Field(10, ge=1, le=100)

    @field_validator("table", "db_schema")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT_RE.match(v):
            raise ValueError(f"Invalid identifier: {v}")
        return v

    @model_validator(mode="after")
    def _check(self) -> DatabaseToolConfig:
        for f in [*self.return_fields, *self.values.keys(), *(o.lstrip("-") for o in self.order_by)]:
            if not IDENT_RE.match(f):
                raise ValueError(f"Invalid field name: {f}")
        if self.operation in ("update_record", "delete_record") and not self.filters:
            raise ValueError("Update and delete actions must specify which record (filters) to change")
        if self.operation in ("create_record", "update_record") and not self.values:
            raise ValueError("Create and update actions must specify the values to save")
        return self


# --- REST API --------------------------------------------------------------------


class RestToolConfig(Strict):
    integration_id: UUID
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = "/"
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    # Nested body template; "customer.fullName": "{{customer_name}}" style keys are expanded.
    body: dict[str, Any] | None = None
    # result key -> dotted path in the response ("data.items[].id")
    response_mapping: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(10.0, gt=0, le=60)


# --- Built-ins ---------------------------------------------------------------------


class HandoffToolConfig(Strict):
    # Use a fixed target key, or let the caller's request pick one of the agent's targets.
    target: str | None = None


class KnowledgeToolConfig(Strict):
    top_k: int = Field(4, ge=1, le=10)


class EmptyConfig(Strict):
    pass


class ToolDefinition(Strict):
    name: str = Field(..., pattern=TOOL_NAME_RE)
    display_name: str = ""
    description: str = Field(..., min_length=3, max_length=1000)
    category: ToolCategory
    # database | rest_api | transfer_call | end_call | knowledge_search
    executor: Literal["database", "rest_api", "transfer_call", "end_call", "knowledge_search"]
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    requires_confirmation: bool = False
    # Short business description of what will happen, used for confirmation prompts.
    confirmation_template: str = ""
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema")
    @classmethod
    def _valid_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") != "object":
            raise ValueError("Tool input must be an object with named fields")
        try:
            Draft202012Validator.check_schema(v)
        except SchemaError as exc:
            raise ValueError(f"Invalid input definition: {exc.message}") from exc
        for prop in v.get("properties", {}):
            if not IDENT_RE.match(prop):
                raise ValueError(f"Invalid input field name: {prop}")
        return v

    @model_validator(mode="after")
    def _config_matches_executor(self) -> ToolDefinition:
        self.typed_config()  # raises on mismatch
        required = set(self.input_schema.get("required", []))
        props = set(self.input_schema.get("properties", {}))
        missing = required - props
        if missing:
            raise ValueError(f"Required inputs are not defined: {', '.join(sorted(missing))}")
        return self

    def typed_config(self) -> BaseModel:
        model: type[BaseModel] = {
            "database": DatabaseToolConfig,
            "rest_api": RestToolConfig,
            "transfer_call": HandoffToolConfig,
            "end_call": EmptyConfig,
            "knowledge_search": KnowledgeToolConfig,
        }[self.executor]
        return model.model_validate(self.config)

    def llm_schema(self) -> dict[str, Any]:
        """OpenAI-compatible function definition. Contains no configuration or secrets."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.input_schema},
        }


def builtin_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="transfer_call",
            display_name="Transfer to a human",
            description="Transfer the caller to a human staff member. Use when the caller asks for a person "
            "or when you cannot complete their request.",
            category=ToolCategory.human_handoff,
            executor="transfer_call",
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Short reason for the transfer"},
                    "department": {"type": "string", "description": "Optional department key"},
                },
                "required": ["reason"],
            },
        ),
        ToolDefinition(
            name="end_call",
            display_name="End call",
            description="End the call after the caller says goodbye and nothing else is needed.",
            category=ToolCategory.voice,
            executor="end_call",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="search_knowledge",
            display_name="Search business knowledge",
            description="Search the business knowledge base (prices, policies, services, location, hours). "
            "Always use this before answering factual questions about the business.",
            category=ToolCategory.knowledge,
            executor="knowledge_search",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The question to look up"}},
                "required": ["query"],
            },
        ),
    ]
