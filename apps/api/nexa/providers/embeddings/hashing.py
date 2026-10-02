"""Offline embedding provider: hashed character n-grams over Arabic-folded text.

Not a neural model, but deterministic, dependency-free and good at lexical
matching across Arabic spelling variants. Used for tests and when no embedding
server is configured; swap for ``openai_compatible`` (e.g. bge-m3) in production.
"""

from __future__ import annotations

import hashlib
import math

from nexa.nlp.arabic import matching_key, strip_definite_article
from nexa.providers.embeddings.base import EmbeddingProvider


class HashingEmbeddings(EmbeddingProvider):
    name = "hashing"

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.model = f"hashing-ngram-{dimension}"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimension
        words = [strip_definite_article(w) for w in matching_key(text).split()]
        feats: list[str] = []
        for w in words:
            feats.append("w:" + w)
            padded = f"#{w}#"
            feats.extend("c:" + padded[i:i + 3] for i in range(max(1, len(padded) - 2)))
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dimension] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]
