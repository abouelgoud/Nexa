"""Voice library (cloned voices), voice catalog and previews for the agent builder."""

from __future__ import annotations

import base64
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import ServiceUnavailable, ValidationFailed
from nexa.models import Voice
from nexa.nlp.pronounce import speakable
from nexa.providers.registry import TTS_PROVIDERS, get_tts, tts_configured
from nexa.providers.tts.base import TTSError
from nexa.services.audit import audit
from nexa.services.voice_library import agents_using, create_voice, delete_voice, engine_available, get_voice
from nexa.services.voices import PIPER_DEFAULTS, azure_catalog

router = APIRouter(prefix="/voices", tags=["voices"])

PROVIDERS = {
    "local": {"label": "Standard (local, fast)", "kind": "local", "cloning": False,
              "note": "Runs on your servers. Clear but synthetic-sounding."},
    "neural": {"label": "Natural (self-hosted)", "kind": "local", "cloning": True,
               "note": "Human-like voices on your own GPU, including your own cloned voices."},
    "elevenlabs": {"label": "ElevenLabs (cloud)", "kind": "cloud", "cloning": True,
                   "note": "Most natural Arabic and English, including your own cloned voices."},
    "azure": {"label": "Azure Neural (cloud)", "kind": "cloud", "cloning": False,
              "note": "Native voices for each Arabic dialect; can match the caller's dialect automatically."},
}
SAMPLE_TEXT = {"ar": "أهلاً وسهلاً، معك عيادة الشفاء. كيف أقدر أساعدك اليوم؟",
               "en": "Hello, thanks for calling. How can I help you today?"}
_cache: dict[str, tuple[float, list[dict]]] = {}


async def _cached(key: str, loader) -> list[dict]:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    try:
        voices = await loader()
    except Exception:  # noqa: BLE001 - a provider being down must not break the page
        return []
    _cache[key] = (time.time(), voices)
    return voices


def _voice_out(v: Voice, used_by: list[str] | None = None) -> dict[str, Any]:
    return {"id": str(v.id), "name": v.name, "provider": v.provider, "provider_label": PROVIDERS[v.provider]["label"],
            "voice_id": v.provider_voice_id, "seconds": v.seconds, "created_at": v.created_at.isoformat(),
            "used_by": used_by or []}


async def _library(ctx: TenantContext) -> list[Voice]:
    return list(await ctx.db.scalars(select(Voice).where(Voice.tenant_id == ctx.tenant_id, Voice.deleted_at.is_(None))
                                     .order_by(Voice.created_at.desc())))


# ---------------------------------------------------------------------------------------------- library
@router.get("")
async def list_voices(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    voices = await _library(ctx)
    return {"voices": [_voice_out(v, await agents_using(ctx, v)) for v in voices],
            "engines": [{"key": k, "label": PROVIDERS[k]["label"], "available": await engine_available(k)}
                        for k in ("neural", "elevenlabs")]}


@router.post("", status_code=201)
async def upload_voice(name: str = Form(..., max_length=100), provider: str = Form("neural"),
                       consent: bool = Form(...), file: UploadFile = File(...),
                       ctx: TenantContext = Depends(require("write"))) -> dict[str, Any]:
    """Create a cloned voice from a recording (at least 4 s; 10-30 s of one clear speaker is best)."""
    if not consent:
        raise ValidationFailed("You must confirm you have the speaker's permission to clone this voice.")
    audio = await file.read(15_000_001)
    voice = await create_voice(ctx, name=name, provider=provider, audio=audio,
                               filename=file.filename or "recording", mime=file.content_type or "audio/wav")
    audit(ctx, "voice.create", "voice", voice.id, {"name": voice.name, "provider": provider})
    await ctx.db.commit()
    _cache.pop(provider, None)
    return _voice_out(voice)


class VoiceUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.patch("/{voice_id}")
async def rename_voice(voice_id: UUID, body: VoiceUpdate, ctx: TenantContext = Depends(require("write"))):
    voice = await get_voice(ctx, voice_id)
    voice.name = body.name.strip()
    audit(ctx, "voice.rename", "voice", voice.id, {"name": voice.name})
    await ctx.db.commit()
    return _voice_out(voice, await agents_using(ctx, voice))


@router.delete("/{voice_id}", status_code=204)
async def remove_voice(voice_id: UUID, ctx: TenantContext = Depends(require("write"))):
    voice = await get_voice(ctx, voice_id)
    await delete_voice(ctx, voice)
    audit(ctx, "voice.delete", "voice", voice.id, {"name": voice.name})
    await ctx.db.commit()
    _cache.pop(voice.provider, None)


@router.get("/{voice_id}/recording")
async def recording(voice_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> Response:
    voice = await ctx.db.scalar(select(Voice).options(undefer(Voice.recording)).where(
        Voice.id == voice_id, Voice.tenant_id == ctx.tenant_id, Voice.deleted_at.is_(None)))
    if voice is None:
        await get_voice(ctx, voice_id)  # raises NotFound
    return Response(voice.recording, media_type=voice.recording_mime)


# ---------------------------------------------------------------------------------------------- catalog
@router.get("/catalog")
async def catalog(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    library = await _library(ctx)
    providers = []
    for key in ("local", "neural", "elevenlabs", "azure"):
        info = dict(PROVIDERS[key], key=key, configured=tts_configured(key))
        mine = [{"id": v.provider_voice_id, "name": f"{v.name} (your voice)", "custom": True}
                for v in library if v.provider == key]
        voices: list[dict] = []
        if key == "local":
            voices = [{"id": PIPER_DEFAULTS["ar"], "name": "Arabic · male (Kareem)"},
                      {"id": PIPER_DEFAULTS["en"], "name": "English · female (Amy)"}]
        elif key == "azure":
            voices = azure_catalog()
        elif key == "neural":
            tts = get_tts("neural")
            info["configured"] = await tts.health() if tts else False
            voices = [{"id": "default", "name": "Natural (default voice)"}]
        elif info["configured"]:
            tts = get_tts(key)
            if tts is not None and hasattr(tts, "list_voices"):
                mine_ids = {m["id"] for m in mine}
                voices = [v for v in await _cached(key, tts.list_voices) if v["id"] not in mine_ids]
        info["voices"] = mine + voices
        providers.append(info)
    return {"providers": providers}


class PreviewIn(BaseModel):
    provider: str
    voice_id: str = Field(..., min_length=1, max_length=200)
    language: str = Field("ar", pattern="^(ar|en)$")
    text: str | None = Field(None, max_length=300)
    speed: float = Field(1.0, ge=0.5, le=2.0)


@router.post("/preview")
async def preview(body: PreviewIn, ctx: TenantContext = Depends(require("test"))) -> dict[str, Any]:
    if body.provider not in TTS_PROVIDERS:
        raise ValidationFailed("Unknown voice provider.")
    tts = get_tts(body.provider)
    if tts is None:
        raise ServiceUnavailable(f"The {PROVIDERS.get(body.provider, {}).get('label', body.provider)} voice is not "
                                 "configured on this server. Add its API key or start its service.")
    try:
        r = await tts.synthesize(speakable(body.text or SAMPLE_TEXT[body.language]), voice_id=body.voice_id,
                                 language=body.language, speed=body.speed)
    except TTSError as exc:
        raise ServiceUnavailable("The voice could not be generated right now.", details=str(exc)) from exc
    return {"mime_type": r.mime_type, "audio_base64": base64.b64encode(r.audio).decode(),
            "latency_ms": round(r.latency_ms, 1)}
