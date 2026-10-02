from __future__ import annotations

import httpx

from nexa.providers.embeddings.base import EmbeddingProvider


class OpenAICompatibleEmbeddings(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str, dimension: int, api_key: str = "not-needed"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension
        self._client = httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {api_key}"})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        r = await self._client.post(f"{self.base_url}/embeddings", json={"model": self.model, "input": texts})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
