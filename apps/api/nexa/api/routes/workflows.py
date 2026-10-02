from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select

from nexa.api.schemas import WorkflowIn, WorkflowOut
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import ValidationFailed, friendly_validation_errors
from nexa.models import Tool, Workflow
from nexa.schemas.tool_definition import builtin_tools
from nexa.schemas.workflow import NODE_HANDLES, WorkflowGraph, validate_workflow
from nexa.services.audit import audit
from nexa.services.workflows import get_workflow, load_graph, save_graph

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _parse_graph(data: dict[str, Any]) -> WorkflowGraph:
    try:
        return WorkflowGraph.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("The workflow is not valid.", details=friendly_validation_errors(exc.errors())) from exc


async def _tool_names(ctx: TenantContext) -> set[str]:
    names = set(await ctx.db.scalars(select(Tool.name).where(Tool.tenant_id == ctx.tenant_id, Tool.deleted_at.is_(None))))
    return names | {b.name for b in builtin_tools()}


@router.get("/node-types")
async def node_types() -> dict[str, Any]:
    return {k: sorted(v) if v is not None else None for k, v in NODE_HANDLES.items()}


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(agent_id: UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    q = select(Workflow).where(Workflow.tenant_id == ctx.tenant_id, Workflow.deleted_at.is_(None))
    if agent_id:
        q = q.where(Workflow.agent_id == agent_id)
    return list(await ctx.db.scalars(q.order_by(Workflow.updated_at.desc())))


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(body: WorkflowIn, ctx: TenantContext = Depends(require("write"))):
    graph = _parse_graph(body.graph or {"nodes": [
        {"id": "start", "type": "start", "label": "Start", "position": {"x": 0, "y": 0}},
        {"id": "end", "type": "end", "label": "Goodbye", "config": {"text": "شكراً لاتصالك، مع السلامة.",
                                                                    "text_en": "Thank you for calling. Goodbye!"},
         "position": {"x": 0, "y": 160}}],
        "edges": [{"id": "e1", "source": "start", "target": "end"}]})
    wf = Workflow(tenant_id=ctx.tenant_id, agent_id=body.agent_id, name=body.name, description=body.description,
                  created_by=ctx.user.id, updated_by=ctx.user.id, revision=0)
    ctx.db.add(wf)
    await ctx.db.flush()
    await save_graph(ctx, wf, graph)
    audit(ctx, "workflow.create", "workflow", wf.id)
    await ctx.db.commit()
    return wf


@router.get("/{workflow_id}")
async def get(workflow_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    wf = await get_workflow(ctx, workflow_id)
    graph = await load_graph(ctx, wf.id)
    return {**WorkflowOut.model_validate(wf).model_dump(mode="json"), "graph": graph.model_dump(mode="json"),
            "issues": [i.model_dump() for i in validate_workflow(_parse_graph(graph.model_dump()), await _tool_names(ctx))]}


@router.put("/{workflow_id}/graph")
async def put_graph(workflow_id: UUID, graph: dict[str, Any], ctx: TenantContext = Depends(require("write"))):
    wf = await get_workflow(ctx, workflow_id)
    parsed = _parse_graph(graph)
    await save_graph(ctx, wf, parsed)
    audit(ctx, "workflow.update", "workflow", wf.id, {"revision": wf.revision})
    await ctx.db.commit()
    return {"revision": wf.revision,
            "issues": [i.model_dump() for i in validate_workflow(parsed, await _tool_names(ctx))]}


@router.post("/validate")
async def validate(graph: dict[str, Any], ctx: TenantContext = Depends(get_tenant_context)):
    return {"issues": [i.model_dump() for i in validate_workflow(_parse_graph(graph), await _tool_names(ctx))]}


@router.delete("/{workflow_id}", status_code=204)
async def delete(workflow_id: UUID, ctx: TenantContext = Depends(require("write"))):
    wf = await get_workflow(ctx, workflow_id)
    wf.deleted_at = datetime.now(UTC)
    audit(ctx, "workflow.delete", "workflow", wf.id)
    await ctx.db.commit()
