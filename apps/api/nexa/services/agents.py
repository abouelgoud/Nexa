"""Agent drafts, immutable version snapshots and the publish checklist."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select

from nexa.core.deps import TenantContext
from nexa.core.errors import NotFound, ValidationFailed, friendly_validation_errors
from nexa.models import (
    Agent,
    AgentLanguage,
    AgentRule,
    AgentTool,
    AgentVersion,
    AgentVoice,
    Document,
    Integration,
    KnowledgeBase,
    PhoneNumber,
    Tool,
    ToolVersion,
)
from nexa.schemas.agent_definition import AgentDefinition
from nexa.schemas.tool_definition import DatabaseToolConfig, ToolDefinition, builtin_tools
from nexa.schemas.workflow import WorkflowGraph, validate_workflow
from nexa.services.workflows import get_workflow, load_graph
from nexa.tools.permissions import check_database_tool

# Which capabilities need at least one tool of a given kind.
CAPABILITY_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "book_appointment": ("book", "create_appointment", "reserve"),
    "cancel_appointment": ("cancel",),
    "reschedule_appointment": ("reschedule",),
}


def parse_definition(data: dict[str, Any]) -> AgentDefinition:
    try:
        return AgentDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("Some agent settings are not valid.",
                               details=friendly_validation_errors(exc.errors())) from exc


async def get_agent(ctx: TenantContext, agent_id: UUID) -> Agent:
    agent = await ctx.db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != ctx.tenant_id or agent.deleted_at is not None:
        raise NotFound("Agent not found.")
    return agent


async def sync_agent_tools(ctx: TenantContext, agent: Agent, tool_ids: list[UUID]) -> None:
    existing = {t.tool_id: t for t in (await ctx.db.scalars(select(AgentTool).where(AgentTool.agent_id == agent.id))).all()}
    wanted = set(tool_ids)
    for tid, link in existing.items():
        if tid not in wanted:
            await ctx.db.delete(link)
    for tid in wanted - set(existing):
        tool = await ctx.db.get(Tool, tid)
        if tool is None or tool.tenant_id != ctx.tenant_id or tool.deleted_at is not None:
            raise ValidationFailed("One of the selected actions no longer exists.")
        ctx.db.add(AgentTool(tenant_id=ctx.tenant_id, agent_id=agent.id, tool_id=tid))


async def resolve_snapshot(ctx: TenantContext, agent: Agent) -> dict[str, Any]:
    """Build the full, self-contained configuration a call needs (no secrets)."""
    defn = parse_definition(agent.draft_config)
    tools: list[dict[str, Any]] = []
    for tid in defn.tool_ids:
        tool = await ctx.db.get(Tool, tid)
        if tool is None or tool.tenant_id != ctx.tenant_id or tool.deleted_at is not None:
            continue
        tv = await ctx.db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id,
                                                           ToolVersion.version_number == tool.current_version))
        tools.append({"tool_id": str(tool.id), "tool_version_id": str(tv.id) if tv else None,
                      "definition": tool.definition})
    names = {t["definition"]["name"] for t in tools}
    builtins = [b for b in builtin_tools() if b.name not in names]
    if not defn.handoff.enabled or not defn.policies.human_handoff_enabled:
        builtins = [b for b in builtins if b.name != "transfer_call"]
    if not defn.knowledge_base_ids:
        builtins = [b for b in builtins if b.name != "search_knowledge"]
    for b in builtins:
        tools.append({"tool_id": None, "tool_version_id": None, "definition": b.model_dump(mode="json"), "builtin": True})
    workflow = None
    if defn.workflow_id:
        wf = await get_workflow(ctx, defn.workflow_id)
        workflow = {"id": str(wf.id), "revision": wf.revision,
                    "graph": (await load_graph(ctx, wf.id)).model_dump(mode="json")}
    return {"definition": defn.model_dump(mode="json"), "tools": tools, "workflow": workflow}


def _hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _next_version_number(ctx: TenantContext, agent_id: UUID) -> int:
    current = await ctx.db.scalar(select(func.max(AgentVersion.version_number)).where(AgentVersion.agent_id == agent_id))
    return (current or 0) + 1


async def create_snapshot(ctx: TenantContext, agent: Agent, kind: str, notes: str = "") -> AgentVersion:
    config = await resolve_snapshot(ctx, agent)
    h = _hash(config)
    if kind == "test":
        existing = await ctx.db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id,
                                                                  AgentVersion.config_hash == h)
                                       .order_by(AgentVersion.version_number.desc()))
        if existing:
            return existing
    now = datetime.now(UTC)
    version = AgentVersion(tenant_id=ctx.tenant_id, agent_id=agent.id, version_number=await _next_version_number(ctx, agent.id),
                           kind=kind, config=config, config_hash=h, notes=notes,
                           published_at=now if kind == "published" else None,
                           created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(version)
    await ctx.db.flush()
    _write_projections(ctx, version, AgentDefinition.model_validate(config["definition"]))
    return version


def _write_projections(ctx: TenantContext, version: AgentVersion, defn: AgentDefinition) -> None:
    """Normalized, queryable copies of the snapshot (languages, voices, rules)."""
    tid, vid = ctx.tenant_id, version.id
    for lang in defn.languages:
        primary = lang == defn.language_behavior.primary_language
        if lang == "ar":
            for d in defn.arabic_dialects or [None]:
                ctx.db.add(AgentLanguage(tenant_id=tid, agent_version_id=vid, language=lang, dialect=d, is_primary=primary))
        else:
            ctx.db.add(AgentLanguage(tenant_id=tid, agent_version_id=vid, language=lang, is_primary=primary))
    ctx.db.add(AgentVoice(tenant_id=tid, agent_version_id=vid, language="ar", provider=defn.voice.provider,
                          voice_id=defn.voice.voice_id, speed=defn.voice.speed))
    if defn.voice.english_voice_id:
        ctx.db.add(AgentVoice(tenant_id=tid, agent_version_id=vid, language="en", provider=defn.voice.provider,
                              voice_id=defn.voice.english_voice_id, speed=defn.voice.speed))
    for key, value in defn.policies.model_dump().items():
        ctx.db.add(AgentRule(tenant_id=tid, agent_version_id=vid, rule_type="policy", key=key, value={"value": value}))
    ctx.db.add(AgentRule(tenant_id=tid, agent_version_id=vid, rule_type="handoff", key="handoff",
                         value=defn.handoff.model_dump(mode="json")))
    ctx.db.add(AgentRule(tenant_id=tid, agent_version_id=vid, rule_type="privacy", key="privacy",
                         value=defn.privacy.model_dump(mode="json")))


async def publish_checklist(ctx: TenantContext, agent: Agent) -> list[dict[str, Any]]:
    """The pre-publish checklist, in business language."""
    items: list[dict[str, Any]] = []

    def add(key: str, label: str, ok: bool, message: str = "", severity: str = "error") -> None:
        items.append({"key": key, "label": label, "ok": ok, "message": "" if ok else message, "severity": severity})

    try:
        defn = AgentDefinition.model_validate(agent.draft_config)
    except ValidationError as exc:
        add("definition", "Agent settings are valid", False,
            "; ".join(e["message"] for e in friendly_validation_errors(exc.errors())))
        return items
    add("definition", "Agent settings are valid", True)
    add("greeting", "Agent has a greeting", bool(defn.general.greeting.strip()),
        "Add a greeting in General settings so callers know who they reached.")
    add("voice", "Voice configured", bool(defn.voice.voice_id), "Choose a voice for the agent.")
    add("language", "Language configured", bool(defn.languages), "Choose at least one language.")
    add("capabilities", "At least one capability", bool(defn.capabilities),
        "Choose what the agent can do (for example: answer questions or book appointments).")

    tools: list[ToolDefinition] = []
    tool_problems: list[str] = []
    for tid in defn.tool_ids:
        tool = await ctx.db.get(Tool, tid)
        if tool is None or tool.tenant_id != ctx.tenant_id or tool.deleted_at is not None:
            tool_problems.append("An action selected for this agent was deleted.")
            continue
        try:
            td = ToolDefinition.model_validate(tool.definition)
        except ValidationError:
            tool_problems.append(f'The action "{tool.display_name or tool.name}" is not configured correctly.')
            continue
        tools.append(td)
        cfg = td.typed_config()
        if isinstance(cfg, DatabaseToolConfig):
            integ = await ctx.db.get(Integration, cfg.integration_id)
            if integ is None or integ.deleted_at is not None or integ.tenant_id != ctx.tenant_id:
                tool_problems.append(f'"{td.display_name or td.name}" uses a database connection that was removed.')
            else:
                tool_problems.extend(check_database_tool(td, cfg, integ.config.get("permissions", {})))
    tool_names = {t.name for t in tools}
    missing_caps = []
    for cap, hints in CAPABILITY_TOOL_HINTS.items():
        if cap in defn.capabilities and not any(any(h in n for h in hints) for n in tool_names):
            missing_caps.append(cap.replace("_", " "))
    add("required_tools", "Required actions configured", not missing_caps,
        f"Add an action for: {', '.join(missing_caps)}.")
    add("tool_permissions", "Action permissions valid", not tool_problems, " ".join(tool_problems))

    kb_ok, kb_msg = True, ""
    for kb_id in defn.knowledge_base_ids:
        kb = await ctx.db.get(KnowledgeBase, kb_id)
        if kb is None or kb.deleted_at is not None or kb.tenant_id != ctx.tenant_id:
            kb_ok, kb_msg = False, "A selected knowledge base was deleted."
            break
        ready = await ctx.db.scalar(select(func.count()).select_from(Document).where(
            Document.knowledge_base_id == kb.id, Document.status == "ready", Document.deleted_at.is_(None)))
        if not ready:
            kb_ok, kb_msg = False, f'The knowledge base "{kb.name}" has no processed documents yet.'
            break
    if "answer_questions" in defn.capabilities and not defn.knowledge_base_ids:
        add("knowledge", "Knowledge base valid", False,
            "The agent answers questions but has no knowledge base. Upload your business information.", "warning")
    else:
        add("knowledge", "Knowledge base valid", kb_ok, kb_msg)

    numbers = (await ctx.db.scalars(select(PhoneNumber).where(PhoneNumber.agent_id == agent.id,
                                                              PhoneNumber.deleted_at.is_(None)))).all()
    bad = [n.e164 for n in numbers if n.status == "error"]
    add("phone", "Phone route valid", not bad, f"These numbers have a connection problem: {', '.join(bad)}",
        "warning" if not numbers else "error")

    wf_msgs: list[str] = []
    if defn.workflow_id:
        try:
            await get_workflow(ctx, defn.workflow_id)
            graph = WorkflowGraph.model_validate((await load_graph(ctx, defn.workflow_id)).model_dump())
            builtin_names = {b.name for b in builtin_tools()}
            wf_msgs = [i.message for i in validate_workflow(graph, tool_names | builtin_names) if i.severity == "error"]
        except (NotFound, ValidationError, ValueError) as exc:
            wf_msgs = [getattr(exc, "message", None) or "The workflow is not valid."]
    add("workflow", "No invalid workflow steps", not wf_msgs, " ".join(wf_msgs))
    return items


async def publish(ctx: TenantContext, agent: Agent, notes: str = "") -> AgentVersion:
    checklist = await publish_checklist(ctx, agent)
    blocking = [c for c in checklist if not c["ok"] and c["severity"] == "error"]
    if blocking:
        raise ValidationFailed("The agent is not ready to publish yet.", details=checklist)
    version = await create_snapshot(ctx, agent, "published", notes)
    agent.published_version_id = version.id
    agent.status = "published"
    agent.updated_by = ctx.user.id
    return version
