"""Telephony abstraction. LiveKit SIP is the first implementation; Twilio/Telnyx/Plivo trunks
plug in behind the same interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvisionedNumber:
    e164: str
    provider: str
    provider_ref: dict[str, Any] = field(default_factory=dict)
    status: str = "active"


@dataclass
class OutboundCall:
    room_name: str
    provider_ref: dict[str, Any] = field(default_factory=dict)


class TelephonyError(RuntimeError):
    pass


class SIPProvider(ABC):
    name = "base"

    @abstractmethod
    async def register_number(self, e164: str, *, tenant_id: str, agent_id: str, trunk: dict[str, Any]) -> ProvisionedNumber:
        """Route inbound calls for ``e164`` (from an external SIP trunk) to the voice runtime."""

    @abstractmethod
    async def release_number(self, number: ProvisionedNumber) -> None: ...

    @abstractmethod
    async def place_outbound_call(self, *, to_e164: str, from_number: ProvisionedNumber, room_name: str,
                                  metadata: dict[str, Any]) -> OutboundCall: ...

    @abstractmethod
    async def transfer(self, *, room_name: str, participant_identity: str, to_e164: str) -> None:
        """Blind-transfer the caller (SIP REFER) to a human."""

    async def health(self) -> bool:
        return True
