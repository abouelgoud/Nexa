"""Fixed-window rate limiting backed by Redis, with an in-process fallback."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

from nexa.core.config import get_settings
from nexa.core.errors import RateLimited

_memory: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
_redis = None
_redis_failed = False


async def _redis_client():
    global _redis, _redis_failed
    if _redis is None and not _redis_failed:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=0.5)
            await _redis.ping()
        except Exception:  # noqa: BLE001 - fall back to memory when Redis is unavailable
            _redis, _redis_failed = None, True
    return _redis


async def hit(key: str, limit: int, window: int = 60) -> None:
    bucket = int(time.time() // window)
    full = f"rl:{key}:{bucket}"
    r = await _redis_client()
    if r is not None:
        try:
            count = await r.incr(full)
            if count == 1:
                await r.expire(full, window)
        except Exception:  # noqa: BLE001
            count = _mem_incr(full, bucket)
    else:
        count = _mem_incr(full, bucket)
    if count > limit:
        raise RateLimited("Too many requests. Please wait a moment and try again.")


def _mem_incr(key: str, bucket: int) -> int:
    b, c = _memory[key]
    c = c + 1 if b == bucket else 1
    _memory[key] = (bucket, c)
    return c


def limiter(scope: str, per_minute: int | None = None):
    async def _dep(request: Request) -> None:
        s = get_settings()
        if s.environment == "test":
            return
        ident = request.client.host if request.client else "unknown"
        await hit(f"{scope}:{ident}", per_minute or s.rate_limit_per_minute)

    return _dep
