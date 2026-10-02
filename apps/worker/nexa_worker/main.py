"""Background worker: consumes the Redis job queue (document ingestion) and runs periodic retention cleanup.

Shares the `nexa` package with the API so jobs use exactly the same code paths.
Run: python -m nexa_worker.main
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time

import redis.asyncio as aioredis

from nexa.core.config import get_settings
from nexa.core.db import dispose_engine, get_sessionmaker
from nexa.core.observability import setup_logging
from nexa.services.jobs import QUEUE, run_job

log = logging.getLogger("nexa.worker")
RETENTION_INTERVAL_SECONDS = 3600


async def process(raw: bytes) -> None:
    job = json.loads(raw)
    started = time.perf_counter()
    async with get_sessionmaker()() as db:
        try:
            await run_job(db, job["job"], job.get("payload", {}))
            await db.commit()
            log.info("job done", extra={"path": job["job"], "duration_ms": round((time.perf_counter() - started) * 1000)})
        except Exception:
            await db.rollback()
            log.exception("job failed: %s", job.get("job"))


async def retention_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        async with get_sessionmaker()() as db:
            try:
                await run_job(db, "retention_cleanup", {})
                await db.commit()
            except Exception:
                await db.rollback()
                log.exception("retention cleanup failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=RETENTION_INTERVAL_SECONDS)
        except TimeoutError:
            pass


async def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    r = aioredis.from_url(s.redis_url)
    retention = asyncio.create_task(retention_loop(stop))
    log.info("worker started, waiting for jobs on %s", QUEUE)
    while not stop.is_set():
        try:
            item = await r.brpop([QUEUE], timeout=2)
        except (ConnectionError, OSError, aioredis.ConnectionError):
            log.warning("redis unavailable, retrying")
            await asyncio.sleep(2)
            continue
        if item:
            await process(item[1])
    retention.cancel()
    await r.aclose()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
