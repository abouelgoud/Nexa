"""Text-to-speech service: Piper voices (local, CPU friendly).

POST /synthesize {"text", "voice", "language", "speed"} -> audio/wav
GET  /voices, /health
Arabic text is diacritized (tashkeel) before synthesis for much better pronunciation.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import urllib.request
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from piper import PiperVoice, SynthesisConfig
from pydantic import BaseModel, Field

VOICE_DIR = Path(os.getenv("PIPER_VOICE_DIR", "/models/piper"))
VOICES = [v.strip() for v in os.getenv("PIPER_VOICES", "ar_JO-kareem-medium,en_US-amy-medium").split(",") if v.strip()]
DEFAULTS = {"ar": os.getenv("PIPER_DEFAULT_AR", "ar_JO-kareem-medium"), "en": os.getenv("PIPER_DEFAULT_EN", "en_US-amy-medium")}
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

log = logging.getLogger("tts")
app = FastAPI(title="Nexa TTS (Piper)")
_voices: dict[str, PiperVoice] = {}
_lock = threading.Lock()


def _voice_url(name: str, suffix: str) -> str:
    lang_region, speaker, quality = name.split("-")
    lang = lang_region.split("_")[0]
    return f"{HF}/{lang}/{lang_region}/{speaker}/{quality}/{name}{suffix}"


def ensure_voice(name: str) -> Path:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    model = VOICE_DIR / f"{name}.onnx"
    for suffix in (".onnx", ".onnx.json"):
        path = VOICE_DIR / f"{name}{suffix}"
        if not path.exists():
            log.warning("downloading voice %s%s", name, suffix)
            urllib.request.urlretrieve(_voice_url(name, suffix), path)  # noqa: S310 - fixed HTTPS host
    return model


def load(name: str) -> PiperVoice:
    with _lock:
        if name not in _voices:
            voice = PiperVoice.load(str(ensure_voice(name)))
            if name.startswith("ar"):
                voice.use_tashkeel = True
            _voices[name] = voice
        return _voices[name]


@app.on_event("startup")
def _warm() -> None:
    for name in VOICES:
        try:
            load(name)
        except Exception:  # noqa: BLE001 - keep serving other voices
            log.exception("could not load voice %s", name)


class SynthesisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str | None = None
    language: str = "ar"
    speed: float = Field(1.0, ge=0.5, le=2.0)


@app.get("/health")
def health() -> dict:
    return {"status": "ok" if _voices else "loading", "voices": list(_voices)}


@app.get("/voices")
def voices() -> dict:
    return {"loaded": list(_voices), "configured": VOICES, "defaults": DEFAULTS}


@app.post("/synthesize")
def synthesize(req: SynthesisRequest) -> Response:
    name = req.voice if req.voice and req.voice in VOICES + list(_voices) else DEFAULTS.get(req.language, VOICES[0])
    try:
        voice = load(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"voice {name} unavailable: {exc}") from exc
    start = time.perf_counter()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize_wav(req.text, wav, syn_config=SynthesisConfig(length_scale=1.0 / req.speed))
    return Response(buf.getvalue(), media_type="audio/wav", headers={
        "x-sample-rate": str(voice.config.sample_rate), "x-voice": name,
        "x-synthesis-ms": str(round((time.perf_counter() - start) * 1000, 1))})
