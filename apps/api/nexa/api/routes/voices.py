"""Voice catalog, previews and voice cloning for the agent builder."""

from __future__ import annotations

import base64
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import ServiceUnavailable, ValidationFailed
from nexa.providers.registry import TTS_PROVIDERS, get_tts, tts_configured
from nexa.providers.tts.base import TTSError
from nexa.services.audit import audit
from nexa.services.voices import PIPER_DEFAULTS, azure_catalog

router = APIRouter(prefix="/voices", tags=["voices"])

PROVIDERS = {
    "local": {"label": "Standard (local, fast)", "kind": "local", "cloning": False,
              "note": "Runs on your servers. Clear but synthetic-sounding."},
    "neural": {"label": "Natural (self-hosted)", "kind": "local", "cloning": True,
               "note": "Human-like voices on your own GPU, including a cloned voice of your choice."},
    "elevenlabs": {"label": "ElevenLabs (cloud)", "kind": "cloud", "cloning": True,
                   "note": "Most natural Arabic and English. Clone voices in your ElevenLabs account."},
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


@router.get("/catalog")
async def catalog(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    providers = []
    for key in ("local", "neural", "elevenlabs", "azure"):
        info = dict(PROVIDERS[key], key=key, configured=tts_configured(key))
        voices: list[dict] = []
        if key == "local":
            voices = [{"id": PIPER_DEFAULTS["ar"], "name": "Arabic · male (Kareem)"},
                      {"id": PIPER_DEFAULTS["en"], "name": "English · female (Amy)"}]
        elif key == "azure":
            voices = azure_catalog()
        elif info["configured"]:
            tts = get_tts(key)
            if tts is not None and hasattr(tts, "list_voices"):
                voices = await _cached(key, tts.list_voices)
            if key == "neural":
                prefix = f"t{ctx.tenant_id.hex[:8]}-"
                voices = [v if v["id"] == "default" else
                          {**v, "name": v["id"].removeprefix(prefix).replace("-", " ").title() + " (your voice)"}
                          for v in voices if v["id"] == "default" or v["id"].startswith(prefix)]
                info["configured"] = await tts.health() if tts else False
        info["voices"] = voices
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
        r = await tts.synthesize(body.text or SAMPLE_TEXT[body.language], voice_id=body.voice_id,
                                 language=body.language, speed=body.speed)
    except TTSError as exc:
        raise ServiceUnavailable("The voice could not be generated right now.", details=str(exc)) from exc
    return {"mime_type": r.mime_type, "audio_base64": base64.b64encode(r.audio).decode(),
            "latency_ms": round(r.latency_ms, 1)}


@router.post("/clone", status_code=201)
async def clone(name: str = Form(..., min_length=1, max_length=60), consent: bool = Form(...),
                file: UploadFile = File(...), ctx: TenantContext = Depends(require("write"))) -> dict[str, Any]:
    """Create a natural self-hosted voice from a 10-30 second recording (neural engine)."""
    if not consent:
        raise ValidationFailed("You must confirm you have the speaker's permission to clone this voice.")
    tts = get_tts("neural")
    if tts is None or not hasattr(tts, "clone"):
        raise ServiceUnavailable("The natural voice service is not available.")
    audio = await file.read(15_000_000)
    if len(audio) < 20_000:
        raise ValidationFailed("The recording is too short. Upload 10 to 30 seconds of clear speech.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "voice"
    voice_id = f"t{ctx.tenant_id.hex[:8]}-{slug}"
    try:
        result = await tts.clone(voice_id, audio, file.filename or "voice.wav")
    except TTSError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    audit(ctx, "voice.clone", "voice", None, {"voice_id": voice_id, "name": name})
    await ctx.db.commit()
    _cache.pop("neural", None)
    return {"id": voice_id, "name": name, **{k: v for k, v in result.items() if k != "id"}}
