"""The business's own cloned voices: create, rename, delete, and restore from the saved recording."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import undefer

from nexa.core.db import get_sessionmaker
from nexa.core.deps import TenantContext
from nexa.core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from nexa.models import Agent, AgentVersion, Voice
from nexa.providers.registry import get_tts, tts_configured
from nexa.providers.tts.base import TTSError

CLONE_PROVIDERS = ("neural", "elevenlabs")
MIN_BYTES = 20_000
MAX_BYTES = 15_000_000


async def saved_recording(provider_voice_id: str) -> bytes | None:
    """Original recording of a self-hosted cloned voice (used to restore it on the voice service)."""
    async with get_sessionmaker()() as db:
        voice = await db.scalar(select(Voice).options(undefer(Voice.recording)).where(
            Voice.provider == "neural", Voice.provider_voice_id == provider_voice_id, Voice.deleted_at.is_(None)))
        return voice.recording if voice else None


async def get_voice(ctx: TenantContext, voice_id: uuid.UUID) -> Voice:
    voice = await ctx.db.get(Voice, voice_id)
    if voice is None or voice.tenant_id != ctx.tenant_id or voice.deleted_at is not None:
        raise NotFound("Voice not found.")
    return voice


async def create_voice(ctx: TenantContext, *, name: str, provider: str, audio: bytes, filename: str, mime: str) -> Voice:
    name = name.strip()
    if not name:
        raise ValidationFailed("Give the voice a name.")
    if provider not in CLONE_PROVIDERS:
        raise ValidationFailed("Choose where to create the voice: Natural (self-hosted) or ElevenLabs.")
    if len(audio) < MIN_BYTES:
        raise ValidationFailed("The recording is too short. Upload at least 4 seconds (10 to 30 seconds is best).")
    if len(audio) > MAX_BYTES:
        raise ValidationFailed("The recording is too large (maximum 15 MB).")
    if await ctx.db.scalar(select(Voice).where(Voice.tenant_id == ctx.tenant_id, Voice.name == name,
                                               Voice.deleted_at.is_(None))):
        raise Conflict(f'You already have a voice named "{name}".')
    tts = get_tts(provider) if tts_configured(provider) else None
    if tts is None:
        raise ServiceUnavailable("This voice engine is not available on the server.")
    seconds = None
    try:
        if provider == "neural":
            provider_voice_id = f"t{ctx.tenant_id.hex[:8]}-{uuid.uuid4().hex[:10]}"
            result = await tts.clone(provider_voice_id, audio, filename)  # type: ignore[attr-defined]
            seconds = result.get("seconds")
        else:
            provider_voice_id = await tts.add_voice(name, audio, filename)  # type: ignore[attr-defined]
    except TTSError as exc:
        raise ServiceUnavailable(f"The voice could not be created: {exc}") from exc
    voice = Voice(tenant_id=ctx.tenant_id, name=name, provider=provider, provider_voice_id=provider_voice_id,
                  seconds=seconds, recording=audio, recording_mime=mime or "audio/wav", consent_by=ctx.user.id,
                  consent_at=datetime.now(UTC), created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(voice)
    await ctx.db.flush()
    return voice


def _uses(config: dict, provider_voice_id: str) -> bool:
    v = config.get("voice") or {}
    return provider_voice_id in (v.get("voice_id"), v.get("english_voice_id"))


async def agents_using(ctx: TenantContext, voice: Voice) -> list[str]:
    """Agents whose draft or live (published) version speaks with this voice."""
    agents = (await ctx.db.scalars(select(Agent).where(Agent.tenant_id == ctx.tenant_id,
                                                       Agent.deleted_at.is_(None)))).all()
    names = []
    for a in agents:
        live = await ctx.db.get(AgentVersion, a.published_version_id) if a.published_version_id else None
        if _uses(a.draft_config, voice.provider_voice_id) or (
                live and _uses(live.config.get("definition", {}), voice.provider_voice_id)):
            names.append(a.name)
    return names


async def delete_voice(ctx: TenantContext, voice: Voice) -> None:
    using = await agents_using(ctx, voice)
    if using:
        raise Conflict(f"This voice is used by: {', '.join(using)}. Choose another voice for them first.")
    tts = get_tts(voice.provider) if tts_configured(voice.provider) else None
    if tts is not None and hasattr(tts, "delete_voice"):
        try:
            await tts.delete_voice(voice.provider_voice_id)
        except TTSError:
            pass
    voice.deleted_at = datetime.now(UTC)
    voice.recording = b""
