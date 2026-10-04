"""Which voice speaks, and which words speech recognition should expect, for an agent."""

from __future__ import annotations

import re

from nexa.providers.tts.azure import DIALECT_VOICES, ENGLISH_VOICES, voice_for_dialect
from nexa.schemas.agent_definition import DIALECT_LABELS, AgentDefinition

PIPER_DEFAULTS = {"ar": "ar_JO-kareem-medium", "en": "en_US-amy-medium"}


# Piper voice ids look like "en_US-amy-medium"; another engine can't use them (left over from the default voice).
_PIPER_ID = re.compile(r"^[a-z]{2}_[A-Z]{2}-")


def resolve_voice(defn: AgentDefinition, language: str, dialect: str | None) -> tuple[str, str]:
    """Return (provider, voice_id) for the next reply."""
    v = defn.voice
    provider = "local" if v.provider == "piper" else v.provider
    if language == "en":
        if v.english_voice_id and not v.english_voice_id.startswith("default") and not (
                provider in ("neural", "elevenlabs", "azure") and _PIPER_ID.match(v.english_voice_id)):
            return provider, v.english_voice_id
        if provider == "azure":
            return provider, ENGLISH_VOICES[v.gender]
        if provider in ("elevenlabs", "neural"):
            return provider, v.voice_id  # multilingual voices speak both languages
        return provider, PIPER_DEFAULTS["en"]
    if provider == "azure":
        if v.match_caller_dialect and dialect:
            return provider, voice_for_dialect(dialect, v.gender)
        if v.voice_id.startswith("ar-"):
            return provider, v.voice_id
        response = defn.language_behavior.response_dialect
        return provider, voice_for_dialect(None if response == "match_caller" else response, v.gender)
    if provider == "local" and v.voice_id.startswith("default"):
        return provider, PIPER_DEFAULTS["ar"]
    return provider, v.voice_id


def stt_keywords(defn: AgentDefinition) -> list[str]:
    words = [defn.general.business_name, *defn.language_behavior.vocabulary]
    seen: list[str] = []
    for w in words:
        w = (w or "").strip()
        if w and w not in seen:
            seen.append(w)
    return seen[:200]


def azure_catalog() -> list[dict]:
    voices = []
    for dialect, (locale, female, male) in DIALECT_VOICES.items():
        if dialect in ("sd", "ar", "ae"):
            continue
        label = DIALECT_LABELS[dialect]
        voices.append({"id": female, "name": f"{label[0]} · female ({locale})", "dialect": dialect, "gender": "female"})
        voices.append({"id": male, "name": f"{label[0]} · male ({locale})", "dialect": dialect, "gender": "male"})
    voices += [{"id": ENGLISH_VOICES["female"], "name": "English · female", "dialect": None, "gender": "female"},
               {"id": ENGLISH_VOICES["male"], "name": "English · male", "dialect": None, "gender": "male"}]
    return voices
