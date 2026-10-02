from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select

from nexa.core.deps import TenantContext
from nexa.core.errors import NotFound
from nexa.models import Workflow, WorkflowEdge, WorkflowNode
from nexa.schemas.workflow import WorkflowEdgeDef, WorkflowGraph, WorkflowNodeDef


async def get_workflow(ctx: TenantContext, workflow_id: UUID) -> Workflow:
    wf = await ctx.db.get(Workflow, workflow_id)
    if wf is None or wf.tenant_id != ctx.tenant_id or wf.deleted_at is not None:
        raise NotFound("Workflow not found.")
    return wf


async def load_graph(ctx: TenantContext, workflow_id: UUID) -> WorkflowGraph:
    nodes = (await ctx.db.scalars(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id))).all()
    edges = (await ctx.db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id))).all()
    return WorkflowGraph.model_construct(
        nodes=[WorkflowNodeDef(id=n.node_key, type=n.node_type, label=n.label, config=n.config, position=n.position)
               for n in sorted(nodes, key=lambda n: n.created_at)],
        edges=[WorkflowEdgeDef(id=e.edge_key, source=e.source_key, target=e.target_key, handle=e.handle,
                               condition=e.condition, label=e.label) for e in edges],
    )


async def save_graph(ctx: TenantContext, wf: Workflow, graph: WorkflowGraph) -> None:
    await ctx.db.execute(delete(WorkflowEdge).where(WorkflowEdge.workflow_id == wf.id))
    await ctx.db.execute(delete(WorkflowNode).where(WorkflowNode.workflow_id == wf.id))
    for n in graph.nodes:
        ctx.db.add(WorkflowNode(tenant_id=ctx.tenant_id, workflow_id=wf.id, node_key=n.id, node_type=n.type,
                                label=n.label, config=n.config, position=n.position))
    for e in graph.edges:
        ctx.db.add(WorkflowEdge(tenant_id=ctx.tenant_id, workflow_id=wf.id, edge_key=e.id, source_key=e.source,
                                target_key=e.target, handle=e.handle, condition=e.condition, label=e.label))
    wf.revision += 1
    wf.updated_by = ctx.user.id
