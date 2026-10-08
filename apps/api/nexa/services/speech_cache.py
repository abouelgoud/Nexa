"""Make natural (self-hosted) voices respond like a phone call.

A natural voice renders a whole sentence before any audio exists, so speech is produced in short phrases
(speech_chunks) that play as soon as each is ready, and an agent's fixed lines (greeting, workflow questions,
"one moment") are rendered ahead of time (warm_agent_voice) into the voice service's disk cache, so they play
instantly in every call. Both use the same phrase splitting, so the pre-rendered audio is exactly what calls ask for.
"""

from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID

from sqlalchemy import select

from nexa.core.db import get_sessionmaker
from nexa.models import Agent
from nexa.nlp.pronounce import parse_pronunciations, speakable
from nexa.providers.registry import get_tts
from nexa.schemas.agent_definition import AgentDefinition, render_greeting
from nexa.services.voices import resolve_voice

log = logging.getLogger("nexa.speech_cache")

FILLERS = {"ar": "لحظة من فضلك.", "en": "One moment, please."}
TEXT_KEYS = ("text", "prompt", "question", "revisit_question", "message")
_CLAUSE = re.compile(r"(?<=[.!?؟؛;:،,])\s+|\n+")
MAX_WORDS = 8


MIN_WORDS = 3
FIRST_WORDS = 4  # the caller hears the first phrase after it renders, so keep it short


def speech_chunks(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Split a reply into short spoken phrases: at punctuation (pieces under MIN_WORDS join the next one, which
    sounds more natural), then long clauses into balanced word groups."""
    pieces: list[str] = []
    pending: list[str] = []
    for clause in _CLAUSE.split(text.strip()):
        pending += clause.split()
        if len(pending) >= MIN_WORDS:
            pieces.append(" ".join(pending))
            pending = []
    if pending:
        if pieces and len(pieces[-1].split()) + len(pending) <= max_words:
            pieces[-1] += " " + " ".join(pending)
        else:
            pieces.append(" ".join(pending))
    if pieces and len(pieces[0].split()) > FIRST_WORDS + MIN_WORDS - 1:
        words = pieces[0].split()
        pieces[:1] = [" ".join(words[:FIRST_WORDS]), " ".join(words[FIRST_WORDS:])]
    out: list[str] = []
    for piece in pieces:
        words = piece.split()
        parts = -(-len(words) // max_words)  # ceil
        size = -(-len(words) // parts)
        out += [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
    return out


def fixed_phrases(defn: AgentDefinition, graph: dict | None, language: str) -> list[str]:
    """The agent's lines that never change (no {{variables}}), as spoken and split exactly as calls request them."""
    texts = [render_greeting(defn, language), FILLERS.get(language, FILLERS["ar"])]
    custom = parse_pronunciations(defn.voice.pronunciations)
    suffix = "_en" if language == "en" else ""
    for node in (graph or {}).get("nodes", []):
        cfg = node.get("config") or {}
        for key in TEXT_KEYS:
            value = cfg.get(f"{key}{suffix}") or (cfg.get(key) if language != "en" else None)
            if isinstance(value, str) and value.strip() and "{{" not in value:
                texts.append(value)
    seen: dict[str, None] = {}
    for text in texts:
        for chunk in speech_chunks(speakable(text, custom)):
            seen.setdefault(chunk)
    return list(seen)


async def _load(tenant_id: UUID, agent_id: UUID) -> tuple[AgentDefinition, dict | None] | None:
    from nexa.models import Workflow
    from nexa.services.workflows import graph_dict

    async with get_sessionmaker()() as db:
        agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id,
                                                    Agent.deleted_at.is_(None)))
        if agent is None:
            return None
        defn = AgentDefinition.model_validate(agent.draft_config)
        graph = None
        if defn.workflow_id:
            wf = await db.get(Workflow, defn.workflow_id)
            if wf is not None and wf.tenant_id == tenant_id:
                graph = await graph_dict(db, wf.id)
        return defn, graph


async def warm_agent_voice(tenant_id: UUID, agent_id: UUID) -> int:
    """Render the agent's fixed lines in its natural voice (fills the voice service's cache). Returns how many."""
    loaded = await _load(tenant_id, agent_id)
    if loaded is None:
        return 0
    defn, graph = loaded
    done = 0
    for language in [getattr(lang, "value", lang) for lang in defn.languages]:
        provider, voice_id = resolve_voice(defn, language, None)
        tts = get_tts(provider) if provider == "neural" else None
        if tts is None:
            continue
        for phrase in fixed_phrases(defn, graph, language):
            try:
                await tts.synthesize(phrase, voice_id=voice_id, language=language, speed=defn.voice.speed)
                done += 1
            except Exception as exc:  # noqa: BLE001 - only an optimisation; stop if the service is unavailable
                log.warning("pre-rendering stopped: %s", exc)
                return done
    if done:
        log.info("pre-rendered %d phrases for agent %s", done, agent_id)
    return done


_running: dict[UUID, asyncio.Task] = {}


def schedule_warm(tenant_id: UUID, agent_id: UUID) -> None:
    """Pre-render in the background after the agent changed; a newer change replaces a pending run."""
    previous = _running.pop(agent_id, None)
    if previous and not previous.done():
        previous.cancel()
    task = asyncio.get_running_loop().create_task(warm_agent_voice(tenant_id, agent_id))
    _running[agent_id] = task
    task.add_done_callback(lambda t: _running.pop(agent_id, None) if _running.get(agent_id) is t else None)


async def synthesize_phrased(tts, text: str, *, voice_id: str, language: str, speed: float):
    """One clip for a reply, rendered phrase by phrase (cache-friendly, as in live calls)."""
    from nexa.providers.audio import pcm16_to_wav, wav_pcm
    from nexa.providers.tts.base import SynthesisResult

    pcm, rate, latency = b"", 24000, 0.0
    for phrase in speech_chunks(text) or [text]:
        r = await tts.synthesize(phrase, voice_id=voice_id, language=language, speed=speed)
        frames, rate, _ = wav_pcm(r.audio)
        pcm += frames
        latency += r.latency_ms
    return SynthesisResult(audio=pcm16_to_wav(pcm, rate), sample_rate=rate, latency_ms=latency, characters=len(text))
