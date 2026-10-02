from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from nexa.api.schemas import (
    AgentCreate,
    AgentDetail,
    AgentOut,
    AgentVersionDetail,
    AgentVersionOut,
    PublishIn,
    TemplateSetupIn,
)
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import NotFound, ValidationFailed
from nexa.models import Agent, AgentVersion, Tool, Workflow
from nexa.schemas.agent_definition import DIALECT_LABELS
from nexa.schemas.tool_definition import ToolDefinition
from nexa.schemas.workflow import WorkflowGraph
from nexa.services import agents as svc
from nexa.services.audit import audit
from nexa.services.tools import create_tool, get_integration, update_tool
from nexa.services.workflows import save_graph
from nexa.templates.catalog import TEMPLATES, get_template

router = APIRouter(prefix="/agents", tags=["agents"])
templates_router = APIRouter(prefix="/templates", tags=["templates"])


@templates_router.get("")
async def list_templates() -> list[dict[str, Any]]:
    return [{"key": t.key, "name": t.name, "name_ar": t.name_ar, "industry": t.industry,
             "description": t.description, "needs_database": t.needs_database} for t in TEMPLATES.values()]


@templates_router.get("/dialects")
async def list_dialects() -> list[dict[str, str]]:
    return [{"code": k, "name": v[0], "name_ar": v[1]} for k, v in DIALECT_LABELS.items()]


@router.get("", response_model=list[AgentOut])
async def list_agents(ctx: TenantContext = Depends(get_tenant_context)):
    rows = await ctx.db.scalars(select(Agent).where(Agent.tenant_id == ctx.tenant_id, Agent.deleted_at.is_(None))
                                .order_by(Agent.created_at.desc()))
    return list(rows)


@router.post("", response_model=AgentDetail, status_code=201)
async def create_agent(body: AgentCreate, ctx: TenantContext = Depends(require("write"))):
    template = get_template(body.template_key)
    if template is None:
        raise ValidationFailed("Unknown template.")
    business = body.business_name or ctx.tenant.name
    config = template.definition(business)
    if body.name:
        config["name"] = body.name
    defn = svc.parse_definition(config)
    agent = Agent(tenant_id=ctx.tenant_id, name=defn.name, description=defn.description,
                  industry=defn.general.industry, template_key=template.key,
                  draft_config=defn.model_dump(mode="json"), created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(agent)
    await ctx.db.flush()
    audit(ctx, "agent.create", "agent", agent.id, {"template": template.key, "name": defn.name})
    await ctx.db.commit()
    return agent


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    return await svc.get_agent(ctx, agent_id)


@router.put("/{agent_id}/config", response_model=AgentDetail)
async def update_config(agent_id: UUID, config: dict[str, Any], ctx: TenantContext = Depends(require("write"))):
    """Replace the draft configuration. Published versions are never modified."""
    agent = await svc.get_agent(ctx, agent_id)
    defn = svc.parse_definition(config)
    for tid in defn.tool_ids:
        tool = await ctx.db.get(Tool, tid)
        if tool is None or tool.tenant_id != ctx.tenant_id or tool.deleted_at is not None:
            raise ValidationFailed("One of the selected actions does not exist.")
    if defn.workflow_id:
        wf = await ctx.db.get(Workflow, defn.workflow_id)
        if wf is None or wf.tenant_id != ctx.tenant_id or wf.deleted_at is not None:
            raise ValidationFailed("The selected workflow does not exist.")
    await svc.sync_agent_tools(ctx, agent, list(defn.tool_ids))
    agent.draft_config = defn.model_dump(mode="json")
    agent.name, agent.description, agent.industry = defn.name, defn.description, defn.general.industry
    agent.updated_by = ctx.user.id
    audit(ctx, "agent.update_draft", "agent", agent.id)
    await ctx.db.commit()
    await ctx.db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: UUID, ctx: TenantContext = Depends(require("write"))):
    from datetime import UTC, datetime

    agent = await svc.get_agent(ctx, agent_id)
    agent.deleted_at = datetime.now(UTC)
    agent.status = "archived"
    audit(ctx, "agent.delete", "agent", agent.id)
    await ctx.db.commit()


@router.get("/{agent_id}/checklist")
async def checklist(agent_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    agent = await svc.get_agent(ctx, agent_id)
    items = await svc.publish_checklist(ctx, agent)
    return {"ready": all(i["ok"] or i["severity"] != "error" for i in items), "items": items}


@router.post("/{agent_id}/publish", response_model=AgentVersionOut, status_code=201)
async def publish(agent_id: UUID, body: PublishIn, ctx: TenantContext = Depends(require("publish"))):
    agent = await svc.get_agent(ctx, agent_id)
    version = await svc.publish(ctx, agent, body.notes)
    audit(ctx, "agent.publish", "agent", agent.id, {"version": version.version_number})
    await ctx.db.commit()
    return version


@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
async def versions(agent_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    await svc.get_agent(ctx, agent_id)
    rows = await ctx.db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id,
                                                           AgentVersion.tenant_id == ctx.tenant_id)
                                .order_by(AgentVersion.version_number.desc()))
    return list(rows)


