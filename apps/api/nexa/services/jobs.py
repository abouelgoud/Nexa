"""Minimal Redis-backed job queue consumed by apps/worker (falls back to inline execution)."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexa.core.config import get_settings

QUEUE = "nexa:jobs"
log = logging.getLogger("nexa.jobs")


async def enqueue(db: AsyncSession, job: str, payload: dict[str, Any]) -> str:
    """Return 'queued' or 'inline'. Inline jobs run in the caller's transaction."""
    s = get_settings()
    if not s.jobs_inline:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(s.redis_url, socket_connect_timeout=0.5)
            await r.lpush(QUEUE, json.dumps({"job": job, "payload": payload}))
            await r.aclose()
            return "queued"
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable (%s); running job %s inline", exc, job)
    await run_job(db, job, payload)
    return "inline"


async def run_job(db: AsyncSession, job: str, payload: dict[str, Any]) -> None:
    if job == "ingest_document":
        from nexa.knowledge.service import ingest_document

        await ingest_document(db, UUID(payload["document_id"]))
    elif job == "retention_cleanup":
        from nexa.services.retention import cleanup

        await cleanup(db)
    else:
        raise ValueError(f"Unknown job {job}")
