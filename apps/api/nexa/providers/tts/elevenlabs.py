"""ElevenLabs text-to-speech: highly natural multilingual voices (incl. Arabic) and voice cloning."""

from __future__ import annotations

import time

import httpx

from nexa.providers.audio import pcm16_to_wav
from nexa.providers.tts.base import SynthesisResult, TTSError, TTSProvider

SAMPLE_RATE = 22050
# Models that accept an explicit language_code (helps with short or mixed Arabic/English sentences).
LANGUAGE_CODE_MODELS = {"eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_v3"}


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str, model_id: str = "eleven_multilingual_v2",
                 base_url: str = "https://api.elevenlabs.io", timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"xi-api-key": api_key}, transport=transport)

    async def synthesize(self, text, *, voice_id, language, speed=1.0) -> SynthesisResult:
        body: dict = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.15,
                               "use_speaker_boost": True, "speed": max(0.7, min(1.2, speed))},
        }
        if self.model_id in LANGUAGE_CODE_MODELS and language in ("ar", "en"):
            body["language_code"] = language
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/v1/text-to-speech/{voice_id}",
                                        params={"output_format": f"pcm_{SAMPLE_RATE}"}, json=body)
        except httpx.HTTPError as exc:
            raise TTSError(f"ElevenLabs unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise TTSError(f"ElevenLabs error {r.status_code}: {r.text[:200]}")
        return SynthesisResult(audio=pcm16_to_wav(r.content, SAMPLE_RATE), sample_rate=SAMPLE_RATE,
                               latency_ms=(time.perf_counter() - start) * 1000, characters=len(text))

    async def list_voices(self) -> list[dict]:
        r = await self._client.get(f"{self.base_url}/v1/voices")
        r.raise_for_status()
        return [{"id": v["voice_id"], "name": v.get("name", v["voice_id"]),
                 "labels": v.get("labels") or {}, "category": v.get("category")} for v in r.json().get("voices", [])]

    async def add_voice(self, name: str, audio: bytes, filename: str) -> str:
        """Instant voice clone in the ElevenLabs account; returns the new voice_id."""
        try:
            r = await self._client.post(f"{self.base_url}/v1/voices/add",
                                        data={"name": name, "remove_background_noise": "true"},
                                        files={"files": (filename, audio)}, timeout=120)
        except httpx.HTTPError as exc:
            raise TTSError(f"ElevenLabs unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise TTSError(f"ElevenLabs voice cloning failed ({r.status_code}): {r.text[:200]}")
        return r.json()["voice_id"]

    async def delete_voice(self, voice_id: str) -> None:
        r = await self._client.delete(f"{self.base_url}/v1/voices/{voice_id}")
        if r.status_code >= 400 and r.status_code != 404:
            raise TTSError(f"ElevenLabs voice deletion failed ({r.status_code})")

    async def health(self) -> bool:
        try:
            return (await self._client.get(f"{self.base_url}/v1/voices", timeout=5)).status_code == 200
        except httpx.HTTPError:
            return False
