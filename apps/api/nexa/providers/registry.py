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
    """Test hook: replace a provider (``llm``, ``stt``, ``tts``, ``embeddings``, ``sip``)."""
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
    from nexa.providers.stt.whisper_http import WhisperHTTPSTT

    return WhisperHTTPSTT(s.stt_base_url, s.stt_model)


def get_tts() -> TTSProvider | None:
    if "tts" in _overrides:
        return _overrides["tts"]  # type: ignore[return-value]
    return _build_tts()


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
