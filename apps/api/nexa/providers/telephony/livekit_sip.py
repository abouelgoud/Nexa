"""LiveKit SIP implementation of ``SIPProvider``.

A carrier (Twilio, Telnyx, Plivo, ...) owns the phone number and points its SIP
trunk at LiveKit SIP. We register an inbound trunk for the number and a dispatch
rule that creates a room per call and dispatches the ``nexa-voice`` agent worker
(services/voice-runtime) with the tenant/agent ids in the job metadata.
"""

from __future__ import annotations

import json
from typing import Any

from nexa.providers.telephony.base import OutboundCall, ProvisionedNumber, SIPProvider, TelephonyError

AGENT_NAME = "nexa-voice"


class LiveKitSIPProvider(SIPProvider):
    name = "livekit"

    def __init__(self, url: str, api_key: str, api_secret: str):
        self.url, self.api_key, self.api_secret = url, api_key, api_secret

    def _client(self):
        from livekit import api

        return api.LiveKitAPI(self.url, self.api_key, self.api_secret)

    async def register_number(self, e164: str, *, tenant_id: str, agent_id: str, trunk: dict[str, Any]) -> ProvisionedNumber:
        from livekit import api

        lk = self._client()
        try:
            inbound = await lk.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(trunk=api.SIPInboundTrunkInfo(
                name=f"nexa-{tenant_id[:8]}-{e164}", numbers=[e164], krisp_enabled=True,
                allowed_addresses=trunk.get("allowed_addresses", []),
                auth_username=trunk.get("inbound_username", ""), auth_password=trunk.get("inbound_password", ""),
                metadata=json.dumps({"tenant_id": tenant_id}))))
            metadata = json.dumps({"tenant_id": tenant_id, "agent_id": agent_id, "number": e164})
            rule = await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-")),
                trunk_ids=[inbound.sip_trunk_id], name=f"nexa-{e164}", metadata=metadata,
                room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME,
                                                                                metadata=metadata)])))
            ref: dict[str, Any] = {"inbound_trunk_id": inbound.sip_trunk_id, "dispatch_rule_id": rule.sip_dispatch_rule_id}
            if trunk.get("outbound_address"):
                outbound = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(
                    trunk=api.SIPOutboundTrunkInfo(name=f"nexa-out-{e164}", address=trunk["outbound_address"],
                                                   numbers=[e164], auth_username=trunk.get("outbound_username", ""),
                                                   auth_password=trunk.get("outbound_password", ""))))
                ref["outbound_trunk_id"] = outbound.sip_trunk_id
            return ProvisionedNumber(e164=e164, provider=self.name, provider_ref=ref)
        except Exception as exc:  # noqa: BLE001 - twirp/network errors
            raise TelephonyError(f"LiveKit SIP rejected the number: {exc}") from exc
        finally:
            await lk.aclose()

    async def release_number(self, number: ProvisionedNumber) -> None:
        from livekit import api

        lk = self._client()
        try:
            if number.provider_ref.get("dispatch_rule_id"):
                await lk.sip.delete_dispatch_rule(api.DeleteSIPDispatchRuleRequest(
                    sip_dispatch_rule_id=number.provider_ref["dispatch_rule_id"]))
            for key in ("inbound_trunk_id", "outbound_trunk_id"):
                if number.provider_ref.get(key):
                    await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=number.provider_ref[key]))
        except Exception as exc:  # noqa: BLE001
            raise TelephonyError(f"Could not release the number: {exc}") from exc
        finally:
            await lk.aclose()

    async def place_outbound_call(self, *, to_e164: str, from_number: ProvisionedNumber, room_name: str,
                                  metadata: dict[str, Any]) -> OutboundCall:
        from livekit import api

        trunk_id = from_number.provider_ref.get("outbound_trunk_id")
        if not trunk_id:
            raise TelephonyError("This number has no outbound SIP trunk configured.")
        lk = self._client()
        try:
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME, room=room_name, metadata=json.dumps(metadata)))
            p = await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id, sip_call_to=to_e164, room_name=room_name, participant_identity=f"sip-{to_e164}",
                participant_name=to_e164, krisp_enabled=True))
            return OutboundCall(room_name=room_name, provider_ref={"participant_id": p.participant_id,
                                                                   "sip_call_id": p.sip_call_id})
        except Exception as exc:  # noqa: BLE001
            raise TelephonyError(f"Outbound call failed: {exc}") from exc
        finally:
            await lk.aclose()

    async def transfer(self, *, room_name: str, participant_identity: str, to_e164: str) -> None:
        from livekit import api

        lk = self._client()
        try:
            await lk.sip.transfer_sip_participant(api.TransferSIPParticipantRequest(
                room_name=room_name, participant_identity=participant_identity, transfer_to=f"tel:{to_e164}",
                play_dialtone=False))
        except Exception as exc:  # noqa: BLE001
            raise TelephonyError(f"Transfer failed: {exc}") from exc
        finally:
            await lk.aclose()
