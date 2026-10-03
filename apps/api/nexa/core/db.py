"""Async SQLAlchemy engine/session plus automatic tenant isolation.

Every ORM query issued through a session whose ``info["tenant_id"]`` is set is
automatically constrained to that tenant for all ``TenantScoped`` models. This
is a safety net on top of explicit filtering in the routes: a forgotten filter
cannot leak data across tenants.
"""

import asyncio
import weakref
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, with_loader_criteria

from nexa.core.config import get_settings

# One engine per event loop: asyncpg connections belong to the loop that opened them. The API has a single loop;
# the call worker in light mode runs each call on its own loop (thread), and sharing a pool there breaks.
_engines: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]" = (
    weakref.WeakKeyDictionary())
_no_loop: tuple[AsyncEngine, async_sessionmaker[AsyncSession]] | None = None


def current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _entry() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    global _no_loop
    loop = current_loop()
    entry = _engines.get(loop) if loop is not None else _no_loop
    if entry is None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10)
        entry = (engine, async_sessionmaker(engine, expire_on_commit=False))
        if loop is not None:
            _engines[loop] = entry
        else:
            _no_loop = entry
    return entry


def get_engine() -> AsyncEngine:
    return _entry()[0]


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return _entry()[1]


async def dispose_engine() -> None:
    """Close this event loop's connections (others are closed by their own loops)."""
    global _no_loop
    loop = current_loop()
    entry = _engines.pop(loop, None) if loop is not None else None
    for e in (entry, _no_loop):
        if e is not None:
            await e[0].dispose()
    _no_loop = None


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def bind_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    session.info["tenant_id"] = tenant_id
    session.sync_session.info["tenant_id"] = tenant_id


@event.listens_for(Session, "do_orm_execute")
def _tenant_isolation(execute_state):  # pragma: no cover - exercised via tests
    tenant_id = execute_state.session.info.get("tenant_id")
    if tenant_id is None or not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_tenant_filter"):
        return
    from nexa.models.base import TenantScoped

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )
