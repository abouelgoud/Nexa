"""Small audio helpers shared by providers."""

from __future__ import annotations

import io
import wave


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return out.getvalue()


def wav_sample_rate(data: bytes, default: int = 22050) -> int:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getframerate()
    except (wave.Error, EOFError):
        return default


def to_wav_mono(data: bytes, target_rate: int = 16000) -> bytes:
    """Convert 16-bit PCM WAV (any rate/channels) to mono WAV at ``target_rate`` (linear interpolation)."""
    import array

    with wave.open(io.BytesIO(data)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit PCM WAV is supported")
    samples = array.array("h", frames)
    if channels > 1:
        samples = array.array("h", (sum(samples[i:i + channels]) // channels for i in range(0, len(samples), channels)))
    if rate != target_rate and len(samples) > 1:
        n_out = int(len(samples) * target_rate / rate)
        step = (len(samples) - 1) / max(1, n_out - 1)
        out = array.array("h", [0]) * n_out
        for i in range(n_out):
            pos = i * step
            j = int(pos)
            frac = pos - j
            nxt = samples[j + 1] if j + 1 < len(samples) else samples[j]
            out[i] = int(samples[j] + (nxt - samples[j]) * frac)
        samples = out
    return pcm16_to_wav(samples.tobytes(), target_rate)


def is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wav_pcm(data: bytes) -> tuple[bytes, int, int]:
    """(16-bit PCM frames, sample rate, channels) of a WAV file."""
    with wave.open(io.BytesIO(data)) as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()
