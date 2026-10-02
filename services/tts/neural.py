"""Chatterbox Multilingual engine: natural speech and zero-shot voice cloning.

Voices are reference recordings stored in NEURAL_VOICE_DIR/<id>.wav; "default" uses the model's own voice.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger("tts.neural")
VOICE_DIR = Path(os.getenv("NEURAL_VOICE_DIR", "/models/neural-voices"))
DEVICE = os.getenv("NEURAL_DEVICE", "auto")
MAX_REFERENCE_SECONDS = 30
_model = None
_lock = threading.Lock()
SENTENCE_RE = re.compile(r"(?<=[.!?؟؛\n])\s+")


def available() -> bool:
    try:
        import chatterbox  # noqa: F401
    except ImportError:
        return False
    return True


def loaded() -> bool:
    return _model is not None


def engine():
    global _model
    with _lock:
        if _model is None:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            device = DEVICE
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            start = time.perf_counter()
            _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
            log.warning("loaded Chatterbox Multilingual on %s in %.1fs", device, time.perf_counter() - start)
        return _model


def list_voices() -> list[dict]:
    voices = [{"id": "default", "name": "Natural (default voice)"}]
    if VOICE_DIR.exists():
        voices += [{"id": p.stem, "name": p.stem, "cloned": True} for p in sorted(VOICE_DIR.glob("*.wav"))]
    return voices


def _to_wav(samples, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def save_reference(voice_id: str, data: bytes) -> dict:
    """Store a cleaned-up reference clip (mono, 24 kHz, max 30 s)."""
    import numpy as np
    import soundfile as sf

    try:
        audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as exc:  # noqa: BLE001 - libsndfile raises various errors
        raise ValueError("Unsupported audio. Upload WAV, FLAC, OGG or MP3.") from exc
    audio = audio.mean(axis=1)
    if rate != 24000:
        n = int(len(audio) * 24000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
        rate = 24000
    seconds = len(audio) / rate
    if seconds < 4:
        raise ValueError("The recording is too short (minimum 4 seconds; 10 to 30 seconds gives the closest match).")
    audio = audio[: MAX_REFERENCE_SECONDS * rate]
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio / peak * 0.9
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    (VOICE_DIR / f"{voice_id}.wav").write_bytes(_to_wav(audio, rate))
    info = {"seconds": round(min(seconds, MAX_REFERENCE_SECONDS), 1)}
    if seconds < 10:
        info["advice"] = "Short recording: a 10-30 second clip will sound closer to the speaker."
    return info


def synthesize(text: str, voice_id: str, language: str) -> tuple[bytes, int]:
    import numpy as np

    model = engine()
    reference = None
    if voice_id and voice_id != "default":
        path = VOICE_DIR / f"{voice_id}.wav"
        if not path.exists():
            raise KeyError(voice_id)
        reference = str(path)
    parts = [p for p in SENTENCE_RE.split(text.strip()) if p.strip()] or [text]
    chunks = []
    with _lock:
        for part in parts:
            wav = model.generate(part, language_id=language if language in ("ar", "en") else "ar",
                                 audio_prompt_path=reference, exaggeration=0.5, cfg_weight=0.5)
            chunks.append(wav.squeeze(0).detach().cpu().numpy())
            chunks.append(np.zeros(int(model.sr * 0.12), dtype="float32"))  # natural pause between sentences
    return _to_wav(np.concatenate(chunks), model.sr), model.sr
