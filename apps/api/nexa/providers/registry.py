"""Builds provider instances from settings. Swap implementations here, never in callers."""

from __future__ import annotations

from functools import lru_cache

from nexa.core.config import get_settings
from nexa.providers.embeddings.base import EmbeddingProvider
from nexa.providers.llm.base import LLMProvider
from nexa.providers.stt.base import STTProvider
from nexa.providers.telephony.base import SIPProvider
from nexa.providers.tts.base import TTSProvider

_overrides: dict[str, object] = {}


def override(kind: str, provider: object | None) -> None:
    """Test hook: replace a provider (``llm``, ``stt``, ``tts``, ``tts:<provider>``, ``embeddings``, ``sip``)."""
    if provider is None:
        _overrides.pop(kind, None)
    else:
        _overrides[kind] = provider


def get_llm() -> LLMProvider:
    if "llm" in _overrides:
        return _overrides["llm"]  # type: ignore[return-value]
    return _build_llm()


@lru_cache
def _build_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "scripted":
        from nexa.providers.llm.scripted import ScriptedLLM

        return ScriptedLLM()
    # local (vLLM), cloud and custom all speak the OpenAI-compatible protocol today.
    from nexa.providers.llm.openai_compatible import OpenAICompatibleLLM

    return OpenAICompatibleLLM(
        base_url=s.llm_base_url, model=s.llm_model, api_key=s.llm_api_key, timeout=s.llm_timeout_seconds,
        temperature=s.llm_temperature, max_tokens=s.llm_max_tokens, disable_thinking=s.llm_disable_thinking,
    )


def get_stt() -> STTProvider | None:
    if "stt" in _overrides:
        return _overrides["stt"]  # type: ignore[return-value]
    return _build_stt()


@lru_cache
def _build_stt() -> STTProvider | None:
    s = get_settings()
    if s.stt_provider == "none":
        return None
    if s.stt_provider == "elevenlabs" and s.elevenlabs_api_key:
        from nexa.providers.stt.elevenlabs import ElevenLabsSTT

        return ElevenLabsSTT(s.elevenlabs_api_key, s.elevenlabs_stt_model)
    if s.stt_provider == "azure" and s.azure_speech_key:
        from nexa.providers.stt.azure import AzureSTT

        return AzureSTT(s.azure_speech_key, s.azure_speech_region)
    from nexa.providers.stt.whisper_http import WhisperHTTPSTT

    return WhisperHTTPSTT(s.stt_base_url, s.stt_model)


TTS_PROVIDERS = ("local", "piper", "neural", "elevenlabs", "azure")


def get_tts(provider: str | None = None) -> TTSProvider | None:
    """TTS for an agent's voice provider (``local``/``piper``, ``neural``, ``elevenlabs``, ``azure``)."""
    key = f"tts:{provider}" if provider and provider not in ("local", "piper") else "tts"
    if key in _overrides:
        return _overrides[key]  # type: ignore[return-value]
    if provider in (None, "local", "piper"):
        return _build_tts()
    return _build_cloud_tts(provider)


def tts_configured(provider: str) -> bool:
    s = get_settings()
    if f"tts:{provider}" in _overrides or (provider in ("local", "piper") and "tts" in _overrides):
        return True
    return {"local": s.tts_provider != "none", "piper": s.tts_provider != "none", "neural": True,
            "elevenlabs": bool(s.elevenlabs_api_key), "azure": bool(s.azure_speech_key)}.get(provider, False)


@lru_cache(maxsize=8)
def _build_cloud_tts(provider: str) -> TTSProvider | None:
    s = get_settings()
    if provider == "elevenlabs" and s.elevenlabs_api_key:
        from nexa.providers.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(s.elevenlabs_api_key, s.elevenlabs_tts_model)
    if provider == "azure" and s.azure_speech_key:
        from nexa.providers.tts.azure import AzureTTS

        return AzureTTS(s.azure_speech_key, s.azure_speech_region)
    if provider == "neural":
        from nexa.providers.tts.neural_http import NeuralHTTPTTS

        return NeuralHTTPTTS(s.neural_tts_base_url)
    return None


@lru_cache
def _build_tts() -> TTSProvider | None:
    s = get_settings()
    if s.tts_provider == "none":
        return None
    from nexa.providers.tts.piper_http import PiperHTTPTTS

    return PiperHTTPTTS(s.tts_base_url)


def get_embeddings() -> EmbeddingProvider:
    if "embeddings" in _overrides:
        return _overrides["embeddings"]  # type: ignore[return-value]
    return _build_embeddings()


@lru_cache
def _build_embeddings() -> EmbeddingProvider:
    s = get_settings()
    if s.embedding_provider == "openai_compatible":
        from nexa.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddings

        return OpenAICompatibleEmbeddings(s.embedding_base_url, s.embedding_model, s.embedding_dim)
    from nexa.providers.embeddings.hashing import HashingEmbeddings

    return HashingEmbeddings(s.embedding_dim)


def get_sip() -> SIPProvider | None:
    if "sip" in _overrides:
        return _overrides["sip"]  # type: ignore[return-value]
    return _build_sip()


@lru_cache
def _build_sip() -> SIPProvider | None:
    s = get_settings()
    if s.sip_provider == "none":
        return None
    from nexa.providers.telephony.livekit_sip import LiveKitSIPProvider

    return LiveKitSIPProvider(s.livekit_api_url, s.livekit_api_key, s.livekit_api_secret)
