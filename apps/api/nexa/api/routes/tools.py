from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from nexa.api.schemas import ToolOut, ToolTestIn
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.models import Tool, ToolVersion
from nexa.schemas.agent_definition import AgentDefinition
from nexa.schemas.tool_definition import ToolCategory, builtin_tools
from nexa.services.audit import audit
from nexa.services.tools import create_tool, get_tool, parse_definition, update_tool
from nexa.tools.executor import ToolContext, ToolExecutor

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    return {"categories": [c.value for c in ToolCategory],
            "generic_operations": ["get_record", "search_records", "create_record", "update_record", "delete_record",
                                   "http_request", "transfer_call", "end_call", "search_knowledge"],
            "builtins": [b.model_dump(mode="json") for b in builtin_tools()]}


@router.get("", response_model=list[ToolOut])
async def list_tools(ctx: TenantContext = Depends(get_tenant_context)):
    return list(await ctx.db.scalars(select(Tool).where(Tool.tenant_id == ctx.tenant_id, Tool.deleted_at.is_(None))
                                     .order_by(Tool.name)))


@router.post("", response_model=ToolOut, status_code=201)
async def create(body: dict[str, Any], ctx: TenantContext = Depends(require("write"))):
    tool = await create_tool(ctx, parse_definition(body))
    audit(ctx, "tool.create", "tool", tool.id, {"name": tool.name})
    await ctx.db.commit()
    return tool


@router.get("/{tool_id}", response_model=ToolOut)
async def get(tool_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    return await get_tool(ctx, tool_id)


@router.put("/{tool_id}", response_model=ToolOut)
async def update(tool_id: UUID, body: dict[str, Any], ctx: TenantContext = Depends(require("write"))):
    tool = await update_tool(ctx, await get_tool(ctx, tool_id), parse_definition(body))
    audit(ctx, "tool.update", "tool", tool.id, {"version": tool.current_version})
    await ctx.db.commit()
    await ctx.db.refresh(tool)
    return tool


@router.get("/{tool_id}/versions")
async def versions(tool_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    await get_tool(ctx, tool_id)
    rows = await ctx.db.scalars(select(ToolVersion).where(ToolVersion.tool_id == tool_id,
                                                          ToolVersion.tenant_id == ctx.tenant_id)
                                .order_by(ToolVersion.version_number.desc()))
    return [{"id": str(v.id), "version_number": v.version_number, "definition": v.definition,
             "created_at": v.created_at.isoformat()} for v in rows]


@router.delete("/{tool_id}", status_code=204)
async def delete(tool_id: UUID, ctx: TenantContext = Depends(require("write"))):
    tool = await get_tool(ctx, tool_id)
    tool.deleted_at = datetime.now(UTC)
    tool.name = f"{tool.name}__deleted_{tool.id.hex[:6]}"[:100]
    audit(ctx, "tool.delete", "tool", tool.id)
    await ctx.db.commit()


@router.post("/{tool_id}/test")
async def test_tool(tool_id: UUID, body: ToolTestIn, ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    """Run an action once with sample inputs (logged as an api_test execution)."""
    tool = await get_tool(ctx, tool_id)
    snapshot = {"definition": AgentDefinition(name="test").model_dump(mode="json"),
                "tools": [{"tool_id": str(tool.id), "tool_version_id": None, "definition": tool.definition}]}
    executor = ToolExecutor(ToolContext(db=ctx.db, tenant_id=ctx.tenant_id, snapshot=snapshot))
    result = await executor.execute(tool.name, body.arguments, source="api_test", confirmed=True)
    await ctx.db.commit()
    return result.as_dict()
