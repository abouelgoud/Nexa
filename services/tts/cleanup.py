"""Clean audio for natural voices.

A cloned voice copies everything in its reference recording - room noise, hum, hiss - into every sentence it says,
so references are cleaned before use: proper (anti-aliased) resampling, hum removal, noise reduction and trimmed
silence. Generated speech gets short fades and a trimmed tail, so phrases join without clicks or noise.
numpy + scipy only (both come with the neural engines).
"""

from __future__ import annotations

from math import gcd

import numpy as np

RATE = 24000
VERSION = "1"  # bump when the cleaning changes; stored references are re-cleaned once


def resample(audio: np.ndarray, rate: int, target: int = RATE) -> np.ndarray:
    """Band-limited resampling. (Plain interpolation folds the highs of 44.1/48 kHz recordings back in as hiss.)"""
    if rate == target or not len(audio):
        return audio.astype(np.float32)
    from scipy.signal import resample_poly

    g = gcd(int(rate), int(target))
    return resample_poly(audio, target // g, int(rate) // g).astype(np.float32)


def _highpass(audio: np.ndarray, rate: int, cutoff: float = 70.0) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt

    if len(audio) < rate // 10:
        return audio
    return sosfiltfilt(butter(4, cutoff, btype="highpass", fs=rate, output="sos"), audio).astype(np.float32)


def _denoise(audio: np.ndarray, rate: int) -> np.ndarray:
    """Spectral gating: learn the steady background from the quietest frames and turn it down (not off, which
    would sound watery)."""
    from scipy.signal import istft, stft

    nper = 1024 if rate >= 22050 else 512
    if len(audio) < nper * 8:
        return audio
    _, _, spec = stft(audio, fs=rate, nperseg=nper, noverlap=nper * 3 // 4)
    mag = np.abs(spec)
    energy = mag.mean(axis=0)
    quiet = mag[:, energy <= np.percentile(energy, 15)]
    noise = quiet.mean(axis=1, keepdims=True) + 1e-10
    gain = np.clip(1.0 - 1.5 * noise / (mag + 1e-10), 0.12, 1.0)
    # Smooth the gain across neighbouring frames so it doesn't flutter ("musical noise").
    kernel = np.ones(3) / 3
    gain = np.apply_along_axis(lambda g: np.convolve(g, kernel, mode="same"), 1, gain)
    _, out = istft(spec * gain, fs=rate, nperseg=nper, noverlap=nper * 3 // 4)
    return out[: len(audio)].astype(np.float32)


def _frame_db(audio: np.ndarray, rate: int, ms: int = 20) -> np.ndarray:
    size = max(1, rate * ms // 1000)
    n = len(audio) // size
    if n == 0:
        return np.array([-120.0])
    rms = np.sqrt((audio[: n * size].reshape(n, size) ** 2).mean(axis=1))
    return 20 * np.log10(rms + 1e-9)


def _trim(audio: np.ndarray, rate: int, below_peak_db: float, pad_s: float) -> np.ndarray:
    """Cut leading/trailing stretches quieter than ``below_peak_db`` under the loudest frame."""
    db = _frame_db(audio, rate)
    loud = np.where(db > db.max() - below_peak_db)[0]
    if not len(loud):
        return audio
    size = rate // 50
    pad = int(pad_s * rate)
    start = max(0, loud[0] * size - pad)
    end = min(len(audio), (loud[-1] + 1) * size + pad)
    return audio[start:end]


def _fade(audio: np.ndarray, rate: int, ms: float = 8.0) -> np.ndarray:
    n = min(len(audio) // 2, int(rate * ms / 1000))
    if n > 1:
        audio = audio.copy()
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        audio[:n] *= ramp
        audio[-n:] *= ramp[::-1]
    return audio


def clean_reference(audio: np.ndarray, rate: int) -> np.ndarray:
    """Mono float audio -> a clean 24 kHz reference clip, peak at 0.9."""
    audio = resample(np.asarray(audio, dtype=np.float32), rate)
    audio = _highpass(audio, RATE)
    audio = _denoise(audio, RATE)
    audio = _trim(audio, RATE, below_peak_db=45, pad_s=0.15)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    return _fade(audio / peak * 0.9 if peak > 0 else audio, RATE)


def polish(audio: np.ndarray, rate: int) -> np.ndarray:
    """Generated speech: drop the low-level tail some models leave after the last word, fade the edges so phrases
    join without clicks, and keep peaks below clipping."""
    audio = np.asarray(audio, dtype=np.float32)
    if not len(audio):
        return audio
    audio = _trim(audio, rate, below_peak_db=50, pad_s=0.06)
    peak = float(np.max(np.abs(audio)))
    if peak > 0.95:
        audio = audio * (0.95 / peak)
    return _fade(audio, rate, ms=6.0)
