"""Whisper over an OpenAI-compatible ``/v1/audio/transcriptions`` endpoint.

The bundled ``services/stt`` server (faster-whisper large-v3) implements this API,
so the same provider works with other compatible servers later.
"""

from __future__ import annotations

import re
import time

import httpx

from nexa.providers.stt.base import STTError, STTProvider, TranscriptionResult, TranscriptSegment

# services/stt uses this hint when the caller passes none.
SERVICE_DEFAULT_PROMPT = "مكالمة هاتفية. Phone call in Arabic and English."
_NOT_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _norm(text: str) -> str:
    return _NOT_WORD.sub(" ", text).strip().lower()


def echoes_hint(text: str, *hints: str | None) -> bool:
    """Whisper sometimes "hears" its own hint text (prompt / hotwords) in near-silence. Such a transcript is not
    something the caller said."""
    said = _norm(text)
    return bool(said) and any(said in _norm(h) for h in hints if h)


class WhisperHTTPSTT(STTProvider):
    name = "whisper"

    def __init__(self, base_url: str, model: str = "large-v3", timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None,
                         keywords=None, languages=None) -> TranscriptionResult:
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(
            mime_type.split(";")[0], "wav")
        data = {"model": self.model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        elif languages:
            data["languages"] = ",".join(languages)  # detect, but only among the agent's languages
        if prompt:
            data["prompt"] = prompt
        if keywords:
            # faster-whisper "hotwords": biases decoding toward these words (names, specialties, ...)
            data["hotwords"] = " ".join(k.strip() for k in keywords if k.strip())[:800]
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/audio/transcriptions", data=data,
                                        files={"file": (f"audio.{ext}", audio, mime_type)})
        except httpx.TimeoutException as exc:
            raise STTError(f"Speech recognition timed out after {self.timeout:.0f} s", "timeout") from exc
        except httpx.HTTPError as exc:
            raise STTError(f"Speech recognition service unreachable at {self.base_url}: {exc}", "unreachable") from exc
        if r.status_code >= 400:
            reason = "loading" if r.status_code == 503 else "failed"
            raise STTError(f"Speech recognition failed ({r.status_code}): {r.text[:200]}", reason)
        body = r.json()
        text = (body.get("text") or "").strip()
        if echoes_hint(text, prompt or SERVICE_DEFAULT_PROMPT, data.get("hotwords")):
            text, body["segments"] = "", []
        return TranscriptionResult(
            text=text,
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
