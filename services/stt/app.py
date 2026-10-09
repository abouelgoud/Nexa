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
import threading
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
# Picks the language first with a small model (~0.4 s on a CPU, Arabic vs English right on every test sentence), so
# the large model runs once with the language fixed. Letting the large model detect costs it a whole extra pass
# (5.3 s -> 10.6 s for a sentence on a 4-core CPU). Empty: let the large model detect.
LID_MODEL = os.getenv("WHISPER_LID_MODEL", "base")
# Biases decoding toward Arabic/English call vocabulary; callers can override per request.
DEFAULT_PROMPT = os.getenv("WHISPER_PROMPT", "مكالمة هاتفية. Phone call in Arabic and English.")

log = logging.getLogger("stt")
app = FastAPI(title="Nexa STT (Whisper)")
_model: WhisperModel | None = None
_mlx_repo: str | None = None  # set when the mlx engine is active
_ready = threading.Event()  # the model is loaded (it loads in the background; the first start downloads it)
_load_error: str | None = None
_load_lock = threading.Lock()
_lid: WhisperModel | None = None
_lid_lock = threading.Lock()


def _use_mlx() -> bool:
    if ENGINE == "mlx":
        return True
    return ENGINE == "auto" and sys.platform == "darwin" and platform.machine() == "arm64"


def model() -> WhisperModel:
    global _model
    with _load_lock:
        return _model or _load_faster_whisper()


def _load_faster_whisper() -> WhisperModel:
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


def best_allowed(probs, allowed: list[str]) -> str:
    """The most likely language among the allowed ones (Whisper's own pick may be e.g. Persian for short Arabic)."""
    scores = dict(probs or [])
    return max(allowed, key=lambda lang: scores.get(lang, 0.0))


def lid_model() -> WhisperModel:
    global _lid
    with _lid_lock:
        if _lid is None:
            _lid = WhisperModel(LID_MODEL, device="cpu", compute_type="int8", download_root=MODEL_DIR,
                                cpu_threads=CPU_THREADS)
        return _lid


def detect(samples) -> list[tuple[str, float]]:
    """Language probabilities for the speech in ``samples`` (16 kHz float), from the small model."""
    return lid_model().detect_language(audio=samples, vad_filter=True)[2]


def pick_language(samples, language: str | None, allowed: list[str] | None) -> str | None:
    """The language to recognise in, or None to let the large model detect it."""
    if language:
        return language
    if allowed and len(allowed) == 1:
        return allowed[0]
    if not LID_MODEL:
        return None
    probs = detect(samples)
    return best_allowed(probs, allowed) if allowed else max(probs, key=lambda p: p[1])[0]


def _samples(audio: bytes):
    return decode_audio(io.BytesIO(audio), sampling_rate=16000)


def _faster_whisper(audio: bytes, language, prompt, hotwords, allowed=None) -> dict:
    samples = _samples(audio)
    language = pick_language(samples, language, allowed)

    def run(lang):
        return model().transcribe(
            samples, language=lang or None, beam_size=BEAM, vad_filter=True,
            initial_prompt=prompt, condition_on_previous_text=False,
            # Words the caller is likely to say (doctor names, specialties) - improves accuracy on names.
            hotwords=hotwords or None,
            vad_parameters={"min_silence_duration_ms": 300},
        )

    segments, info = run(language)  # lazy: detection has run, transcription happens when iterated
    if not language and allowed and info.language not in allowed:
        segments, info = run(best_allowed(info.all_language_probs, allowed))
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
             "avg_logprob": round(s.avg_logprob, 3)} for s in segments]
    return {"segments": segs, "language": info.language,
            "language_probability": round(info.language_probability, 3), "duration": round(info.duration, 2)}


def _mlx(audio: bytes, language, prompt, hotwords, allowed=None) -> dict:
    import mlx_whisper

    samples = _samples(audio)
    language = pick_language(samples, language, allowed)

    def run(lang):
        # mlx-whisper has no hotwords; putting them in the prompt recovers most of their benefit.
        return mlx_whisper.transcribe(samples, path_or_hf_repo=_mlx_repo, language=lang or None,
                                      initial_prompt=f"{prompt} {hotwords}" if hotwords else prompt,
                                      condition_on_previous_text=False, verbose=None)

    out = run(language)
    if not language and allowed and out.get("language") not in allowed:
        out = run(allowed[0])  # mlx reports no per-language scores; use the agent's main language
    segs = [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": s["text"].strip(),
             "avg_logprob": round(float(s.get("avg_logprob", 0.0)), 3)}
            for s in out.get("segments", []) if s.get("no_speech_prob", 0) < 0.6]
    return {"segments": segs, "language": out.get("language") or language, "language_probability": None,
            "duration": round(len(samples) / 16000, 2)}


def _load_in_background() -> None:
    global _load_error
    try:
        load()
        if LID_MODEL:
            lid_model()
    except Exception as exc:  # noqa: BLE001 - reported by /health and to callers
        _load_error = f"{type(exc).__name__}: {exc}"
        log.exception("could not load the speech recognition model")
    finally:
        _ready.set()


@app.on_event("startup")
def _warm() -> None:
    # Load without blocking startup, so the service answers right away (with "loading") instead of refusing
    # connections while the model downloads on first start.
    if os.getenv("WHISPER_PRELOAD", "true") == "true":
        threading.Thread(target=_load_in_background, daemon=True, name="whisper-load").start()
    else:
        _ready.set()


@app.get("/health")
def health() -> dict:
    status = "error" if _load_error else "ok" if _ready.is_set() else "loading"
    return {"status": status, "model": MODEL, "engine": "mlx" if _mlx_repo else "faster-whisper",
            "device": "apple-gpu" if _mlx_repo else (_model.model.device if _model is not None else DEVICE),
            **({"error": _load_error} if _load_error else {})}


@app.post("/v1/audio/transcriptions")
def transcribe(file: UploadFile = File(...), model_name: str | None = Form(None, alias="model"),
               language: str | None = Form(None), prompt: str | None = Form(None),
               hotwords: str | None = Form(None), languages: str | None = Form(None),
               response_format: str = Form("json")) -> dict:
    # A plain (sync) endpoint: FastAPI runs it in a worker thread, so one transcription never blocks the others.
    global _mlx_repo
    if not _ready.wait(timeout=20):
        raise HTTPException(503, f"loading: the {MODEL} model is still loading (the first start downloads it)")
    if _load_error and not _mlx_repo and _model is None:
        raise HTTPException(503, f"model failed to load: {_load_error}")
    audio = file.file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    start = time.perf_counter()
    allowed = [lang.strip() for lang in (languages or "").split(",") if lang.strip()] or None
    args = (audio, language, prompt or DEFAULT_PROMPT, hotwords, allowed)
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
