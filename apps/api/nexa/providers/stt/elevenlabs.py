"""ElevenLabs Scribe speech-to-text: strong accuracy on Arabic dialects and Arabic/English mixing."""

from __future__ import annotations

import time

import httpx

from nexa.providers.stt.base import STTError, STTProvider, TranscriptionResult

ISO3_TO_1 = {"ara": "ar", "eng": "en"}


class ElevenLabsSTT(STTProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str, model_id: str = "scribe_v2", base_url: str = "https://api.elevenlabs.io",
                 timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None):
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"xi-api-key": api_key}, transport=transport)

    async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None,
                         keywords=None, languages=None) -> TranscriptionResult:
        if not language and languages and len(languages) == 1:
            language = languages[0]
        data: dict[str, str | list[str]] = {"model_id": self.model_id, "tag_audio_events": "false"}
        if language:
            data["language_code"] = language
        terms = [t.strip()[:50] for t in (keywords or []) if t.strip()][:100]
        if terms:
            data["keyterms"] = terms  # sent as repeated form fields
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/v1/speech-to-text", data=data,
                                        files={"file": ("audio", audio, mime_type)})
        except httpx.HTTPError as exc:
            raise STTError(f"ElevenLabs unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise STTError(f"ElevenLabs transcription failed ({r.status_code}): {r.text[:200]}")
        body = r.json()
        words = [w for w in body.get("words") or [] if w.get("type") == "word"]
        duration = max((w.get("end") or 0) for w in words) if words else 0.0
        lang = body.get("language_code")
        return TranscriptionResult(text=(body.get("text") or "").strip(), language=ISO3_TO_1.get(lang, lang),
                                   language_probability=body.get("language_probability"),
                                   duration_seconds=float(duration),
                                   latency_ms=(time.perf_counter() - start) * 1000)
