"""Speech-to-text service: faster-whisper (Whisper large-v3 by default) behind an OpenAI-compatible API.

POST /v1/audio/transcriptions  (multipart: file, model?, language?, prompt?, response_format?)
GET  /health
"""

from __future__ import annotations

import io
import logging
import os
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel

MODEL = os.getenv("WHISPER_MODEL", "large-v3")  # most accurate for Arabic; large-v3-turbo is ~3x faster
DEVICE = os.getenv("WHISPER_DEVICE", "auto")
COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "default")
BEAM = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
MODEL_DIR = os.getenv("WHISPER_MODEL_DIR", "/models/whisper")
# Biases decoding toward Arabic/English call vocabulary; callers can override per request.
DEFAULT_PROMPT = os.getenv("WHISPER_PROMPT", "مكالمة هاتفية. Phone call in Arabic and English.")

log = logging.getLogger("stt")
app = FastAPI(title="Nexa STT (Whisper)")
_model: WhisperModel | None = None


def model() -> WhisperModel:
    global _model
    if _model is None:
        start = time.perf_counter()
        _model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE, download_root=MODEL_DIR)
        log.warning("loaded whisper %s on %s in %.1fs", MODEL, DEVICE, time.perf_counter() - start)
    return _model


@app.on_event("startup")
def _warm() -> None:
    if os.getenv("WHISPER_PRELOAD", "true") == "true":
        model()


@app.get("/health")
def health() -> dict:
    return {"status": "ok" if _model is not None else "loading", "model": MODEL}


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...), model_name: str | None = Form(None, alias="model"),
                     language: str | None = Form(None), prompt: str | None = Form(None),
                     hotwords: str | None = Form(None), response_format: str = Form("json")) -> dict:
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    start = time.perf_counter()
    try:
        segments, info = model().transcribe(
            io.BytesIO(audio), language=language or None, beam_size=BEAM, vad_filter=True,
            initial_prompt=prompt or DEFAULT_PROMPT, condition_on_previous_text=False,
            # Words the caller is likely to say (doctor names, specialties) - improves accuracy on names.
            hotwords=hotwords or None,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        segs = list(segments)
    except Exception as exc:  # noqa: BLE001 - decoding errors from PyAV/ctranslate2
        raise HTTPException(400, f"could not decode audio: {exc}") from exc
    text = " ".join(s.text.strip() for s in segs).strip()
    if response_format == "text":
        return {"text": text}
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 2),
        "processing_ms": round((time.perf_counter() - start) * 1000, 1),
        "segments": [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                      "avg_logprob": round(s.avg_logprob, 3)} for s in segs],
    }
