from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.api.routes.auth import create_tenant
from nexa.api.schemas import MemberIn, MemberOut, TenantIn, TenantOut
from nexa.core.db import get_db
from nexa.core.deps import ROLES, TenantContext, get_current_user, get_tenant_context, require
from nexa.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from nexa.models import Tenant, TenantUser, User
from nexa.services.audit import audit

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
async def list_tenants(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Tenant).join(TenantUser, TenantUser.tenant_id == Tenant.id)
                            .where(TenantUser.user_id == user.id, Tenant.deleted_at.is_(None)).order_by(Tenant.created_at))
    return list(rows)


@router.post("", response_model=TenantOut, status_code=201)
async def create(body: TenantIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await create_tenant(db, user, body.name, body.industry, body.default_timezone)
    await db.commit()
    return tenant


@router.get("/current", response_model=TenantOut)
async def current(ctx: TenantContext = Depends(get_tenant_context)):
    return ctx.tenant


@router.patch("/current", response_model=TenantOut)
async def update(body: TenantIn, ctx: TenantContext = Depends(require("manage_tenant"))):
    ctx.tenant.name, ctx.tenant.industry, ctx.tenant.default_timezone = body.name, body.industry, body.default_timezone
    audit(ctx, "tenant.update", "tenant", ctx.tenant_id, body.model_dump())
    await ctx.db.commit()
    return ctx.tenant


@router.get("/current/members", response_model=list[MemberOut])
async def members(ctx: TenantContext = Depends(get_tenant_context)):
    rows = (await ctx.db.execute(select(TenantUser, User).join(User, User.id == TenantUser.user_id)
                                 .where(TenantUser.tenant_id == ctx.tenant_id))).all()
    return [MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role) for m, u in rows]


@router.post("/current/members", response_model=MemberOut, status_code=201)
async def add_member(body: MemberIn, ctx: TenantContext = Depends(require("manage_members"))):
    if body.role not in ROLES:
        raise ValidationFailed(f"Role must be one of: {', '.join(ROLES)}")
    user = await ctx.db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        raise NotFound("No user with this email. Ask them to create an account first.")
    if await ctx.db.scalar(select(TenantUser).where(TenantUser.tenant_id == ctx.tenant_id, TenantUser.user_id == user.id)):
        raise Conflict("This user is already a member.")
    ctx.db.add(TenantUser(tenant_id=ctx.tenant_id, user_id=user.id, role=body.role))
    audit(ctx, "member.add", "user", user.id, {"role": body.role})
    await ctx.db.commit()
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=body.role)


@router.delete("/current/members/{user_id}", status_code=204)
async def remove_member(user_id: UUID, ctx: TenantContext = Depends(require("manage_members"))):
    m = await ctx.db.scalar(select(TenantUser).where(TenantUser.tenant_id == ctx.tenant_id, TenantUser.user_id == user_id))
    if m is None:
        raise NotFound("Member not found.")
    if m.role == "owner":
        owners = await ctx.db.scalar(select(func.count()).select_from(TenantUser).where(TenantUser.tenant_id == ctx.tenant_id, TenantUser.role == "owner"))
        if owners <= 1:
            raise Forbidden("The last owner cannot be removed.")
    await ctx.db.delete(m)
    audit(ctx, "member.remove", "user", user_id)
    await ctx.db.commit()
