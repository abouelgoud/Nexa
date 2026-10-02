from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name = "base"
    model: str = ""
    dimension: int = 0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
