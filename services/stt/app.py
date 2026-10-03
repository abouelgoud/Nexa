"""Speech-to-text service: Whisper behind an OpenAI-compatible API.

Engines (WHISPER_ENGINE): faster-whisper (CPU / NVIDIA), or mlx (Apple Silicon GPU via mlx-whisper - several times
faster on a Mac). "auto" picks mlx on Apple Silicon when it is installed, falling back to faster-whisper if it fails.

POST /v1/audio/transcriptions  (multipart: file, model?, language?, prompt?, response_format?)
GET  /health
"""

from __future__ import annotations

import io
import logging
import os
import platform
import sys
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel, decode_audio

MODEL = os.getenv("WHISPER_MODEL", "large-v3")  # most accurate for Arabic; large-v3-turbo is ~3x faster
DEVICE = os.getenv("WHISPER_DEVICE", "auto")
COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "default")
# Greedy decoding (1) is as accurate as beam search (5) on our Arabic call tests and ~30% faster.
BEAM = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
ENGINE = os.getenv("WHISPER_ENGINE", "auto")
# faster-whisper uses 4 CPU threads unless told otherwise; use every core (recognition is the slowest step on a CPU).
CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "0")) or max(4, os.cpu_count() or 4)
MLX_MODELS = {"large-v3-turbo": "mlx-community/whisper-large-v3-turbo", "large-v3": "mlx-community/whisper-large-v3-mlx",
              "small": "mlx-community/whisper-small-mlx"}
MODEL_DIR = os.getenv("WHISPER_MODEL_DIR", "/models/whisper")
# Biases decoding toward Arabic/English call vocabulary; callers can override per request.
DEFAULT_PROMPT = os.getenv("WHISPER_PROMPT", "مكالمة هاتفية. Phone call in Arabic and English.")

log = logging.getLogger("stt")
app = FastAPI(title="Nexa STT (Whisper)")
_model: WhisperModel | None = None
_mlx_repo: str | None = None  # set when the mlx engine is active


def _use_mlx() -> bool:
    if ENGINE == "mlx":
        return True
    return ENGINE == "auto" and sys.platform == "darwin" and platform.machine() == "arm64"


def model() -> WhisperModel:
    global _model
    if _model is None:
        start = time.perf_counter()
        _model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE, download_root=MODEL_DIR,
                              cpu_threads=CPU_THREADS)
        log.warning("loaded whisper %s (faster-whisper, %s, %d threads) in %.1fs", MODEL, DEVICE, CPU_THREADS,
                    time.perf_counter() - start)
    return _model


def load() -> None:
    global _mlx_repo
    if _use_mlx():
        try:
            import mlx_whisper
            import numpy as np

            repo = MLX_MODELS.get(MODEL, MODEL)
            start = time.perf_counter()
            mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=repo, language="ar")
            _mlx_repo = repo
            log.warning("loaded whisper %s (mlx, Apple Silicon GPU) in %.1fs", repo, time.perf_counter() - start)
            return
        except Exception:  # noqa: BLE001 - not installed / unsupported: use faster-whisper
            log.exception("mlx-whisper unavailable, using faster-whisper on the CPU")
    model()


def _faster_whisper(audio: bytes, language, prompt, hotwords) -> dict:
    segments, info = model().transcribe(
        io.BytesIO(audio), language=language or None, beam_size=BEAM, vad_filter=True,
        initial_prompt=prompt, condition_on_previous_text=False,
        # Words the caller is likely to say (doctor names, specialties) - improves accuracy on names.
        hotwords=hotwords or None,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
             "avg_logprob": round(s.avg_logprob, 3)} for s in segments]
    return {"segments": segs, "language": info.language,
            "language_probability": round(info.language_probability, 3), "duration": round(info.duration, 2)}


def _mlx(audio: bytes, language, prompt, hotwords) -> dict:
    import mlx_whisper

    samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
    # mlx-whisper has no hotwords; putting them in the prompt recovers most of their benefit.
    out = mlx_whisper.transcribe(samples, path_or_hf_repo=_mlx_repo, language=language or None,
                                 initial_prompt=f"{prompt} {hotwords}" if hotwords else prompt,
                                 condition_on_previous_text=False, verbose=None)
    segs = [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": s["text"].strip(),
             "avg_logprob": round(float(s.get("avg_logprob", 0.0)), 3)}
            for s in out.get("segments", []) if s.get("no_speech_prob", 0) < 0.6]
    return {"segments": segs, "language": out.get("language") or language, "language_probability": None,
            "duration": round(len(samples) / 16000, 2)}


@app.on_event("startup")
def _warm() -> None:
    if os.getenv("WHISPER_PRELOAD", "true") == "true":
        load()


@app.get("/health")
def health() -> dict:
    return {"status": "ok" if (_model is not None or _mlx_repo) else "loading", "model": MODEL,
            "engine": "mlx" if _mlx_repo else "faster-whisper"}


@app.post("/v1/audio/transcriptions")
def transcribe(file: UploadFile = File(...), model_name: str | None = Form(None, alias="model"),
               language: str | None = Form(None), prompt: str | None = Form(None),
               hotwords: str | None = Form(None), response_format: str = Form("json")) -> dict:
    # A plain (sync) endpoint: FastAPI runs it in a worker thread, so one transcription never blocks the others.
    global _mlx_repo
    audio = file.file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    start = time.perf_counter()
    args = (audio, language, prompt or DEFAULT_PROMPT, hotwords)
    try:
        if _mlx_repo:
            try:
                out = _mlx(*args)
            except Exception:  # noqa: BLE001 - keep calls working on the CPU engine
                log.exception("mlx-whisper failed; switching to faster-whisper")
                _mlx_repo = None
                out = _faster_whisper(*args)
        else:
            out = _faster_whisper(*args)
    except Exception as exc:  # noqa: BLE001 - decoding errors from PyAV/ctranslate2
        raise HTTPException(400, f"could not decode audio: {exc}") from exc
    text = " ".join(s["text"] for s in out["segments"]).strip()
    if response_format == "text":
        return {"text": text}
    return {"text": text, **out, "processing_ms": round((time.perf_counter() - start) * 1000, 1)}
