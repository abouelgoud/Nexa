"""LiveKit Agents adapters around Nexa's provider interfaces (STT/TTS stay swappable)."""

from __future__ import annotations

import io
import logging
import time
import uuid
import wave

from livekit import rtc
from livekit.agents import APIConnectionError, llm, stt, tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr

from nexa.core.observability import STT_LATENCY, TTS_LATENCY
from nexa.providers.audio import wav_pcm
from nexa.providers.stt.base import STTError, STTProvider
from nexa.providers.tts.base import TTSError, TTSProvider
from nexa.services.speech_cache import speech_chunks

log = logging.getLogger("nexa.voice")


def frames_to_wav(buffer: utils.AudioBuffer) -> bytes:
    frame = rtc.combine_audio_frames(buffer)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(frame.num_channels)
        w.setsampwidth(2)
        w.setframerate(frame.sample_rate)
        w.writeframes(frame.data.tobytes())
    return out.getvalue()


def resample_pcm16(pcm: bytes, rate: int, target: int, channels: int = 1) -> bytes:
    """Mono 16-bit PCM at ``target`` Hz (linear interpolation; voices are band-limited well below Nyquist)."""
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != target and len(x):
        n = int(round(len(x) * target / rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()


class NexaSTT(stt.STT):
    """Non-streaming STT; AgentSession pairs it with VAD to segment caller utterances."""

    def __init__(self, provider: STTProvider, prompt: str | None = None, keywords: list[str] | None = None,
                 languages: list[str] | None = None):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._provider = provider
        self._prompt = prompt
        self._keywords = keywords or []
        self._languages = languages
        self.last_language: str | None = None
        self.last_latency_ms: float | None = None

    async def _recognize_impl(self, buffer: utils.AudioBuffer, *, language: NotGivenOr[str] = NOT_GIVEN,
                              conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> stt.SpeechEvent:
        start = time.perf_counter()
        try:
            result = await self._provider.transcribe(frames_to_wav(buffer), mime_type="audio/wav",
                                                     language=language or None, prompt=self._prompt,
                                                     keywords=self._keywords, languages=self._languages)
        except STTError as exc:
            raise APIConnectionError(str(exc)) from exc
        STT_LATENCY.observe(time.perf_counter() - start)
        self.last_language = result.language
        self.last_latency_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info("timing: recognized %.1fs of speech in %.2fs", result.duration_seconds, self.last_latency_ms / 1000)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT, request_id=uuid.uuid4().hex,
            alternatives=[stt.SpeechData(language=result.language or "", text=result.text)],
        )


class NexaTTS(tts.TTS):
    def __init__(self, provider: TTSProvider, voice_id: str, language: str = "ar", speed: float = 1.0,
                 sample_rate: int = 22050):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=sample_rate, num_channels=1)
        self._provider = provider
        # Slow, high-quality voices are streamed phrase by phrase (see _run_phrases).
        self.phrase_streaming = getattr(provider, "name", "") == "neural"
        self.voice_id = voice_id
        self.language = language
        self.speed = speed

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> tts.ChunkedStream:
        return _NexaChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _NexaChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts: NexaTTS, input_text: str, conn_options: APIConnectOptions):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._nexa_tts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        t = self._nexa_tts
        if t.phrase_streaming:
            await self._run_phrases(output_emitter)
            return
        start = time.perf_counter()
        try:
            result = await t._provider.synthesize(self.input_text, voice_id=t.voice_id, language=t.language, speed=t.speed)
        except TTSError as exc:
            raise APIConnectionError(str(exc)) from exc
        TTS_LATENCY.observe(time.perf_counter() - start)
        output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=result.sample_rate, num_channels=1,
                                  mime_type="audio/wav")
        output_emitter.push(result.audio)
        output_emitter.flush()

    async def _run_phrases(self, output_emitter: tts.AudioEmitter) -> None:
        """Natural voices: render short phrases one after another and play each as soon as it is ready, so the
        caller hears the first words after one short phrase instead of after the whole sentence."""
        t = self._nexa_tts
        started = False
        for phrase in speech_chunks(self.input_text):
            start = time.perf_counter()
            try:
                result = await t._provider.synthesize(phrase, voice_id=t.voice_id, language=t.language, speed=t.speed)
            except TTSError as exc:
                raise APIConnectionError(str(exc)) from exc
            TTS_LATENCY.observe(time.perf_counter() - start)
            pcm, rate, channels = wav_pcm(result.audio)
            if channels != 1 or rate != t.sample_rate:  # the session plays at one fixed rate
                pcm = resample_pcm16(pcm, rate, t.sample_rate, channels)
            if not started:
                output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=t.sample_rate, num_channels=1,
                                          mime_type="audio/pcm")
                started = True
            output_emitter.push(pcm)
        if started:
            output_emitter.flush()


class RuntimeLLM(llm.LLM):
    """Marker LLM: AgentSession only generates replies when an LLM is configured. Replies actually come from
    NexaVoiceAgent.llm_node -> ConversationRuntime (workflow engine or the configured LLMProvider), so chat()
    is never called."""

    @property
    def model(self) -> str:
        return "nexa-runtime"

    @property
    def provider(self) -> str:
        return "nexa"

    def chat(self, **kwargs):  # pragma: no cover - llm_node is overridden
        raise NotImplementedError("Nexa replies are produced by the ConversationRuntime")
