"""Inbound call routing: phone number -> route -> agent -> immutable version."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.models import Agent, AgentVersion, PhoneNumber, PhoneRoute
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.hours import is_open


@dataclass
class RouteDecision:
    tenant_id: UUID
    agent_id: UUID
    version: AgentVersion
    phone_number_id: UUID


async def resolve_inbound(db: AsyncSession, e164: str) -> RouteDecision | None:
    number = await db.scalar(select(PhoneNumber).where(PhoneNumber.e164 == e164, PhoneNumber.status == "active",
                                                       PhoneNumber.deleted_at.is_(None)))
    if number is None:
        return None
    routes = (await db.scalars(select(PhoneRoute).where(PhoneRoute.phone_number_id == number.id,
                                                        PhoneRoute.tenant_id == number.tenant_id)
                               .order_by(PhoneRoute.priority))).all()
    candidates = [(r.agent_id, r.version_policy, r.conditions) for r in routes]
    if number.agent_id:
        candidates.append((number.agent_id, "published", {}))
    for agent_id, policy, conditions in candidates:
        agent = await db.get(Agent, agent_id)
        if agent is None or agent.deleted_at is not None or agent.tenant_id != number.tenant_id:
            continue
        version = await _version(db, agent, policy, number.purpose)
        if version is None:
            continue
        hours = conditions.get("business_hours", "any")
        if hours != "any":
            open_now = is_open(AgentDefinition.model_validate(version.config["definition"]))
            if (hours == "inside") != open_now:
                continue
        return RouteDecision(number.tenant_id, agent.id, version, number.id)
    return None


async def _version(db: AsyncSession, agent: Agent, policy: str, purpose: str) -> AgentVersion | None:
    if agent.published_version_id and policy == "published":
        return await db.get(AgentVersion, agent.published_version_id)
    if purpose == "test" or policy == "latest_test":
        # Test numbers may run the newest snapshot (draft testing over the phone).
        return await db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id)
                               .order_by(AgentVersion.version_number.desc()))
    return None
