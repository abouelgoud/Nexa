from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from nexa.api.schemas import IntegrationIn, IntegrationOut, IntegrationUpdate
from nexa.core.config import get_settings
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from nexa.core.security import decrypt_json, encrypt_json
from nexa.models import Integration, IntegrationCredential
from nexa.services.audit import audit
from nexa.templates.doctor_appointment import INTEGRATION_PERMISSIONS
from nexa.tools import database as dbtool
from nexa.tools.network import BlockedDestination, ensure_public_url

router = APIRouter(prefix="/integrations", tags=["integrations"])

SECRET_FIELDS = {"postgres": {"password", "dsn"}, "rest_api": {"token", "api_key", "username", "password"}}


def _hint(creds: dict[str, Any]) -> str:
    parts = []
    for k, v in creds.items():
        if isinstance(v, str) and v:
            parts.append(f"{k} ••••{v[-2:]}" if len(v) > 6 else f"{k} ••••")
    return ", ".join(parts)


def _validate_config(kind: str, config: dict[str, Any]) -> None:
    for k in config:
        if k.lower() in SECRET_FIELDS[kind] | {"secret", "authorization"}:
            raise ValidationFailed(f'"{k}" is a secret. Put it in credentials so it is stored encrypted.')
    if kind == "rest_api":
        url = config.get("base_url", "")
        if urlparse(url).scheme not in ("http", "https"):
            raise ValidationFailed("The API base URL must start with http:// or https://")
        auth = config.get("auth", {"type": "none"})
        if auth.get("type") not in ("none", "bearer", "api_key", "basic"):
            raise ValidationFailed("Unsupported authentication type.")
    if kind == "postgres" and not config.get("host") and not config.get("use_dsn"):
        raise ValidationFailed("Enter the database host (or provide a connection string in credentials).")


async def _out(ctx: TenantContext, integ: Integration) -> IntegrationOut:
    cred = await ctx.db.scalar(select(IntegrationCredential).where(IntegrationCredential.integration_id == integ.id))
    out = IntegrationOut.model_validate(integ)
    out.has_credentials = cred is not None
    out.credential_hint = cred.hint if cred else ""
    return out


async def _get(ctx: TenantContext, integration_id: UUID) -> Integration:
    integ = await ctx.db.get(Integration, integration_id)
    if integ is None or integ.tenant_id != ctx.tenant_id or integ.deleted_at is not None:
        raise NotFound("Connection not found.")
    return integ


async def _set_credentials(ctx: TenantContext, integ: Integration, creds: dict[str, Any]) -> None:
    allowed = SECRET_FIELDS[integ.kind]
    unknown = set(creds) - allowed
    if unknown:
        raise ValidationFailed(f"Unknown credential fields: {', '.join(sorted(unknown))}")
    row = await ctx.db.scalar(select(IntegrationCredential).where(IntegrationCredential.integration_id == integ.id))
    data = {k: v for k, v in creds.items() if v not in (None, "")}
    if row is None:
        ctx.db.add(IntegrationCredential(tenant_id=ctx.tenant_id, integration_id=integ.id,
                                         encrypted_data=encrypt_json(data), hint=_hint(data)))
    else:
        merged = {**decrypt_json(row.encrypted_data), **data}
        row.encrypted_data, row.hint = encrypt_json(merged), _hint(merged)


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(ctx: TenantContext = Depends(get_tenant_context)):
    rows = await ctx.db.scalars(select(Integration).where(Integration.tenant_id == ctx.tenant_id,
                                                          Integration.deleted_at.is_(None)).order_by(Integration.name))
    return [await _out(ctx, r) for r in rows]


