import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from nexa.api.schemas import OutboundCallIn, PhoneNumberIn, PhoneNumberOut, PhoneNumberUpdate
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from nexa.models import PhoneNumber, PhoneRoute
from nexa.providers.registry import get_sip
from nexa.providers.telephony.base import ProvisionedNumber, TelephonyError
from nexa.services.agents import get_agent
from nexa.services.audit import audit

router = APIRouter(prefix="/phone-numbers", tags=["phone"])


async def _get(ctx: TenantContext, number_id: UUID) -> PhoneNumber:
    n = await ctx.db.get(PhoneNumber, number_id)
    if n is None or n.tenant_id != ctx.tenant_id or n.deleted_at is not None:
        raise NotFound("Phone number not found.")
    return n


@router.get("", response_model=list[PhoneNumberOut])
async def list_numbers(agent_id: UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    q = select(PhoneNumber).where(PhoneNumber.tenant_id == ctx.tenant_id, PhoneNumber.deleted_at.is_(None))
    if agent_id:
        q = q.where(PhoneNumber.agent_id == agent_id)
    return list(await ctx.db.scalars(q.order_by(PhoneNumber.created_at)))


@router.post("", response_model=PhoneNumberOut, status_code=201)
async def create_number(body: PhoneNumberIn, ctx: TenantContext = Depends(require("manage_phone"))):
    """Connect a number from your SIP carrier (Twilio, Telnyx, ...) and route it to an agent."""
    taken = await ctx.db.scalar(select(PhoneNumber).where(PhoneNumber.e164 == body.e164,
                                                          PhoneNumber.deleted_at.is_(None))
                                .execution_options(skip_tenant_filter=True))
    if taken:
        raise Conflict("This phone number is already connected.")
    if body.agent_id:
        await get_agent(ctx, body.agent_id)
    sip = get_sip()
    number = PhoneNumber(tenant_id=ctx.tenant_id, e164=body.e164, provider=sip.name if sip else "none",
                         purpose=body.purpose, agent_id=body.agent_id, status="pending", provider_ref={},
                         created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(number)
    await ctx.db.flush()
    if sip is not None:
        try:
            prov = await sip.register_number(body.e164, tenant_id=str(ctx.tenant_id),
                                             agent_id=str(body.agent_id or ""), trunk=body.trunk)
            number.provider_ref, number.status = prov.provider_ref, "active"
        except TelephonyError as exc:
            number.status, number.provider_ref = "error", {"error": str(exc)}
    if body.agent_id:
        ctx.db.add(PhoneRoute(tenant_id=ctx.tenant_id, phone_number_id=number.id, agent_id=body.agent_id,
                              version_policy="published"))
    audit(ctx, "phone.create", "phone_number", number.id, {"e164": body.e164, "purpose": body.purpose})
    await ctx.db.commit()
    return number


@router.patch("/{number_id}", response_model=PhoneNumberOut)
async def update_number(number_id: UUID, body: PhoneNumberUpdate, ctx: TenantContext = Depends(require("manage_phone"))):
    n = await _get(ctx, number_id)
    if body.agent_id is not None:
        await get_agent(ctx, body.agent_id)
        n.agent_id = body.agent_id
        route = await ctx.db.scalar(select(PhoneRoute).where(PhoneRoute.phone_number_id == n.id,
                                                             PhoneRoute.tenant_id == ctx.tenant_id))
        if route:
            route.agent_id = body.agent_id
        else:
            ctx.db.add(PhoneRoute(tenant_id=ctx.tenant_id, phone_number_id=n.id, agent_id=body.agent_id))
    if body.status:
        n.status = body.status
    audit(ctx, "phone.update", "phone_number", n.id, body.model_dump(mode="json"))
    await ctx.db.commit()
    await ctx.db.refresh(n)
    return n


@router.delete("/{number_id}", status_code=204)
async def delete_number(number_id: UUID, ctx: TenantContext = Depends(require("manage_phone"))):
    n = await _get(ctx, number_id)
    sip = get_sip()
    if sip is not None and n.status == "active":
        try:
            await sip.release_number(ProvisionedNumber(n.e164, n.provider, n.provider_ref))
        except TelephonyError as exc:
            raise ServiceUnavailable(str(exc)) from exc
    n.deleted_at, n.status = datetime.now(UTC), "disabled"
    audit(ctx, "phone.delete", "phone_number", n.id)
    await ctx.db.commit()


@router.post("/{number_id}/outbound-test")
async def outbound_test(number_id: UUID, body: OutboundCallIn, ctx: TenantContext = Depends(require("test"))):
    """Have the agent call a phone (e.g. your mobile) - requires an outbound trunk on the number."""
    n = await _get(ctx, number_id)
    if n.agent_id is None:
        raise ValidationFailed("Assign an agent to this number first.")
    sip = get_sip()
    if sip is None:
        raise ServiceUnavailable("Telephony is not configured.")
    room = f"call-out-{uuid.uuid4().hex[:12]}"
    try:
        call = await sip.place_outbound_call(to_e164=body.to, from_number=ProvisionedNumber(n.e164, n.provider, n.provider_ref),
                                             room_name=room, metadata={"tenant_id": str(ctx.tenant_id),
                                                                       "agent_id": str(n.agent_id), "number": n.e164,
                                                                       "direction": "outbound", "to": body.to})
    except TelephonyError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    audit(ctx, "phone.outbound_test", "phone_number", n.id, {"to": body.to})
    await ctx.db.commit()
    return {"room": call.room_name, "provider_ref": call.provider_ref}
