"""Natural neural speech with zero-shot voice cloning.

Two models, chosen with NEURAL_MODEL:
* chatterbox (default) - Chatterbox Multilingual. MIT code and weights: safe for commercial use.
* omnivoice            - k2-fsa OmniVoice (the engine VoiceStudio uses). 600+ languages, strong cloning from
                         3-15 s. Code is Apache-2.0 but the released weights are CC-BY-NC: non-commercial only.

Both run on an NVIDIA GPU, Apple Silicon (Metal/MPS) or the CPU; NEURAL_DEVICE=auto picks the best one.
On a Mac, run this service natively (scripts/voice-mac.sh): Docker on macOS cannot use the Metal GPU.

Voices are reference recordings stored in NEURAL_VOICE_DIR/<id>.wav; "default" is the model's own voice.
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
MODEL = os.getenv("NEURAL_MODEL", "chatterbox").strip().lower()
MAX_REFERENCE_SECONDS = 30
_model = None
_device = None
_lock = threading.Lock()
SENTENCE_RE = re.compile(r"(?<=[.!?؟؛\n])\s+")


def available() -> bool:
    try:
        if MODEL == "omnivoice":
            import omnivoice  # noqa: F401
        else:
            import chatterbox  # noqa: F401
    except ImportError:
        return False
    return True


def loaded() -> bool:
    return _model is not None


def info() -> dict:
    return {"model": MODEL, "device": _device}


def best_device() -> str:
    import torch

    if DEVICE != "auto":
        return DEVICE
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"  # Apple Silicon GPU
    return "cpu"


def engine():
    global _model, _device
    with _lock:
        if _model is None:
            _device = best_device()
            start = time.perf_counter()
            _model = _OmniVoice(_device) if MODEL == "omnivoice" else _Chatterbox(_device)
            log.warning("loaded %s on %s in %.1fs", MODEL, _device, time.perf_counter() - start)
        return _model


class _Chatterbox:
    def __init__(self, device: str):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.tts = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self.sr = self.tts.sr

    def prepare(self, voice_id: str) -> None:
        pass  # Chatterbox reads the reference clip at generation time

    def generate(self, text: str, language: str, voice_id: str | None):
        reference = str(VOICE_DIR / f"{voice_id}.wav") if voice_id else None
        wav = self.tts.generate(text, language_id=language if language in ("ar", "en") else "ar",
                                audio_prompt_path=reference, exaggeration=0.5, cfg_weight=0.5)
        return wav.squeeze(0).detach().cpu().numpy()


class _OmniVoice:
    """Each voice keeps an encoded prompt (<id>.pt) beside its recording, so cloning work is done once."""

    PROMPT_SECONDS = 15  # OmniVoice clones best from a short passage; 3-15 s is its sweet spot

    def __init__(self, device: str):
        import torch
        from omnivoice import OmniVoice

        dtype = torch.float32 if device == "cpu" else torch.float16
        self.tts = OmniVoice.from_pretrained(os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice"),
                                             device_map=device, dtype=dtype)
        self.sr = self.tts.sampling_rate
        self._prompts: dict = {}

    def prepare(self, voice_id: str):
        """Encode the reference (transcribing it with Whisper first) and cache the prompt on disk."""
        import soundfile as sf
        import torch
        from omnivoice.models.omnivoice import VoiceClonePrompt

        cached = VOICE_DIR / f"{voice_id}.pt"
        if voice_id in self._prompts:
            return self._prompts[voice_id]
        if cached.exists():
            prompt = VoiceClonePrompt.load(str(cached))
        else:
            audio, rate = sf.read(VOICE_DIR / f"{voice_id}.wav", dtype="float32")
            audio = audio[: self.PROMPT_SECONDS * rate]
            if getattr(self.tts, "_asr_pipe", None) is None:
                self.tts.load_asr_model()  # Whisper large-v3-turbo, downloaded on first clone
            prompt = self.tts.create_voice_clone_prompt((torch.from_numpy(audio).unsqueeze(0), rate))
            prompt.save(str(cached))
        self._prompts[voice_id] = prompt
        return prompt

    def forget(self, voice_id: str) -> None:
        self._prompts.pop(voice_id, None)

    def generate(self, text: str, language: str, voice_id: str | None):
        if voice_id:
            return self.tts.generate(text=text, language=language, voice_clone_prompt=self.prepare(voice_id))[0]
        # No reference: a steady designed voice rather than a different random speaker on every turn.
        return self.tts.generate(text=text, language=language, instruct="female, middle-aged")[0]


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
    """Store a cleaned-up reference clip (mono, 24 kHz, max 30 s) and prepare it for the model."""
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
    (VOICE_DIR / f"{voice_id}.pt").unlink(missing_ok=True)
    (VOICE_DIR / f"{voice_id}.wav").write_bytes(_to_wav(audio, rate))
    model = engine()
    if hasattr(model, "forget"):
        model.forget(voice_id)
    with _lock:
        model.prepare(voice_id)
    result = {"seconds": round(min(seconds, MAX_REFERENCE_SECONDS), 1)}
    if seconds < 10:
        result["advice"] = "Short recording: a 10-30 second clip will sound closer to the speaker."
    return result


def delete_reference(voice_id: str) -> None:
    for suffix in (".wav", ".pt"):
        (VOICE_DIR / f"{voice_id}{suffix}").unlink(missing_ok=True)
    if _model is not None and hasattr(_model, "forget"):
        _model.forget(voice_id)


def synthesize(text: str, voice_id: str, language: str) -> tuple[bytes, int]:
    import numpy as np

    model = engine()
    reference = None
    if voice_id and voice_id != "default":
        if not (VOICE_DIR / f"{voice_id}.wav").exists():
            raise KeyError(voice_id)
        reference = voice_id
    parts = [p for p in SENTENCE_RE.split(text.strip()) if p.strip()] or [text]
    chunks = []
    with _lock:
        for part in parts:
            chunks.append(np.asarray(model.generate(part, language, reference), dtype="float32"))
            chunks.append(np.zeros(int(model.sr * 0.12), dtype="float32"))  # natural pause between sentences
    return _to_wav(np.concatenate(chunks), model.sr), model.sr
