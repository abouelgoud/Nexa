from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from nexa.schemas.agent_definition import AgentDefinition

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def local_now(defn: AgentDefinition, now: datetime | None = None) -> datetime:
    try:
        tz = ZoneInfo(defn.general.timezone)
    except Exception:  # noqa: BLE001 - invalid zone falls back to UTC
        tz = ZoneInfo("UTC")
    return (now or datetime.now(UTC)).astimezone(tz)


def is_open(defn: AgentDefinition, now: datetime | None = None) -> bool:
    """True when inside operating hours (or when no hours are configured)."""
    if not defn.general.operating_hours:
        return True
    local = local_now(defn, now)
    day = DAY_KEYS[local.weekday()]
    hm = local.strftime("%H:%M")
    for slot in defn.general.operating_hours:
        if slot.day == day and slot.open <= hm < slot.close:
            return True
    return False
