"""Async SQLAlchemy engine/session plus automatic tenant isolation.

Every ORM query issued through a session whose ``info["tenant_id"]`` is set is
automatically constrained to that tenant for all ``TenantScoped`` models. This
is a safety net on top of explicit filtering in the routes: a forgotten filter
cannot leak data across tenants.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, with_loader_criteria

from nexa.core.config import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


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
