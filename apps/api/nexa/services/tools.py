from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from nexa.core.deps import TenantContext
from nexa.core.errors import Conflict, NotFound, ValidationFailed, friendly_validation_errors
from nexa.models import Integration, Tool, ToolVersion
from nexa.schemas.tool_definition import DatabaseToolConfig, RestToolConfig, ToolDefinition
from nexa.tools.permissions import check_database_tool


def parse_definition(data: dict[str, Any]) -> ToolDefinition:
    try:
        return ToolDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("This action is not configured correctly.",
                               details=friendly_validation_errors(exc.errors())) from exc


async def get_integration(ctx: TenantContext, integration_id: UUID) -> Integration:
    integ = await ctx.db.get(Integration, integration_id)
    if integ is None or integ.tenant_id != ctx.tenant_id or integ.deleted_at is not None:
        raise NotFound("The connected system for this action was not found.")
    return integ


async def check_tool_against_integration(ctx: TenantContext, defn: ToolDefinition) -> UUID | None:
    cfg = defn.typed_config()
    if isinstance(cfg, DatabaseToolConfig):
        integ = await get_integration(ctx, cfg.integration_id)
        if integ.kind != "postgres":
            raise ValidationFailed("Database actions must use a database connection.")
        problems = check_database_tool(defn, cfg, integ.config.get("permissions", {}))
        if problems:
            raise ValidationFailed("This action is not allowed by the database permissions.",
                                   details=[{"field": "config", "message": p} for p in problems])
        return integ.id
    if isinstance(cfg, RestToolConfig):
        integ = await get_integration(ctx, cfg.integration_id)
        if integ.kind != "rest_api":
            raise ValidationFailed("API actions must use an API connection.")
        return integ.id
    return None


async def create_tool(ctx: TenantContext, defn: ToolDefinition) -> Tool:
    existing = await ctx.db.scalar(select(Tool).where(Tool.tenant_id == ctx.tenant_id, Tool.name == defn.name, Tool.deleted_at.is_(None)))
    if existing:
        raise Conflict(f'An action named "{defn.name}" already exists.')
    integration_id = await check_tool_against_integration(ctx, defn)
    data = defn.model_dump(mode="json")
    tool = Tool(tenant_id=ctx.tenant_id, name=defn.name, display_name=defn.display_name or defn.name,
                description=defn.description, category=defn.category, definition=data, current_version=1,
                integration_id=integration_id, created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(tool)
    await ctx.db.flush()
    ctx.db.add(ToolVersion(tenant_id=ctx.tenant_id, tool_id=tool.id, version_number=1, definition=data,
                           created_by=ctx.user.id))
    return tool


async def update_tool(ctx: TenantContext, tool: Tool, defn: ToolDefinition) -> Tool:
    if defn.name != tool.name:
        clash = await ctx.db.scalar(select(Tool).where(Tool.tenant_id == ctx.tenant_id, Tool.name == defn.name, Tool.id != tool.id,
                                                       Tool.deleted_at.is_(None)))
        if clash:
            raise Conflict(f'An action named "{defn.name}" already exists.')
    tool.integration_id = await check_tool_against_integration(ctx, defn)
    data = defn.model_dump(mode="json")
    if data == tool.definition:
        return tool
    tool.name, tool.display_name, tool.description = defn.name, defn.display_name or defn.name, defn.description
    tool.category, tool.definition = defn.category, data
    tool.current_version += 1
    tool.updated_by = ctx.user.id
    ctx.db.add(ToolVersion(tenant_id=ctx.tenant_id, tool_id=tool.id, version_number=tool.current_version,
                           definition=data, created_by=ctx.user.id))
    return tool


async def get_tool(ctx: TenantContext, tool_id: UUID) -> Tool:
    tool = await ctx.db.get(Tool, tool_id)
    if tool is None or tool.tenant_id != ctx.tenant_id or tool.deleted_at is not None:
        raise NotFound("Action not found.")
    return tool
