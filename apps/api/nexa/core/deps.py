"""Request dependencies: authentication, tenant resolution and RBAC.

Authorization is enforced here, on the backend. The tenant is selected with the
``X-Tenant-ID`` header and the user's membership/role is verified on every request.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.core.db import bind_tenant, get_db
from nexa.core.errors import Forbidden, Unauthorized
from nexa.core.security import decode_access_token
from nexa.models import Tenant, TenantUser, User

bearer = HTTPBearer(auto_error=False)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {"read"},
    "editor": {"read", "write", "test"},
    "admin": {"read", "write", "test", "publish", "manage_integrations", "manage_phone"},
    "owner": {"read", "write", "test", "publish", "manage_integrations", "manage_phone", "manage_members",
              "manage_tenant"},
}
ROLES = list(ROLE_PERMISSIONS)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)
) -> User:
    if creds is None:
        raise Unauthorized("Please sign in to continue.")
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise Unauthorized("Your session has expired. Please sign in again.")
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Your account is not active.")
    return user


@dataclass
class TenantContext:
    user: User
    tenant: Tenant
    role: str
    db: AsyncSession
    ip: str | None = None

    @property
    def tenant_id(self) -> UUID:
        return self.tenant.id

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise Forbidden("Your role does not allow this action. Ask an owner or admin for access.")


async def get_tenant_context(
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    if not x_tenant_id:
        raise Forbidden("Select a business (tenant) first.", code="tenant_required")
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise Forbidden("Unknown business.") from exc
    row = (
        await db.execute(
            select(TenantUser, Tenant)
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user.id, Tenant.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        # Same message whether the tenant exists or not: do not leak tenant existence.
        raise Forbidden("You do not have access to this business.")
    membership, tenant = row
    bind_tenant(db, tenant.id)
    return TenantContext(user=user, tenant=tenant, role=membership.role, db=db,
                         ip=request.client.host if request.client else None)


def require(permission: str):
    async def _dep(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        ctx.require(permission)
        return ctx

    return _dep
