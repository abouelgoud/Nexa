"""Self-hosted natural voices (Chatterbox Multilingual in services/tts with the neural engine).
Supports cloning a voice from a short consented recording, so each business can have its own voice."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import httpx

from nexa.providers.audio import wav_sample_rate
from nexa.providers.tts.base import SynthesisResult, TTSError, TTSProvider


class NeuralHTTPTTS(TTSProvider):
    name = "neural"

    def __init__(self, base_url: str, timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None,
                 restore: Callable[[str], Awaitable[bytes | None]] | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        # Returns the saved original recording of a cloned voice, to re-create it if the service lost it.
        self.restore = restore

    async def _post_synth(self, text: str, voice_id: str, language: str, speed: float) -> httpx.Response:
        try:
            return await self._client.post(f"{self.base_url}/synthesize", json={
                "text": text, "voice": voice_id, "language": language, "speed": speed, "engine": "neural"})
        except httpx.HTTPError as exc:
            raise TTSError(f"Neural voice service unreachable: {exc}") from exc

    async def synthesize(self, text, *, voice_id, language, speed=1.0) -> SynthesisResult:
        start = time.perf_counter()
        r = await self._post_synth(text, voice_id, language, speed)
        if r.status_code == 404 and self.restore is not None:
            recording = await self.restore(voice_id)
            if recording:
                await self.clone(voice_id, recording, "recording")
                r = await self._post_synth(text, voice_id, language, speed)
        if r.status_code >= 400:
            raise TTSError(f"Neural voice synthesis failed ({r.status_code}): {r.text[:200]}")
        return SynthesisResult(audio=r.content, sample_rate=wav_sample_rate(r.content, 24000),
                               latency_ms=(time.perf_counter() - start) * 1000, characters=len(text))

    async def clone(self, voice_id: str, audio: bytes, filename: str) -> dict:
        r = await self._client.post(f"{self.base_url}/voices/clone", data={"voice_id": voice_id},
                                    files={"file": (filename, audio)})
        if r.status_code >= 400:
            raise TTSError(f"Voice cloning failed: {r.text[:200]}")
        return r.json()

    async def delete_voice(self, voice_id: str) -> None:
        try:
            await self._client.delete(f"{self.base_url}/voices/{voice_id}")
        except httpx.HTTPError:
            pass  # the saved recording is deleted with the voice record anyway

    async def list_voices(self) -> list[dict]:
        r = await self._client.get(f"{self.base_url}/voices", timeout=5)
        r.raise_for_status()
        return r.json().get("neural", [])

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200 and "neural" in r.json().get("engines", [])
        except (httpx.HTTPError, ValueError):
            return False
