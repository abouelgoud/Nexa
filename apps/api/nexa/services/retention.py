"""Data retention: delete transcripts/messages/events older than each agent version's retention policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.models import AgentVersion, Call, CallEvent, Conversation, Message, Transcript


async def cleanup(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    purged = 0
    versions = (await db.execute(select(AgentVersion.id, AgentVersion.config))).all()
    for vid, config in versions:
        days = int(config.get("definition", {}).get("privacy", {}).get("retention_days", 30))
        cutoff = now - timedelta(days=days)
        call_ids = select(Call.id).where(Call.agent_version_id == vid, Call.started_at < cutoff)
        conv_ids = select(Conversation.id).where(Conversation.call_id.in_(call_ids))
        r1 = await db.execute(delete(Transcript).where(Transcript.call_id.in_(call_ids)))
        r2 = await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(CallEvent).where(CallEvent.call_id.in_(call_ids)))
        await db.execute(update(Conversation).where(Conversation.call_id.in_(call_ids)).values(state={}))
        await db.execute(update(Call).where(Call.id.in_(call_ids), Call.recording_uri.is_not(None))
                         .values(recording_uri=None))
        purged += (r1.rowcount or 0) + (r2.rowcount or 0)
    await db.flush()
    return {"purged_rows": purged}
