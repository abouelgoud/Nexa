import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.api.schemas import LoginIn, MembershipOut, RegisterIn, TokenOut, UserOut
from nexa.core.config import get_settings
from nexa.core.db import get_db
from nexa.core.deps import get_current_user
from nexa.core.errors import Conflict, Unauthorized
from nexa.core.rate_limit import limiter
from nexa.core.security import create_access_token, hash_password, verify_password
from nexa.models import AuditLog, Tenant, TenantUser, User

router = APIRouter(prefix="/auth", tags=["auth"])


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "business"
    return f"{base}-{secrets.token_hex(3)}"


async def create_tenant(db: AsyncSession, user: User, name: str, industry: str | None = None,
                        tz: str = "Asia/Riyadh") -> Tenant:
    tenant = Tenant(name=name, slug=slugify(name), industry=industry, default_timezone=tz, settings={})
    db.add(tenant)
    await db.flush()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner"))
    db.add(AuditLog(tenant_id=tenant.id, actor_user_id=user.id, action="tenant.create", entity_type="tenant",
                    entity_id=tenant.id, changes={"name": name}))
    return tenant


async def memberships(db: AsyncSession, user: User) -> list[MembershipOut]:
    rows = (await db.execute(select(TenantUser, Tenant).join(Tenant, Tenant.id == TenantUser.tenant_id)
                             .where(TenantUser.user_id == user.id, Tenant.deleted_at.is_(None))
                             .order_by(Tenant.created_at))).all()
    return [MembershipOut(tenant_id=t.id, tenant_name=t.name, role=m.role) for m, t in rows]


@router.post("/register", response_model=TokenOut, status_code=201,
             dependencies=[Depends(limiter("auth", get_settings().auth_rate_limit_per_minute))])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    email = body.email.lower()
    if await db.scalar(select(User).where(func.lower(User.email) == email)):
        raise Conflict("An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name, locale=body.locale)
    db.add(user)
    await db.flush()
    if body.tenant_name:
        await create_tenant(db, user, body.tenant_name)
    await db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user),
                    memberships=await memberships(db, user))


@router.post("/login", response_model=TokenOut,
             dependencies=[Depends(limiter("auth", get_settings().auth_rate_limit_per_minute))])
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower(), User.deleted_at.is_(None)))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise Unauthorized("Incorrect email or password.")
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user),
                    memberships=await memberships(db, user))


@router.get("/me", response_model=TokenOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> TokenOut:
    return TokenOut(access_token="", user=UserOut.model_validate(user), memberships=await memberships(db, user))
