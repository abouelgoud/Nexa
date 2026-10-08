"""Text-to-speech service.

Engines:
* piper  - fast, CPU friendly, clear but synthetic voices. Arabic text is vowelled as it is spoken (spoken_ar.py).
* neural - natural, human-like speech and zero-shot voice cloning from a consented recording, with
           Chatterbox Multilingual (MIT, default) or OmniVoice (NEURAL_MODEL=omnivoice; weights are
           non-commercial). Runs on an NVIDIA GPU, Apple Silicon (MPS) or CPU; see neural.py.

POST /synthesize {"text", "voice", "language", "speed", "engine"} -> audio/wav
POST /voices/clone (multipart: voice_id, file)   [neural]
GET  /voices, /health
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import threading
import time
import urllib.request
import wave
from collections import OrderedDict
from pathlib import Path

import neural
import spoken_ar
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

VOICE_DIR = Path(os.getenv("PIPER_VOICE_DIR", "/models/piper"))
VOICES = [v.strip() for v in os.getenv("PIPER_VOICES", "ar_JO-kareem-medium,en_US-amy-medium").split(",") if v.strip()]
DEFAULTS = {"ar": os.getenv("PIPER_DEFAULT_AR", "ar_JO-kareem-medium"), "en": os.getenv("PIPER_DEFAULT_EN", "en_US-amy-medium")}
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

ENGINES = [e.strip() for e in os.getenv("TTS_ENGINES", "piper,neural").split(",") if e.strip()]
if not neural.available():
    ENGINES = [e for e in ENGINES if e != "neural"]
try:
    from piper import PiperVoice, SynthesisConfig
except ImportError:  # neural-only image
    PiperVoice = SynthesisConfig = None  # type: ignore[assignment,misc]
    ENGINES = [e for e in ENGINES if e != "piper"]

log = logging.getLogger("tts")
app = FastAPI(title="Nexa TTS")
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
                voice.use_tashkeel = False  # vowelled by spoken_ar before synthesis
            _voices[name] = voice
        return _voices[name]


@app.on_event("startup")
def _warm() -> None:
    if "piper" in ENGINES:
        for name in VOICES:
            try:
                load(name)
            except Exception:  # noqa: BLE001 - keep serving other voices
                log.exception("could not load voice %s", name)
    if "neural" in ENGINES:
        for voice_id in neural.clean_stored_references():
            _forget_voice(voice_id)  # its cached phrases were rendered from the noisy recording
    preload = os.getenv("NEURAL_PRELOAD", "true")
    if "neural" in ENGINES and preload == "true":
        neural.engine()
    elif "neural" in ENGINES and preload == "background":
        # Start loading now without blocking startup, so the first natural-voice request doesn't wait for it.
        threading.Thread(target=neural.engine, daemon=True, name="neural-preload").start()


class SynthesisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str | None = None
    language: str = "ar"
    speed: float = Field(1.0, ge=0.5, le=2.0)
    engine: str = "piper"


@app.get("/health")
def health() -> dict:
    lazy = os.getenv("NEURAL_PRELOAD", "true") != "true"  # the natural voice model loads in the background / on use
    ready = (("piper" not in ENGINES) or bool(_voices)) and (("neural" not in ENGINES) or neural.loaded() or lazy)
    out = {"status": "ok" if ready else "loading", "engines": ENGINES, "voices": list(_voices)}
    if "neural" in ENGINES:
        out["neural"] = neural.info()
    return out


@app.get("/voices")
def voices() -> dict:
    return {"loaded": list(_voices), "configured": VOICES, "defaults": DEFAULTS, "engines": ENGINES,
            "neural": neural.list_voices() if "neural" in ENGINES else []}


# Natural voices take a while per sentence, and agents repeat many phrases (greeting, "one moment", questions),
# so recent results are kept and replayed instantly.
_cache: OrderedDict[tuple[str, str, str], tuple[bytes, int]] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = int(os.getenv("NEURAL_CACHE_SIZE", "200"))


# Also on disk, so pre-rendered phrases (an agent's greeting and questions) survive restarts.
DISK_CACHE = Path(os.getenv("NEURAL_CACHE_DIR", str(neural.VOICE_DIR / "cache")))
DISK_CACHE_FILES = int(os.getenv("NEURAL_CACHE_FILES", "5000"))


def _disk_path(key: tuple[str, str, str]) -> Path:
    digest = hashlib.sha1(f"{key[1]}|{key[2]}".encode()).hexdigest()[:20]
    return DISK_CACHE / f"{key[0]}__{digest}.wav"


def _disk_get(key: tuple[str, str, str]) -> tuple[bytes, int] | None:
    path = _disk_path(key)
    if not path.exists():
        return None
    data = path.read_bytes()
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
    path.touch()  # most recently used
    return data, rate


def _disk_put(key: tuple[str, str, str], audio: bytes) -> None:
    try:
        DISK_CACHE.mkdir(parents=True, exist_ok=True)
        _disk_path(key).write_bytes(audio)
        files = list(DISK_CACHE.glob("*.wav"))
        if len(files) > DISK_CACHE_FILES:
            for old in sorted(files, key=lambda f: f.stat().st_mtime)[: len(files) - DISK_CACHE_FILES]:
                old.unlink(missing_ok=True)
    except OSError:
        log.warning("could not write the voice cache", exc_info=True)


def _forget_voice(voice_id: str) -> None:
    with _cache_lock:
        for key in [k for k in _cache if k[0] == voice_id]:
            del _cache[key]
    for path in DISK_CACHE.glob(f"{voice_id}__*.wav"):
        path.unlink(missing_ok=True)


@app.post("/voices/clone")
async def clone_voice(voice_id: str = Form(...), file: UploadFile = File(...)) -> dict:
    if "neural" not in ENGINES:
        raise HTTPException(503, "The neural engine is not enabled on this server.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,60}", voice_id):
        raise HTTPException(400, "invalid voice id")
    _forget_voice(voice_id)
    try:
        info = neural.save_reference(voice_id, await file.read(15_000_000))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": voice_id, **info}


@app.delete("/voices/{voice_id}")
def delete_voice(voice_id: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,60}", voice_id):
        raise HTTPException(400, "invalid voice id")
    neural.delete_reference(voice_id)
    _forget_voice(voice_id)
    return {"deleted": voice_id}


@app.post("/synthesize")
def synthesize(req: SynthesisRequest) -> Response:
    if req.engine == "neural":
        if "neural" not in ENGINES:
            raise HTTPException(503, "The neural engine is not enabled on this server.")
        start = time.perf_counter()
        key = (req.voice or "default", req.language, req.text.strip())
        with _cache_lock:
            hit = _cache.get(key)
            if hit:
                _cache.move_to_end(key)
        if not hit:
            hit = _disk_get(key)
            if hit:
                with _cache_lock:
                    _cache[key] = hit
        if hit:
            audio, rate = hit
        else:
            try:
                audio, rate = neural.synthesize(req.text, key[0], req.language)
            except KeyError as exc:
                raise HTTPException(404, f"unknown voice {req.voice}") from exc
            with _cache_lock:
                _cache[key] = (audio, rate)
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
            _disk_put(key, audio)
        return Response(audio, media_type="audio/wav", headers={
            "x-sample-rate": str(rate), "x-voice": key[0], "x-engine": "neural", "x-cache": "hit" if hit else "miss",
            "x-synthesis-ms": str(round((time.perf_counter() - start) * 1000, 1))})
    if "piper" not in ENGINES:
        raise HTTPException(503, "The piper engine is not enabled on this server.")
    name = req.voice if req.voice and req.voice in VOICES + list(_voices) else DEFAULTS.get(req.language, VOICES[0])
    try:
        voice = load(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"voice {name} unavailable: {exc}") from exc
    start = time.perf_counter()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        text = spoken_ar.spoken(req.text) if name.startswith("ar") else req.text
        voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1.0 / req.speed))
    return Response(buf.getvalue(), media_type="audio/wav", headers={
        "x-sample-rate": str(voice.config.sample_rate), "x-voice": name,
        "x-synthesis-ms": str(round((time.perf_counter() - start) * 1000, 1))})
