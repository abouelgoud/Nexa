"""Browser testing: text and push-to-talk voice turns against a draft or published agent."""

import base64
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from nexa.api.schemas import TestMessageIn, TestSessionIn
from nexa.core.config import get_settings
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from nexa.core.observability import STT_LATENCY, TTS_LATENCY
from nexa.core.rate_limit import limiter
from nexa.models import AgentVersion
from nexa.providers.registry import get_llm, get_stt, get_tts
from nexa.providers.stt.base import STTError
from nexa.providers.tts.base import TTSError
from nexa.runtime.session import ConversationRuntime, TurnResult
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.agents import create_snapshot, get_agent
from nexa.services.usage import record_usage
from nexa.services.voices import resolve_voice, stt_keywords

router = APIRouter(prefix="/test", tags=["test"], dependencies=[Depends(limiter("test", 240))])


async def _speak(ctx: TenantContext, rt: ConversationRuntime, result: TurnResult) -> list[dict[str, Any]]:
    defn: AgentDefinition = rt.definition
    provider, voice = resolve_voice(defn, rt.lang, rt.session.dialect)
    tts = get_tts(provider)
    if tts is None or not result.replies:
        if result.replies and tts is None:
            return [{"error": f"The '{provider}' voice is not configured on this server."}]
        return []
    clips = []
    for text in result.replies:
        try:
            r = await tts.synthesize(text, voice_id=voice, language=rt.lang, speed=defn.voice.speed)
        except TTSError as exc:
            return [{"error": str(exc)}]
        TTS_LATENCY.observe(r.latency_ms / 1000)
        record_usage(ctx.db, ctx.tenant_id, "tts_characters", len(text), call_id=rt.call.id, agent_id=rt.call.agent_id)
        clips.append({"mime_type": r.mime_type, "audio_base64": base64.b64encode(r.audio).decode(),
                      "latency_ms": round(r.latency_ms, 1)})
    result.latency_ms["tts"] = round(sum(c["latency_ms"] for c in clips), 1)
    return clips


@router.get("/providers")
async def providers(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    s = get_settings()
    stt, tts, llm = get_stt(), get_tts(), get_llm()
    return {"local_ai": s.local_ai,
            "llm": {"provider": s.llm_provider, "model": s.llm_model, "healthy": await llm.health()},
            "stt": {"provider": s.stt_provider, "healthy": await stt.health() if stt else False},
            "tts": {"provider": s.tts_provider, "healthy": await tts.health() if tts else False}}


@router.post("/sessions", status_code=201)
async def start_session(body: TestSessionIn, voice: bool = False,
                        ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    agent = await get_agent(ctx, body.agent_id)
    if body.use == "published":
        if agent.published_version_id is None:
            raise ValidationFailed("This agent has not been published yet. Test the draft instead.")
        version = await ctx.db.get(AgentVersion, agent.published_version_id)
    else:
        version = await create_snapshot(ctx, agent, "test", "test snapshot")
    rt, result = await ConversationRuntime.start(ctx.db, tenant_id=ctx.tenant_id, agent_id=agent.id, version=version,
                                                 channel="web", is_test=True, caller_number=body.caller_number)
    audio = await _speak(ctx, rt, result) if voice else []
    await ctx.db.commit()
    return {"session_id": str(rt.call.id), "agent_version": {"id": str(version.id), "number": version.version_number,
                                                             "kind": version.kind},
            "mode": rt.definition.execution_mode, "result": result.as_dict(), "audio": audio}


async def _load(ctx: TenantContext, session_id: UUID) -> ConversationRuntime:
    rt = await ConversationRuntime.load(ctx.db, session_id, ctx.tenant_id)
    if rt is None:
        raise NotFound("Test session not found.")
    return rt


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: UUID, body: TestMessageIn, voice: bool = False,
                       ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    rt = await _load(ctx, session_id)
    result = await rt.handle_user_text(body.text)
    audio = await _speak(ctx, rt, result) if voice else []
    await ctx.db.commit()
    return {"result": result.as_dict(), "audio": audio}


@router.post("/sessions/{session_id}/audio")
async def send_audio(session_id: UUID, file: UploadFile = File(...), voice: bool = Form(True),
                     ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    """Push-to-talk: caller audio -> Whisper -> agent -> Piper."""
    rt = await _load(ctx, session_id)
    stt = get_stt()
    if stt is None:
        raise ServiceUnavailable("Speech recognition is not configured.")
    audio = await file.read(10_000_000)
    t0 = time.perf_counter()
    try:
        tr = await stt.transcribe(audio, mime_type=file.content_type or "audio/webm",
                                  prompt="محادثة هاتفية لحجز موعد. Arabic and English phone conversation.",
                                  keywords=stt_keywords(rt.definition))
    except STTError as exc:
        raise ServiceUnavailable("Speech recognition is not available right now. Is the STT service running?",
                                 details=str(exc)) from exc
    stt_ms = (time.perf_counter() - t0) * 1000
    STT_LATENCY.observe(stt_ms / 1000)
    record_usage(ctx.db, ctx.tenant_id, "stt_seconds", tr.duration_seconds, call_id=rt.call.id, agent_id=rt.call.agent_id)
    record_usage(ctx.db, ctx.tenant_id, "audio_seconds", tr.duration_seconds, call_id=rt.call.id,
                 agent_id=rt.call.agent_id)
    result = await rt.handle_user_text(tr.text, stt={"language": tr.language, "duration": tr.duration_seconds,
                                                     "latency_ms": round(stt_ms, 1)})
    result.latency_ms["stt"] = round(stt_ms, 1)
    clips = await _speak(ctx, rt, result) if voice else []
    result.latency_ms["end_to_end"] = round(stt_ms + result.latency_ms.get("turn_total", 0) +
                                            result.latency_ms.get("tts", 0), 1)
    await ctx.db.commit()
    return {"transcript": tr.text, "stt_language": tr.language, "result": result.as_dict(), "audio": clips}


@router.post("/realtime", status_code=201)
async def start_realtime(body: TestSessionIn, ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    """Real-time WebRTC test: returns a LiveKit room token; the voice runtime joins and runs the call."""
    from nexa.providers.telephony.livekit_rooms import browser_test_room

    agent = await get_agent(ctx, body.agent_id)
    if body.use == "published":
        if agent.published_version_id is None:
            raise ValidationFailed("This agent has not been published yet. Test the draft instead.")
        version = await ctx.db.get(AgentVersion, agent.published_version_id)
    else:
        version = await create_snapshot(ctx, agent, "test", "test snapshot")
    await ctx.db.commit()
    room = browser_test_room(f"tester-{ctx.user.id.hex[:8]}", {
        "tenant_id": str(ctx.tenant_id), "agent_id": str(agent.id), "version_id": str(version.id)})
    return {**room, "agent_version": {"id": str(version.id), "number": version.version_number, "kind": version.kind}}


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: UUID, ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    rt = await _load(ctx, session_id)
    await rt.end("ended_by_tester")
    await ctx.db.commit()
    return {"status": rt.call.status, "outcome": rt.call.outcome}
