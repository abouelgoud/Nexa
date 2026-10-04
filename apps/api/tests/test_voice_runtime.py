"""Real-time voice runtime (LiveKit Agents) adapters and the agent<->runtime bridge.

LiveKit itself is not needed: adapters are exercised with in-memory audio, and the agent's turn
bridge runs against the real database. Skipped when livekit-agents is not installed.
"""

import io
import sys
import wave
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

pytest.importorskip("livekit.agents")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "voice-runtime"))

from livekit import rtc  # noqa: E402
from nexa_voice.agent import CallHandle, NexaVoiceAgent  # noqa: E402
from nexa_voice.plugins import NexaSTT, NexaTTS, frames_to_wav  # noqa: E402

from nexa.providers.stt.base import STTProvider, TranscriptionResult  # noqa: E402
from nexa.providers.tts.base import SynthesisResult, TTSProvider  # noqa: E402
from tests.conftest import setup_doctor_agent  # noqa: E402


def tone_frame(seconds=0.5, rate=16000) -> rtc.AudioFrame:
    samples = (np.sin(np.linspace(0, 440 * 2 * np.pi * seconds, int(rate * seconds))) * 8000).astype(np.int16)
    return rtc.AudioFrame(samples.tobytes(), rate, 1, len(samples))


def wav_bytes(seconds=0.3, rate=22050) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.zeros(int(rate * seconds), dtype=np.int16).tobytes())
    return out.getvalue()


class FakeSTT(STTProvider):
    def __init__(self):
        self.received = b""

    async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None, keywords=None,
                         languages=None):
        self.received = audio
        self.keywords = keywords
        return TranscriptionResult(text="أبغى أحجز موعد", language="ar", duration_seconds=0.5)


class FakeTTS(TTSProvider):
    async def synthesize(self, text, *, voice_id, language, speed=1.0):
        return SynthesisResult(audio=wav_bytes(), sample_rate=22050, characters=len(text))


def test_frames_to_wav():
    data = frames_to_wav([tone_frame(), tone_frame()])
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 16000


async def test_stt_adapter():
    provider = FakeSTT()
    event = await NexaSTT(provider, keywords=["سارة العتيبي"]).recognize([tone_frame()])
    assert provider.keywords == ["سارة العتيبي"]
    assert event.alternatives[0].text == "أبغى أحجز موعد"
    assert event.alternatives[0].language == "ar"
    assert provider.received.startswith(b"RIFF")


async def test_tts_adapter_emits_audio():
    t = NexaTTS(FakeTTS(), "ar_JO-kareem-medium")
    frames = []
    async with t.synthesize("مرحبا") as stream:
        async for ev in stream:
            frames.append(ev.frame)
    assert sum(f.samples_per_channel for f in frames) == int(22050 * 0.3)


async def test_voice_agent_bridges_turns_to_runtime(account, clinic_db):
    setup = await setup_doctor_agent(account)
    session = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"],
                                                     "caller_number": "+966500000001"})).json()
    handle = CallHandle(call_id=UUID(session["session_id"]), tenant_id=UUID(account.tenant_id))
    agent = NexaVoiceAgent(handle)
    r = await agent.run_turn("أبغى أحجز موعد عيون")
    assert r.replies == ["هل تفضل طبيب معين؟"]
    await agent.run_turn("لا")
    await agent.run_turn("الأول")
    r = await agent.run_turn("نعم")
    assert r.replies[0].startswith("تم الحجز بنجاح")
    r = await agent.run_turn("ابي اكلم موظف")
    assert handle.pending_actions[0]["type"] == "transfer"
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments") == 1


async def test_voice_agent_llm_node_streams_replies(account, clinic_db):
    from livekit.agents import llm

    setup = await setup_doctor_agent(account)
    session = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"]})).json()
    agent = NexaVoiceAgent(CallHandle(call_id=UUID(session["session_id"]), tenant_id=UUID(account.tenant_id)))
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="I want to book a dentist appointment")
    out = "".join([chunk async for chunk in agent.llm_node(ctx, [], None)])
    assert "Do you prefer a specific doctor?" in out


async def test_filler_spoken_when_answer_is_slow(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4

    import nexa_voice.agent as agent_mod
    from livekit.agents import llm

    monkeypatch.setattr(agent_mod, "FILLER_AFTER_SECONDS", 0.05)
    agent = NexaVoiceAgent(CallHandle(call_id=uuid4(), tenant_id=uuid4(), language="ar"))

    async def slow_turn(text, stt_meta=None):
        await asyncio.sleep(0.2)
        return SimpleNamespace(replies=["عندي موعد يوم الأحد."])

    agent.run_turn = slow_turn
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="أبغى موعد")
    chunks = [c async for c in agent.llm_node(ctx, [], None)]
    assert chunks[0].strip() == "لحظة من فضلك." and "عندي موعد" in chunks[-1]

    agent.handle.thinking_fillers = False
    chunks = [c async for c in agent.llm_node(ctx, [], None)]
    assert len(chunks) == 1


async def test_voice_follows_caller_dialect(account, clinic_db):
    setup = await setup_doctor_agent(account)
    session = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"]})).json()
    switches = []
    agent = NexaVoiceAgent(CallHandle(call_id=UUID(session["session_id"]), tenant_id=UUID(account.tenant_id)),
                           tts_for_language=lambda lang, dialect: switches.append((lang, dialect)))
    await agent.run_turn("عايز احجز معاد دلوقتي")
    assert switches[-1] == ("ar", "eg")


def test_livekit_reached_directly_when_no_proxy_lists_it(monkeypatch):
    from nexa_voice.main import livekit_proxy

    for name in ("https_proxy", "http_proxy", "HTTP_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,livekit")
    assert livekit_proxy("ws://localhost:7880") is None
    assert livekit_proxy("ws://livekit:7880") is None
    assert livekit_proxy("wss://cloud.livekit.example") == "http://proxy.corp:3128"
    monkeypatch.delenv("HTTPS_PROXY")
    assert livekit_proxy("wss://cloud.livekit.example") is None


def test_call_capacity_counts_calls_not_cpu(monkeypatch):
    import nexa_voice.main as voice_main

    monkeypatch.setattr(voice_main, "MAX_CALLS", 4)
    worker = type("W", (), {"active_jobs": [object(), object()]})()
    assert voice_main.calls_load(worker) == 0.5
    worker.active_jobs = [object()] * 9
    assert voice_main.calls_load(worker) == 1.0
