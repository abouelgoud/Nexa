"""Call -> Agent -> Tool: an inbound phone call routed by number to the published agent version."""

from uuid import UUID

from nexa.core.db import get_sessionmaker
from nexa.providers import registry
from nexa.providers.telephony.base import OutboundCall, ProvisionedNumber, SIPProvider
from nexa.runtime.session import ConversationRuntime
from nexa.services.telephony import resolve_inbound
from tests.conftest import setup_doctor_agent


class FakeSIP(SIPProvider):
    name = "fake"

    def __init__(self):
        self.registered: list[str] = []
        self.transfers: list[str] = []

    async def register_number(self, e164, *, tenant_id, agent_id, trunk):
        self.registered.append(e164)
        return ProvisionedNumber(e164, self.name, {"inbound_trunk_id": "ST_1", "dispatch_rule_id": "SDR_1"})

    async def release_number(self, number):
        pass

    async def place_outbound_call(self, *, to_e164, from_number, room_name, metadata):
        return OutboundCall(room_name, {"participant_id": "PA_1"})

    async def transfer(self, *, room_name, participant_identity, to_e164):
        self.transfers.append(to_e164)


async def test_inbound_phone_call_uses_published_version(account, clinic_db):
    sip = FakeSIP()
    registry.override("sip", sip)
    setup = await setup_doctor_agent(account, mode="workflow")
    agent_id = setup["agent"]["id"]
    v1 = (await account.post(f"/agents/{agent_id}/publish", {"notes": "go live"})).json()

    r = await account.post("/phone-numbers", {"e164": "+966112223344", "agent_id": agent_id, "purpose": "test"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "active" and sip.registered == ["+966112223344"]
    assert (await account.post("/phone-numbers", {"e164": "+966112223344"})).status_code == 409

    # Draft edits after publishing must not affect live calls.
    cfg = (await account.get(f"/agents/{agent_id}")).json()["draft_config"]
    cfg["general"]["greeting"] = "DRAFT GREETING"
    await account.put(f"/agents/{agent_id}/config", cfg)

    async with get_sessionmaker()() as db:
        route = await resolve_inbound(db, "+966112223344")
        assert route is not None and str(route.version.id) == v1["id"]
        rt, opening = await ConversationRuntime.start(
            db, tenant_id=route.tenant_id, agent_id=route.agent_id, version=route.version, channel="phone",
            is_test=False, caller_number="+966500000001", to_number="+966112223344",
            phone_number_id=route.phone_number_id, external_id="call-abc")
        assert opening.replies[0] != "DRAFT GREETING"
        call_id = rt.call.id
        await db.commit()

    async def turn(text):
        async with get_sessionmaker()() as db:
            rt = await ConversationRuntime.load(db, call_id, UUID(account.tenant_id))
            result = await rt.handle_user_text(text)
            await db.commit()
            return result

    await turn("أبغى أحجز موعد أسنان")
    await turn("أي دكتور")
    r = await turn("أول واحد")
    # Caller ID was used, so the agent goes straight to confirmation.
    assert r.replies[0].startswith("ممتاز، هل أحجز لك موعد الأسنان")
    r = await turn("ايوه")
    assert r.replies[0].startswith("تم الحجز بنجاح")
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments WHERE patient_id = 1") == 1
    await turn("لا")

    detail = (await account.get(f"/calls/{call_id}")).json()
    assert detail["call"]["channel"] == "phone" and detail["call"]["from_number"] == "+966500000001"
    assert detail["call"]["outcome"] == "task_completed"
    assert detail["agent_version"]["version_number"] == v1["version_number"]

    stats = (await account.get(f"/analytics/overview?agent_id={agent_id}")).json()
    assert stats["calls"] == 1 and stats["completed_tasks"] == 1 and stats["answered_calls"] == 1
    assert stats["languages"] == [{"key": "ar", "count": 1}]
    usage = (await account.get("/analytics/usage")).json()["usage"]
    assert usage["tool_executions"] >= 4 and usage["call_seconds"] >= 0


async def test_unknown_or_disabled_number_is_not_routed(account):
    async with get_sessionmaker()() as db:
        assert await resolve_inbound(db, "+15550000000") is None


async def test_test_number_can_run_draft_before_publishing(account, clinic_db):
    registry.override("sip", FakeSIP())
    setup = await setup_doctor_agent(account)
    agent_id = setup["agent"]["id"]
    await account.post("/test/sessions", {"agent_id": agent_id})  # creates a test snapshot
    await account.post("/phone-numbers", {"e164": "+966119998877", "agent_id": agent_id, "purpose": "test"})
    async with get_sessionmaker()() as db:
        route = await resolve_inbound(db, "+966119998877")
        assert route is not None and route.version.kind == "test"


async def test_outbound_test_call(account, clinic_db):
    registry.override("sip", FakeSIP())
    setup = await setup_doctor_agent(account)
    n = (await account.post("/phone-numbers", {"e164": "+966117776655", "agent_id": setup["agent"]["id"]})).json()
    r = await account.post(f"/phone-numbers/{n['id']}/outbound-test", {"to": "+966500000009"})
    assert r.status_code == 200 and r.json()["room"].startswith("call-out-")
