from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class SynthesisResult:
    audio: bytes
    mime_type: str = "audio/wav"
    sample_rate: int = 22050
    latency_ms: float = 0.0
    characters: int = 0


class TTSError(RuntimeError):
    pass


class TTSProvider(ABC):
    name = "base"

    @abstractmethod
    async def synthesize(self, text: str, *, voice_id: str, language: str, speed: float = 1.0) -> SynthesisResult: ...

    async def stream(self, text: str, *, voice_id: str, language: str, speed: float = 1.0) -> AsyncIterator[bytes]:
        """Sentence-level streaming: synthesize each sentence as soon as it is available."""
        import re

        for sentence in [s for s in re.split(r"(?<=[.!?؟،,])\s+", text) if s.strip()]:
            yield (await self.synthesize(sentence, voice_id=voice_id, language=language, speed=speed)).audio

    async def health(self) -> bool:
        return True
