"""Azure Neural text-to-speech: native voices for most Arabic dialects (Saudi, Egyptian, Gulf, Levantine,
Iraqi, Maghrebi, ...) so the agent can answer in the caller's own dialect."""

from __future__ import annotations

import time
from xml.sax.saxutils import escape

import httpx

from nexa.providers.tts.base import SynthesisResult, TTSError, TTSProvider

# dialect -> (locale, female voice, male voice)
DIALECT_VOICES: dict[str, tuple[str, str, str]] = {
    "sa": ("ar-SA", "ar-SA-ZariyahNeural", "ar-SA-HamedNeural"),
    "gulf": ("ar-AE", "ar-AE-FatimaNeural", "ar-AE-HamdanNeural"),
    "ae": ("ar-AE", "ar-AE-FatimaNeural", "ar-AE-HamdanNeural"),
    "kw": ("ar-KW", "ar-KW-NouraNeural", "ar-KW-FahedNeural"),
    "qa": ("ar-QA", "ar-QA-AmalNeural", "ar-QA-MoazNeural"),
    "bh": ("ar-BH", "ar-BH-LailaNeural", "ar-BH-AliNeural"),
    "om": ("ar-OM", "ar-OM-AyshaNeural", "ar-OM-AbdullahNeural"),
    "iq": ("ar-IQ", "ar-IQ-RanaNeural", "ar-IQ-BasselNeural"),
    "levant": ("ar-JO", "ar-JO-SanaNeural", "ar-JO-TaimNeural"),
    "eg": ("ar-EG", "ar-EG-SalmaNeural", "ar-EG-ShakirNeural"),
    "sd": ("ar-EG", "ar-EG-SalmaNeural", "ar-EG-ShakirNeural"),
    "ye": ("ar-YE", "ar-YE-MaryamNeural", "ar-YE-SalehNeural"),
    "ly": ("ar-LY", "ar-LY-ImanNeural", "ar-LY-OmarNeural"),
    "tn": ("ar-TN", "ar-TN-ReemNeural", "ar-TN-HediNeural"),
    "dz": ("ar-DZ", "ar-DZ-AminaNeural", "ar-DZ-IsmaelNeural"),
    "ma": ("ar-MA", "ar-MA-MounaNeural", "ar-MA-JamalNeural"),
    "ar": ("ar-SA", "ar-SA-ZariyahNeural", "ar-SA-HamedNeural"),
}
ENGLISH_VOICES = {"female": "en-US-AvaMultilingualNeural", "male": "en-US-AndrewMultilingualNeural"}
SAMPLE_RATE = 24000


def voice_for_dialect(dialect: str | None, gender: str) -> str:
    _, female, male = DIALECT_VOICES.get(dialect or "sa", DIALECT_VOICES["sa"])
    return female if gender == "female" else male


def locale_of(voice_id: str) -> str:
    parts = voice_id.split("-")
    return "-".join(parts[:2]) if len(parts) >= 3 else "ar-SA"


def build_ssml(text: str, voice_id: str, speed: float = 1.0) -> str:
    rate = f"{round((speed - 1) * 100):+d}%"
    return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale_of(voice_id)}'>"
            f"<voice name='{escape(voice_id)}'><prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>")


class AzureTTS(TTSProvider):
    name = "azure"

    def __init__(self, key: str, region: str, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self.region = region
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport, headers={
            "Ocp-Apim-Subscription-Key": key, "User-Agent": "nexa-voice"})

    async def synthesize(self, text, *, voice_id, language, speed=1.0) -> SynthesisResult:
        start = time.perf_counter()
        try:
            r = await self._client.post(self.url, content=build_ssml(text, voice_id, speed).encode(), headers={
                "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
        except httpx.HTTPError as exc:
            raise TTSError(f"Azure Speech unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise TTSError(f"Azure Speech error {r.status_code}: {r.text[:200]}")
        return SynthesisResult(audio=r.content, sample_rate=SAMPLE_RATE,
                               latency_ms=(time.perf_counter() - start) * 1000, characters=len(text))
