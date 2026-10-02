from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class TranscriptSegment:
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float | None = None


@dataclass
class TranscriptionResult:
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float = 0.0
    segments: list[TranscriptSegment] = field(default_factory=list)
    latency_ms: float = 0.0


class STTError(RuntimeError):
    pass


class STTProvider(ABC):
    name = "base"

    @abstractmethod
    async def transcribe(
        self, audio: bytes, *, mime_type: str = "audio/wav", language: str | None = None, prompt: str | None = None,
        keywords: list[str] | None = None,
    ) -> TranscriptionResult:
        """``keywords``: words the caller is likely to say (names, specialties) to bias recognition."""

    async def stream(self, chunks: AsyncIterator[bytes], *, language: str | None = None) -> AsyncIterator[TranscriptionResult]:
        """Default streaming: buffer and transcribe once. Real-time runtimes use VAD-segmented utterances."""
        buf = b"".join([c async for c in chunks])
        yield await self.transcribe(buf, language=language)

    async def health(self) -> bool:
        return True
