"""Piper TTS via the bundled ``services/tts`` HTTP server (POST /synthesize -> WAV)."""

from __future__ import annotations

import time

import httpx

from nexa.providers.tts.base import SynthesisResult, TTSError, TTSProvider


class PiperHTTPTTS(TTSProvider):
    name = "piper"

    def __init__(self, base_url: str, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def synthesize(self, text, *, voice_id, language, speed=1.0) -> SynthesisResult:
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/synthesize",
                                        json={"text": text, "voice": voice_id, "language": language, "speed": speed})
        except httpx.HTTPError as exc:
            raise TTSError(f"Voice service unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise TTSError(f"Voice synthesis failed ({r.status_code}): {r.text[:200]}")
        return SynthesisResult(audio=r.content, mime_type=r.headers.get("content-type", "audio/wav"),
                               sample_rate=int(r.headers.get("x-sample-rate", 22050)),
                               latency_ms=(time.perf_counter() - start) * 1000, characters=len(text))

    async def health(self) -> bool:
        try:
            return (await self._client.get(f"{self.base_url}/health", timeout=3)).status_code == 200
        except httpx.HTTPError:
            return False
