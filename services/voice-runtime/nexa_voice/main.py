"""LiveKit Agents worker. Phone calls arrive via LiveKit SIP dispatch rules; browser tests via an explicit
agent dispatch from the API. Run: python -m nexa_voice.main start"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from livekit.agents import AgentServer, AgentSession, JobContext, JobExecutorType, JobProcess, cli
from livekit.plugins import silero

from nexa.core.config import get_settings
from nexa.core.db import get_sessionmaker
from nexa.models import AgentVersion
from nexa.nlp.pronounce import parse_pronunciations, speakable
from nexa.providers.registry import get_sip, get_stt, get_tts
from nexa.runtime.session import ConversationRuntime
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.telephony import resolve_inbound
from nexa.services.voices import resolve_voice, stt_keywords
from nexa_voice.agent import FILLERS, CallHandle, NexaVoiceAgent
from nexa_voice.plugins import NexaSTT, NexaTTS, RuntimeLLM

log = logging.getLogger("nexa.voice")
AGENT_NAME = "nexa-voice"

s = get_settings()


async def save_recording(session: AgentSession, tenant_id: UUID, call_id: UUID) -> str | None:
    """Finish the call's recording and move it to the recordings folder; returns its path relative to it."""
    recorder = getattr(session, "_recorder_io", None)
    if recorder is None:
        return None
    try:
        await recorder.aclose()
        source = recorder.output_path
        if source is None or not source.exists():
            return None
        relative = f"{tenant_id}/{call_id}.ogg"
        target = Path(s.recordings_dir) / relative
        await asyncio.to_thread(_move, source, target)
        return relative
    except Exception:  # noqa: BLE001 - the call itself must still be closed properly
        log.exception("could not save the call recording")
        return None


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def livekit_proxy(url: str) -> str | None:
    """The proxy for reaching LiveKit. livekit-agents uses HTTPS_PROXY for every host, ignoring NO_PROXY,
    so a local LiveKit (localhost, a Docker service name) behind a corporate proxy would be unreachable."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY")
    host = urlparse(url).hostname or ""
    if not proxy or urllib.request.proxy_bypass_environment(host):
        return None
    return proxy


# Everything runs on your own servers: no LiveKit Cloud turn/interruption models. The caller can interrupt
# (barge-in), and their words are never thrown away as a "false interruption" while Whisper is still transcribing.
TURN_HANDLING = {
    "turn_detection": "vad",
    "endpointing": {"min_delay": 0.4, "max_delay": 2.5},
    # Keep what the caller says while the agent can't be interrupted (e.g. the first seconds of the greeting),
    # instead of dropping it and hearing only the end of their sentence.
    "interruption": {"enabled": True, "mode": "vad", "min_duration": 0.5, "discard_audio_if_uninterruptible": False,
                     "resume_false_interruption": False, "false_interruption_timeout": None},
}

# By default LiveKit only sends calls to a worker while the machine's CPU is below 70%. When everything runs on one
# computer (scripts/dev-mac.sh: LLM, Whisper, voices), CPU says little about free call capacity, so
# VOICE_MAX_CALLS=N reports load as calls in progress / N instead.
MAX_CALLS = int(os.getenv("VOICE_MAX_CALLS", "0"))


def calls_load(worker: AgentServer) -> float:
    return min(len(worker.active_jobs) / MAX_CALLS, 1.0)


# VOICE_LIGHT=1 (scripts/dev-mac.sh): run calls as threads in this one process instead of a separate process per call
# plus pre-started spares (~400 MB each). For a single computer handling a few calls at a time.
LIGHT = os.getenv("VOICE_LIGHT", "0") == "1"
_light_options = {"job_executor_type": JobExecutorType.THREAD, "num_idle_processes": 0} if LIGHT else {}

server = AgentServer(ws_url=s.livekit_url, api_key=s.livekit_api_key, api_secret=s.livekit_api_secret,
                     http_proxy=livekit_proxy(s.livekit_url),
                     # Full only when every call slot is taken (LiveKit's default refuses calls above 70% load).
                     **({"load_fnc": calls_load, "load_threshold": 1.0} if MAX_CALLS > 0 else {}),
                     **_light_options)


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
    # The session plays at one rate: the engine's own (natural voices 24 kHz, Piper 22.05 kHz).
    voice_tts = NexaTTS(tts_provider, voice_id, handle.language, defn.voice.speed,
                        sample_rate=24000 if getattr(tts_provider, "name", "") == "neural" else 22050,
                        pronunciations=parse_pronunciations(defn.voice.pronunciations))

    def switch_voice(language: str, dialect: str | None) -> None:
        voice_tts.language = language
        voice_tts.voice_id = resolve_voice(defn, language, dialect)[1]

    agent = NexaVoiceAgent(handle, tts_for_language=switch_voice)
    session = AgentSession(stt=NexaSTT(get_stt(), prompt="مكالمة هاتفية. Phone call in Arabic and English.",
                                       keywords=stt_keywords(defn), languages=[getattr(lang, "value", lang) for lang in defn.languages]),
                           llm=RuntimeLLM(), tts=voice_tts, vad=ctx.proc.userdata["vad"], turn_handling=TURN_HANDLING)

    record = bool(defn.privacy.record_calls)
    finished = False

    async def finish(reason: str = "caller_hangup") -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        recording = await save_recording(session, tenant_id, call_id) if record else None
        async with get_sessionmaker()() as db:
            rt = await ConversationRuntime.load(db, call_id, tenant_id)
            if rt:
                await rt.end(reason)
                if recording:
                    rt.call.recording_uri = recording
                await db.commit()

    ctx.add_shutdown_callback(finish)

    @session.on("close")
    def _on_close(ev) -> None:
        # The caller hung up: close the call (and save its recording) now, not when LiveKit later ends the job.
        async def close_call() -> None:
            await finish("caller_hangup")
            ctx.shutdown("call ended")

        asyncio.create_task(close_call())

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        # One line per stage, so a slow call shows where the time went (.dev/voice-runtime.log).
        m, kind = ev.metrics, type(ev.metrics).__name__
        if kind == "EOUMetrics":
            log.info("timing: end of caller's turn detected after %.2fs", m.end_of_utterance_delay)
        elif kind == "TTSMetrics" and m.ttfb >= 0 and m.audio_duration > 0:
            log.info("timing: voice started after %.2fs (%.1fs of speech)", m.ttfb, m.audio_duration)

    warmed: set[tuple[str, str]] = set()

    async def warm_filler(language: str, voice_id: str) -> None:
        """Render "one moment" for this voice ahead of time; the voice service caches it, so it plays instantly."""
        try:
            await tts_provider.synthesize(speakable(FILLERS.get(language, FILLERS["ar"])), voice_id=voice_id, language=language,
                                          speed=defn.voice.speed)
        except Exception:  # noqa: BLE001 - only an optimisation
            log.debug("could not pre-render the filler phrase", exc_info=True)

    @session.on("agent_state_changed")
    def _on_state(ev) -> None:
        # While the caller talks (after the agent spoke), pre-render the filler for the current voice once.
        key = (voice_tts.language, voice_tts.voice_id)
        if ev.new_state == "listening" and handle.thinking_fillers and key not in warmed:
            warmed.add(key)
            asyncio.create_task(warm_filler(*key))
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

    # Recording (agent setting): caller and agent on separate stereo channels, only what was actually heard.
    await session.start(agent=agent, room=ctx.room,
                        record={"audio": True, "traces": False, "logs": False, "transcript": False} if record else False)
    for reply in opening.replies:
        session.say(reply, allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
