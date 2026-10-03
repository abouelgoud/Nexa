"""Permission-checked query builder for customer PostgreSQL databases.

LLM -> structured tool -> permission validator -> query builder -> database.
Identifiers come only from validated tool configuration and are checked against
the live schema; values are always bound parameters.
"""

from __future__ import annotations

import asyncio
import operator
import time
import uuid
import weakref
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import column, delete, insert, select, table, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nexa.core.config import get_settings
from nexa.schemas.tool_definition import DatabaseToolConfig
from nexa.tools.network import ensure_public_host
from nexa.tools.permissions import TablePermissions
from nexa.tools.templating import render


class DatabaseToolError(Exception):
    def __init__(self, message: str, code: str = "database_error"):
        super().__init__(message)
        self.message = message
        self.code = code


COMPARATORS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "lte": operator.le, "gt": operator.gt,
               "gte": operator.ge}
# integration id -> (url, engine), per event loop (asyncpg connections belong to the loop that opened them).
_loop_engines: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, tuple[str, AsyncEngine]]] = (
    weakref.WeakKeyDictionary())
_columns: dict[tuple[str, str, str], dict[str, str]] = {}


def build_url(config: dict[str, Any], secrets: dict[str, Any]) -> str:
    if secrets.get("dsn"):
        dsn: str = secrets["dsn"]
        for prefix in ("postgresql://", "postgres://"):
            if dsn.startswith(prefix):
                return "postgresql+asyncpg://" + dsn[len(prefix):]
        return dsn
    user = quote(config.get("username", ""), safe="")
    pwd = quote(secrets.get("password", ""), safe="")
    host = config.get("host", "localhost")
    port = int(config.get("port", 5432))
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{config.get('database', '')}"


async def get_engine(integration_id: str, config: dict[str, Any], secrets: dict[str, Any]) -> AsyncEngine:
    url = build_url(config, secrets)
    _engines = _loop_engines.setdefault(asyncio.get_running_loop(), {})
    cached = _engines.get(integration_id)
    if cached and cached[0] == url:
        return cached[1]
    if config.get("host"):
        await ensure_public_host(config["host"])
    connect_args: dict[str, Any] = {"timeout": get_settings().integration_timeout_seconds,
                                    "server_settings": {"statement_timeout": "8000", "application_name": "nexa-agent"}}
    if config.get("ssl"):
        connect_args["ssl"] = "require"
    engine = create_async_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True, connect_args=connect_args)
    if cached:
        await cached[1].dispose()
    _engines[integration_id] = (url, engine)
    return engine


async def dispose_all() -> None:
    _engines = _loop_engines.pop(asyncio.get_running_loop(), {})
    for _, engine in _engines.values():
        await engine.dispose()
    _engines.clear()
    _columns.clear()


async def table_columns(engine: AsyncEngine, cache_key: str, schema: str, tbl: str) -> dict[str, str]:
    key = (cache_key, schema, tbl)
    if key not in _columns:
        async with engine.connect() as conn:
            rows = (await conn.execute(
                text("SELECT column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema = :s AND table_name = :t"), {"s": schema, "t": tbl})).all()
        if not rows:
            raise DatabaseToolError(f'The table "{schema}.{tbl}" was not found in the connected database.',
                                    "table_not_found")
        _columns[key] = {r[0]: r[1] for r in rows}
    return _columns[key]


