"""Whisper over an OpenAI-compatible ``/v1/audio/transcriptions`` endpoint.

The bundled ``services/stt`` server (faster-whisper large-v3) implements this API,
so the same provider works with other compatible servers later.
"""

from __future__ import annotations

import time

import httpx

from nexa.providers.stt.base import STTError, STTProvider, TranscriptionResult, TranscriptSegment


class WhisperHTTPSTT(STTProvider):
    name = "whisper"

    def __init__(self, base_url: str, model: str = "large-v3", timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None,
                         keywords=None) -> TranscriptionResult:
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(
            mime_type.split(";")[0], "wav")
        data = {"model": self.model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        if keywords:
            # faster-whisper "hotwords": biases decoding toward these words (names, specialties, ...)
            data["hotwords"] = " ".join(k.strip() for k in keywords if k.strip())[:800]
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/audio/transcriptions", data=data,
                                        files={"file": (f"audio.{ext}", audio, mime_type)})
        except httpx.HTTPError as exc:
            raise STTError(f"Speech recognition service unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise STTError(f"Speech recognition failed ({r.status_code}): {r.text[:200]}")
        body = r.json()
        return TranscriptionResult(
            text=(body.get("text") or "").strip(),
            language=body.get("language"),
            language_probability=body.get("language_probability"),
            duration_seconds=float(body.get("duration") or 0.0),
            segments=[TranscriptSegment(text=s.get("text", ""), start_ms=int(s.get("start", 0) * 1000),
                                        end_ms=int(s.get("end", 0) * 1000), confidence=s.get("avg_logprob"))
                      for s in body.get("segments") or []],
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    async def health(self) -> bool:
        try:
            r = await self._client.get(self.base_url.rsplit("/v1", 1)[0] + "/health", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False
