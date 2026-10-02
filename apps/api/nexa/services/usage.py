from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexa.models import UsageRecord

METRICS = {"call_seconds", "audio_seconds", "llm_tokens", "stt_seconds", "tts_characters", "storage_bytes",
           "api_calls", "tool_executions"}


def record_usage(db: AsyncSession, tenant_id: UUID, metric: str, quantity: float, *, call_id: UUID | None = None,
                 agent_id: UUID | None = None, meta: dict | None = None) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown usage metric: {metric}")
    if quantity <= 0:
        return
    db.add(UsageRecord(tenant_id=tenant_id, metric=metric, quantity=quantity, call_id=call_id, agent_id=agent_id,
                       meta=meta or {}))
