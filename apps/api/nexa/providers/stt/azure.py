"""Azure Speech speech-to-text (short audio REST). Uses a dialect-specific locale (ar-SA, ar-EG, ...)."""

from __future__ import annotations

import time

import httpx

from nexa.providers.audio import is_wav, to_wav_mono
from nexa.providers.stt.base import STTError, STTProvider, TranscriptionResult


class AzureSTT(STTProvider):
    name = "azure"

    def __init__(self, key: str, region: str, default_locale: str = "ar-SA", timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = (f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/"
                    "cognitiveservices/v1")
        self.default_locale = default_locale
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport,
                                         headers={"Ocp-Apim-Subscription-Key": key})

    async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None,
                         keywords=None, languages=None) -> TranscriptionResult:
        if not language and languages and len(languages) == 1:
            language = languages[0]
        if not is_wav(audio):
            raise STTError("Azure speech recognition needs WAV audio.")
        audio = to_wav_mono(audio, 16000)
        locale = language if language and "-" in language else ("en-US" if language == "en" else self.default_locale)
        start = time.perf_counter()
        try:
            r = await self._client.post(self.url, params={"language": locale, "format": "detailed"}, content=audio,
                                        headers={"Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000"})
        except httpx.HTTPError as exc:
            raise STTError(f"Azure Speech unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise STTError(f"Azure transcription failed ({r.status_code}): {r.text[:200]}")
        body = r.json()
        if body.get("RecognitionStatus") not in ("Success", "NoMatch", "InitialSilenceTimeout"):
            raise STTError(f"Azure recognition status: {body.get('RecognitionStatus')}")
        best = (body.get("NBest") or [{}])[0]
        return TranscriptionResult(text=(body.get("DisplayText") or "").strip(), language=locale.split("-")[0],
                                   language_probability=best.get("Confidence"),
                                   duration_seconds=(body.get("Duration") or 0) / 10_000_000,
                                   latency_ms=(time.perf_counter() - start) * 1000)