@router.post("", response_model=IntegrationOut, status_code=201)
async def create(body: IntegrationIn, ctx: TenantContext = Depends(require("manage_integrations"))):
    _validate_config(body.kind, body.config)
    integ = Integration(tenant_id=ctx.tenant_id, name=body.name, kind=body.kind, config=body.config,
                        created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(integ)
    await ctx.db.flush()
    if body.credentials:
        await _set_credentials(ctx, integ, body.credentials)
    audit(ctx, "integration.create", "integration", integ.id, {"kind": body.kind, "config": body.config})
    await ctx.db.commit()
    return await _out(ctx, integ)


@router.post("/demo-clinic", response_model=IntegrationOut, status_code=201)
async def create_demo_clinic(ctx: TenantContext = Depends(require("manage_integrations"))):
    """Connect the bundled demo clinic database (local development)."""
    s = get_settings()
    if s.environment == "production":
        raise ValidationFailed("The demo database is only available in development.")
    url = urlparse(s.demo_clinic_database_url)
    integ = Integration(tenant_id=ctx.tenant_id, name="Demo clinic database", kind="postgres",
                        config={"host": url.hostname, "port": url.port or 5432, "database": url.path.lstrip("/"),
                                "username": url.username, "permissions": INTEGRATION_PERMISSIONS},
                        created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(integ)
    await ctx.db.flush()
    await _set_credentials(ctx, integ, {"password": url.password or ""})
    audit(ctx, "integration.create", "integration", integ.id, {"kind": "postgres", "demo": True})
    await ctx.db.commit()
    return await _out(ctx, integ)


@router.get("/{integration_id}", response_model=IntegrationOut)
async def get(integration_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    return await _out(ctx, await _get(ctx, integration_id))


@router.patch("/{integration_id}", response_model=IntegrationOut)
async def update(integration_id: UUID, body: IntegrationUpdate,
                 ctx: TenantContext = Depends(require("manage_integrations"))):
    integ = await _get(ctx, integration_id)
    if body.config is not None:
        _validate_config(integ.kind, body.config)
        integ.config = body.config
    if body.name:
        integ.name = body.name
    if body.status:
        integ.status = body.status
    if body.credentials:
        await _set_credentials(ctx, integ, body.credentials)
    integ.updated_by = ctx.user.id
    audit(ctx, "integration.update", "integration", integ.id,
          {"config": body.config, "credentials_changed": bool(body.credentials)})
    await ctx.db.commit()
    await ctx.db.refresh(integ)
    return await _out(ctx, integ)


@router.delete("/{integration_id}", status_code=204)
async def delete(integration_id: UUID, ctx: TenantContext = Depends(require("manage_integrations"))):
    integ = await _get(ctx, integration_id)
    integ.deleted_at = datetime.now(UTC)
    cred = await ctx.db.scalar(select(IntegrationCredential).where(IntegrationCredential.integration_id == integ.id))
    if cred:
        await ctx.db.delete(cred)
    audit(ctx, "integration.delete", "integration", integ.id)
    await ctx.db.commit()


async def _secrets(ctx: TenantContext, integ: Integration) -> dict[str, Any]:
    cred = await ctx.db.scalar(select(IntegrationCredential).where(IntegrationCredential.integration_id == integ.id))
    return decrypt_json(cred.encrypted_data) if cred else {}


@router.post("/{integration_id}/test")
async def test_connection(integration_id: UUID, ctx: TenantContext = Depends(require("manage_integrations"))):
    integ = await _get(ctx, integration_id)
    secrets = await _secrets(ctx, integ)
    if integ.kind == "postgres":
        try:
            engine = await dbtool.get_engine(str(integ.id), integ.config, secrets)
            tables = await dbtool.list_tables(engine)
        except BlockedDestination as exc:
            raise ValidationFailed(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface a friendly message for any driver error
            raise ServiceUnavailable("Could not connect to the database. Check the host, name, user and password.",
                                     details=type(exc).__name__) from exc
        return {"ok": True, "message": f"Connected. {len(tables)} tables found."}
    import httpx

    try:
        await ensure_public_url(integ.config["base_url"])
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(integ.config["base_url"])
    except BlockedDestination as exc:
        raise ValidationFailed(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ServiceUnavailable("Could not reach the API. Check the base URL.") from exc
    return {"ok": r.status_code < 500, "message": f"The API responded with status {r.status_code}."}


@router.get("/{integration_id}/schema")
async def schema(integration_id: UUID, ctx: TenantContext = Depends(require("manage_integrations"))):
    """Tables and columns, used by the no-code permission editor."""
    integ = await _get(ctx, integration_id)
    if integ.kind != "postgres":
        raise ValidationFailed("Only database connections have tables.")
    try:
        engine = await dbtool.get_engine(str(integ.id), integ.config, await _secrets(ctx, integ))
        return {"tables": await dbtool.list_tables(engine)}
    except BlockedDestination as exc:
        raise ValidationFailed(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ServiceUnavailable("Could not read the database tables.") from exc
