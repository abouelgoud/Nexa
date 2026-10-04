from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from nexa.core.config import get_settings
from nexa.core.deps import TenantContext, get_tenant_context
from nexa.core.errors import NotFound
from nexa.models import (
    AgentVersion,
    Call,
    CallEvent,
    Conversation,
    Message,
    ToolExecution,
    Transcript,
    WorkflowExecution,
)

router = APIRouter(tags=["calls"])


def call_summary(c: Call) -> dict[str, Any]:
    return {"id": str(c.id), "agent_id": str(c.agent_id), "agent_version_id": str(c.agent_version_id),
            "channel": c.channel, "direction": c.direction, "is_test": c.is_test, "from_number": c.from_number,
            "to_number": c.to_number, "status": c.status, "started_at": c.started_at.isoformat(),
            "ended_at": c.ended_at.isoformat() if c.ended_at else None, "duration_seconds": c.duration_seconds,
            "language": c.language, "dialect": c.dialect, "intent": c.intent, "outcome": c.outcome,
            "transferred_to": c.transferred_to, "error": c.error, "metrics": c.metrics}


@router.get("/calls")
async def list_calls(agent_id: UUID | None = None, status: str | None = None, channel: str | None = None,
                     external_id: str | None = None,
                     include_tests: bool = True, limit: int = Query(50, le=200), offset: int = 0,
                     ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    q = select(Call).where(Call.tenant_id == ctx.tenant_id)
    if agent_id:
        q = q.where(Call.agent_id == agent_id)
    if status:
        q = q.where(Call.status == status)
    if channel:
        q = q.where(Call.channel == channel)
    if external_id:
        q = q.where(Call.external_id == external_id)
    if not include_tests:
        q = q.where(Call.is_test.is_(False))
    rows = await ctx.db.scalars(q.order_by(Call.started_at.desc()).limit(limit).offset(offset))
    return [call_summary(c) for c in rows]


@router.get("/calls/{call_id}")
async def call_detail(call_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    call = await ctx.db.get(Call, call_id)
    if call is None or call.tenant_id != ctx.tenant_id:
        raise NotFound("Call not found.")
    version = await ctx.db.get(AgentVersion, call.agent_version_id)
    conv = await ctx.db.scalar(select(Conversation).where(Conversation.call_id == call.id))
    messages = (await ctx.db.scalars(select(Message).where(Message.conversation_id == conv.id)
                                     .order_by(Message.seq))).all() if conv else []
    transcripts = (await ctx.db.scalars(select(Transcript).where(Transcript.call_id == call.id)
                                        .order_by(Transcript.created_at))).all()
    tools = (await ctx.db.scalars(select(ToolExecution).where(ToolExecution.call_id == call.id)
                                  .order_by(ToolExecution.created_at))).all()
    events = (await ctx.db.scalars(select(CallEvent).where(CallEvent.call_id == call.id)
                                   .order_by(CallEvent.created_at))).all()
    wx = await ctx.db.scalar(select(WorkflowExecution).where(WorkflowExecution.call_id == call.id))
    return {
        "call": call_summary(call),
        "agent_version": {"id": str(version.id), "version_number": version.version_number, "kind": version.kind}
        if version else None,
        "messages": [{"seq": m.seq, "role": m.role, "content": m.content, "original_text": m.original_text,
                      "normalized_text": m.normalized_text, "language": m.language, "dialect": m.dialect,
                      "metadata": m.meta, "created_at": m.created_at.isoformat()} for m in messages],
        "transcripts": [{"speaker": t.speaker, "original_text": t.original_text, "normalized_text": t.normalized_text,
                         "language": t.language, "dialect": t.dialect, "dialect_scores": t.dialect_scores,
                         "confidence": t.confidence, "created_at": t.created_at.isoformat()} for t in transcripts],
        "tool_executions": [{"id": str(t.id), "tool_name": t.tool_name, "category": t.category, "source": t.source,
                             "arguments": t.arguments, "result": t.result, "status": t.status, "error": t.error,
                             "latency_ms": t.latency_ms, "requires_confirmation": t.requires_confirmation,
                             "confirmed": t.confirmed, "created_at": t.created_at.isoformat()} for t in tools],
        "events": [{"type": e.event_type, "payload": e.payload, "latency_ms": e.latency_ms,
                    "created_at": e.created_at.isoformat()} for e in events],
        "workflow": {"status": wx.status, "current_node": wx.current_node, "path": wx.path, "variables": wx.variables}
        if wx else None,
        "has_recording": recording_file(call) is not None,
    }


def recording_file(call: Call) -> Path | None:
    """The call's recording on disk, if it was recorded and still exists (never outside the recordings folder)."""
    if not call.recording_uri:
        return None
    root = Path(get_settings().recordings_dir).resolve()
    path = (root / call.recording_uri).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


@router.get("/calls/{call_id}/recording")
async def call_recording(call_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> FileResponse:
    call = await ctx.db.get(Call, call_id)
    if call is None or call.tenant_id != ctx.tenant_id:
        raise NotFound("Call not found.")
    path = recording_file(call)
    if path is None:
        raise NotFound("This call has no recording.")
    return FileResponse(path, media_type="audio/ogg", filename=f"call-{call.id}.ogg")


@router.get("/conversations/{call_id}")
async def conversation(call_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    detail = await call_detail(call_id, ctx)
    return {"call_id": str(call_id), "messages": detail["messages"]}