async def list_tables(engine: AsyncEngine) -> list[dict[str, Any]]:
    """Schema discovery for the no-code permission editor."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY table_schema, table_name, "
            "ordinal_position"))).all()
    tables: dict[str, dict[str, Any]] = {}
    for s, t, c, d in rows:
        tables.setdefault(f"{s}.{t}", {"schema": s, "table": t, "columns": []})["columns"].append({"name": c, "type": d})
    return list(tables.values())


def coerce(value: Any, data_type: str) -> Any:
    if value is None:
        return None
    try:
        if data_type in ("integer", "bigint", "smallint"):
            return int(value)
        if data_type in ("numeric", "real", "double precision"):
            return Decimal(str(value))
        if data_type == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
        if data_type == "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        if data_type.startswith("timestamp"):
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if data_type.startswith("time"):
            return value if isinstance(value, dtime) else dtime.fromisoformat(str(value))
        if data_type == "uuid":
            return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise DatabaseToolError(f'The value "{value}" is not a valid {data_type}.', "invalid_value") from exc
    return str(value) if not isinstance(value, (list, dict)) else value


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, (date, dtime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


async def execute_database_tool(
    cfg: DatabaseToolConfig, args: dict[str, Any], *, integration_id: str, integration_config: dict[str, Any],
    secrets: dict[str, Any],
) -> dict[str, Any]:
    perms = TablePermissions(integration_config.get("permissions", {}), cfg.db_schema, cfg.table)
    engine = await get_engine(integration_id, integration_config, secrets)
    cols = await table_columns(engine, integration_id, cfg.db_schema, cfg.table)

    def check_col(name: str) -> str:
        if name not in cols:
            raise DatabaseToolError(f'The field "{name}" does not exist in "{cfg.table}".', "field_not_found")
        return name

    return_fields = [check_col(f) for f in (cfg.return_fields or perms.readable_fields()) if perms.readable(f)]
    if not return_fields:
        raise DatabaseToolError("No readable fields are configured for this action.", "no_fields")
    t = table(cfg.table, *[column(c) for c in cols], schema=cfg.db_schema)

    conditions = []
    for flt in cfg.filters:
        if flt.op in ("is_null", "not_null"):
            raw: Any = True
        elif flt.arg is not None:
            raw = args.get(flt.arg)
            if raw in (None, ""):
                if flt.optional:
                    continue
                raise DatabaseToolError(f'Missing information: "{flt.arg}".', "missing_argument")
        else:
            raw = flt.value
        c = t.c[check_col(flt.field)]
        dtype = cols[flt.field]
        if flt.op == "in":
            values = raw if isinstance(raw, list) else [raw]
            conditions.append(c.in_([coerce(v, dtype) for v in values]))
            continue
        if flt.op in ("like", "ilike"):
            pattern = f"%{str(raw).replace('%', '').replace('_', '')}%"
            conditions.append(c.ilike(pattern) if flt.op == "ilike" else c.like(pattern))
            continue
        if flt.op == "is_null":
            conditions.append(c.is_(None))
            continue
        if flt.op == "not_null":
            conditions.append(c.is_not(None))
            continue
        conditions.append(COMPARATORS[flt.op](c, coerce(raw, dtype)))

    values: dict[str, Any] = {}
    for field, template in cfg.values.items():
        rendered = render(template, args)
        if rendered in (None, ""):
            raise DatabaseToolError(f'Missing information for "{field}".', "missing_argument")
        values[check_col(field)] = coerce(rendered, cols[field])

    returning = [t.c[f] for f in return_fields]
    op = cfg.operation
    if op in ("get_record", "search_records"):
        stmt = select(*returning).where(*conditions).limit(1 if op == "get_record" else cfg.limit)
        for o in cfg.order_by:
            name = check_col(o.lstrip("-"))
            stmt = stmt.order_by(t.c[name].desc() if o.startswith("-") else t.c[name])
    elif op == "create_record":
        stmt = insert(t).values(**values).returning(*returning)
    elif op == "update_record":
        if not conditions:
            raise DatabaseToolError("Refusing to update without a record filter.", "unsafe_update")
        stmt = update(t).where(*conditions).values(**values).returning(*returning)
    else:
        if not conditions:
            raise DatabaseToolError("Refusing to delete without a record filter.", "unsafe_delete")
        stmt = delete(t).where(*conditions).returning(*returning)

    start = time.perf_counter()
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
            # Updates/deletes must affect exactly the targeted record(s), never a surprise bulk change.
            if op in ("update_record", "delete_record") and len(rows) > cfg.limit:
                raise DatabaseToolError("This change would affect too many records and was cancelled.", "too_many_rows")
    except IntegrityError as exc:
        raise DatabaseToolError("The record conflicts with existing data (for example, the slot is already taken).",
                                "conflict") from exc
    except DBAPIError as exc:
        raise DatabaseToolError("The database rejected the request.", "database_error") from exc
    except OSError as exc:
        raise DatabaseToolError("Could not connect to the database.", "connection_error") from exc
    records = [{k: jsonable(v) for k, v in r.items()} for r in rows]
    result: dict[str, Any] = {"records": records, "record": records[0] if records else None, "count": len(records),
                              "db_latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    if op in ("update_record", "delete_record", "get_record") and not records:
        result["not_found"] = True
    return result