@router.get("/{agent_id}/versions/{version_id}", response_model=AgentVersionDetail)
async def version_detail(agent_id: UUID, version_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    v = await ctx.db.get(AgentVersion, version_id)
    if v is None or v.agent_id != agent_id or v.tenant_id != ctx.tenant_id:
        raise NotFound("Version not found.")
    return v


@router.post("/{agent_id}/versions/{version_id}/activate", response_model=AgentDetail)
async def activate_version(agent_id: UUID, version_id: UUID, ctx: TenantContext = Depends(require("publish"))):
    """Roll back/forward: point production at an existing immutable published version."""
    agent = await svc.get_agent(ctx, agent_id)
    v = await ctx.db.get(AgentVersion, version_id)
    if v is None or v.agent_id != agent.id or v.kind != "published":
        raise NotFound("Published version not found.")
    agent.published_version_id = v.id
    agent.status = "published"
    audit(ctx, "agent.activate_version", "agent", agent.id, {"version": v.version_number})
    await ctx.db.commit()
    return agent


@router.post("/{agent_id}/versions/{version_id}/restore-draft", response_model=AgentDetail)
async def restore_draft(agent_id: UUID, version_id: UUID, ctx: TenantContext = Depends(require("write"))):
    """Copy an old version's settings into the draft (the old version itself is untouched)."""
    agent = await svc.get_agent(ctx, agent_id)
    v = await ctx.db.get(AgentVersion, version_id)
    if v is None or v.agent_id != agent.id:
        raise NotFound("Version not found.")
    agent.draft_config = v.config["definition"]
    audit(ctx, "agent.restore_draft", "agent", agent.id, {"version": v.version_number})
    await ctx.db.commit()
    await ctx.db.refresh(agent)
    return agent


@router.post("/{agent_id}/template/setup", response_model=AgentDetail)
async def setup_template(agent_id: UUID, body: TemplateSetupIn, ctx: TenantContext = Depends(require("write"))):
    """Create the template's actions (bound to the chosen connection) and workflow, and attach them."""
    agent = await svc.get_agent(ctx, agent_id)
    template = get_template(agent.template_key or "blank")
    if template is None:
        raise ValidationFailed("This agent was not created from a template.")
    config = dict(agent.draft_config)
    tool_ids: list[str] = [str(t) for t in config.get("tool_ids", [])]
    if template.needs_database:
        if body.integration_id is None:
            raise ValidationFailed("Choose the database connection this template should use.")
        integ = await get_integration(ctx, body.integration_id)
        if template.integration_permissions() and not integ.config.get("permissions"):
            integ.config = {**integ.config, "permissions": template.integration_permissions()}
        await ctx.db.flush()
        for raw in template.tools(integ.id):
            defn = ToolDefinition.model_validate(raw)
            existing = await ctx.db.scalar(select(Tool).where(Tool.tenant_id == ctx.tenant_id, Tool.name == defn.name,
                                                              Tool.deleted_at.is_(None)))
            tool = await update_tool(ctx, existing, defn) if existing else await create_tool(ctx, defn)
            await ctx.db.flush()
            if str(tool.id) not in tool_ids:
                tool_ids.append(str(tool.id))
    graph_data = template.workflow()
    if graph_data:
        wf = Workflow(tenant_id=ctx.tenant_id, agent_id=agent.id, name=f"{agent.name} workflow",
                      description=template.description, created_by=ctx.user.id, updated_by=ctx.user.id)
        ctx.db.add(wf)
        await ctx.db.flush()
        await save_graph(ctx, wf, WorkflowGraph.model_validate(graph_data))
        config["workflow_id"] = str(wf.id)
        # Deterministic, works without a GPU; switch to "agent" mode in settings to let the LLM drive.
        config["execution_mode"] = "workflow"
    config["tool_ids"] = tool_ids
    defn = svc.parse_definition(config)
    await svc.sync_agent_tools(ctx, agent, list(defn.tool_ids))
    agent.draft_config = defn.model_dump(mode="json")
    audit(ctx, "agent.template_setup", "agent", agent.id, {"template": template.key})
    await ctx.db.commit()
    await ctx.db.refresh(agent)
    return agent


@router.post("/{agent_id}/duplicate", response_model=AgentDetail, status_code=201)
async def duplicate(agent_id: UUID, ctx: TenantContext = Depends(require("write"))):
    src = await svc.get_agent(ctx, agent_id)
    config = dict(src.draft_config)
    config["name"] = f"{src.name} (copy)"[:200]
    agent = Agent(tenant_id=ctx.tenant_id, name=config["name"], description=src.description, industry=src.industry,
                  template_key=src.template_key, draft_config=config, created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(agent)
    await ctx.db.flush()
    await svc.sync_agent_tools(ctx, agent, [UUID(t) for t in config.get("tool_ids", [])])
    audit(ctx, "agent.duplicate", "agent", agent.id, {"source": str(src.id)})
    await ctx.db.commit()
    await ctx.db.refresh(agent)
    return agent
