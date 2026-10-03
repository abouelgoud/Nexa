"""Calls in the light call worker run on separate event loops (threads); each must get its own connection pool."""

import asyncio
import threading

from sqlalchemy import text

from nexa.core.db import get_sessionmaker


def test_each_event_loop_gets_its_own_pool(database):
    results, errors = [], []

    async def call(n: int):
        maker = get_sessionmaker()
        for _ in range(5):  # several queries, overlapping with the other "call"
            async with maker() as db:
                results.append((n, id(maker), (await db.execute(text("SELECT 1"))).scalar()))
            await asyncio.sleep(0.01)

    def run(n: int):
        try:
            asyncio.run(call(n))
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 10 and all(r[2] == 1 for r in results)
    assert len({r[1] for r in results if r[0] == 0} | {r[1] for r in results if r[0] == 1}) == 2  # separate pools
