"""LiveKit Agents worker. Phone calls arrive via LiveKit SIP dispatch rules; browser tests via an explicit
agent dispatch from the API. Run: python -m nexa_voice.main start"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, cli
from livekit.plugins import silero

from nexa.core.config import get_settings
from nexa.core.db import get_sessionmaker
from nexa.models import AgentVersion
from nexa.providers.registry import get_sip, get_stt, get_tts
from nexa.runtime.session import ConversationRuntime
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.telephony import resolve_inbound
from nexa.services.voices import resolve_voice, stt_keywords
from nexa_voice.agent import CallHandle, NexaVoiceAgent
from nexa_voice.plugins import NexaSTT, NexaTTS, RuntimeLLM

log = logging.getLogger("nexa.voice")
AGENT_NAME = "nexa-voice"

s = get_settings()
server = AgentServer(ws_url=s.livekit_url, api_key=s.livekit_api_key, api_secret=s.livekit_api_secret)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.45)


server.setup_fnc = prewarm


async def _start_call(ctx: JobContext, meta: dict, caller_number: str | None, called_number: str | None):
    async with get_sessionmaker()() as db:
        if meta.get("version_id"):  # browser test dispatched by the API
            version = await db.get(AgentVersion, UUID(meta["version_id"]))
            tenant_id, agent_id, number_id, channel, is_test = (UUID(meta["tenant_id"]), UUID(meta["agent_id"]), None,
                                                                "web", True)
        else:
            route = await resolve_inbound(db, called_number or meta.get("number", ""))
            if route is None:
                return None, None, None
            version, tenant_id, agent_id, number_id = route.version, route.tenant_id, route.agent_id, route.phone_number_id
            channel, is_test = "phone", False
        rt, opening = await ConversationRuntime.start(
            db, tenant_id=tenant_id, agent_id=agent_id, version=version, channel=channel, is_test=is_test,
            caller_number=caller_number, to_number=called_number, external_id=ctx.room.name, phone_number_id=number_id)
        await db.commit()
        return rt.call.id, tenant_id, (opening, AgentDefinition.model_validate(version.config["definition"]))


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    caller_number = participant.attributes.get("sip.phoneNumber")
    called_number = participant.attributes.get("sip.trunkPhoneNumber") or meta.get("number")
    call_id, tenant_id, started = await _start_call(ctx, meta, caller_number, called_number)
    if call_id is None:
        log.warning("no route for %s", called_number)
        ctx.shutdown("no route")
        return
    opening, defn = started
    handle = CallHandle(call_id=call_id, tenant_id=tenant_id, language=defn.language_behavior.primary_language,
                        thinking_fillers=defn.voice.thinking_fillers)
    provider, voice_id = resolve_voice(defn, handle.language, None)
    tts_provider = get_tts(provider) or get_tts()
    voice_tts = NexaTTS(tts_provider, voice_id, handle.language, defn.voice.speed)

    def switch_voice(language: str, dialect: str | None) -> None:
        voice_tts.language = language
        voice_tts.voice_id = resolve_voice(defn, language, dialect)[1]

    agent = NexaVoiceAgent(handle, tts_for_language=switch_voice)
    session = AgentSession(stt=NexaSTT(get_stt(), prompt="مكالمة هاتفية. Phone call in Arabic and English.",
                                       keywords=stt_keywords(defn)),
                           llm=RuntimeLLM(), tts=voice_tts, vad=ctx.proc.userdata["vad"], allow_interruptions=True,
                           min_endpointing_delay=0.4, max_endpointing_delay=2.5)

    async def finish(reason: str = "caller_hangup") -> None:
        async with get_sessionmaker()() as db:
            rt = await ConversationRuntime.load(db, call_id, tenant_id)
            if rt:
                await rt.end(reason)
                await db.commit()

    ctx.add_shutdown_callback(finish)

    @session.on("agent_state_changed")
    def _on_state(ev) -> None:
        # Execute transfers / hang-ups only after the agent finished speaking.
        if ev.new_state == "listening" and handle.pending_actions:
            action = handle.pending_actions.pop(0)
            asyncio.create_task(_execute(action))

    async def _execute(action: dict) -> None:
        if action["type"] == "transfer" and caller_number:
            sip = get_sip()
            if sip:
                try:
                    await sip.transfer(room_name=ctx.room.name, participant_identity=participant.identity,
                                       to_e164=action["phone_number"])
                except Exception:  # noqa: BLE001
                    log.exception("transfer failed")
                    return
        await finish("transferred" if action["type"] == "transfer" else "agent_ended")
        ctx.shutdown(action["type"])

    await session.start(agent=agent, room=ctx.room)
    for reply in opening.replies:
        session.say(reply, allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
