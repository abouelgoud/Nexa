"""Agent -> LLM -> Tool: the LLM requests tools, the backend validates, gates and executes them."""

import json

from nexa.providers import registry
from nexa.providers.llm.scripted import ScriptedLLM
from tests.conftest import setup_doctor_agent


async def start(account, agent_id):
    r = await account.post("/test/sessions", {"agent_id": agent_id, "use": "draft"})
    assert r.status_code == 201, r.text
    return r.json()


async def say(account, sid, text):
    r = await account.post(f"/test/sessions/{sid}/messages", {"text": text})
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def test_llm_booking_requires_explicit_confirmation(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="agent")
    slot = await clinic_db.fetchrow(
        "SELECT slot_id, doctor_id FROM clinic.available_slots WHERE specialty_id = 1 ORDER BY starts_at LIMIT 1")
    book_args = {"patient_id": 1, "doctor_id": slot["doctor_id"], "slot_id": slot["slot_id"]}
    llm = ScriptedLLM([
        # turn 1: look up slots, then answer
        {"tool": "get_available_slots", "arguments": {"specialty_id": "1"}},
        "عندي الأحد الساعة 6:30. يناسبك؟",
        # turn 2: model tries to book immediately -> backend demands confirmation
        {"tool": "book_appointment", "arguments": book_args},
        "تم الحجز بنجاح!",  # model lies: the output guard must block this
        # turn 3: caller confirms, model repeats the exact same call -> executed
        {"tool": "book_appointment", "arguments": book_args},
        "تم الحجز بنجاح. موعدك الأحد الساعة 6:30.",
    ])
    registry.override("llm", llm)
    session = await start(account, setup["agent"]["id"])
    assert session["mode"] == "agent"
    assert "السلام عليكم" in session["result"]["replies"][0]
    sid = session["session_id"]

    r1 = await say(account, sid, "السلام عليكم، أبغى أحجز موعد جلدية.")
    assert r1["tool_calls"][0]["status"] == "succeeded"
    assert r1["language"] == "ar" and r1["dialect"] == "sa"
    # Tools offered to the model contain no configuration or credentials
    offered = json.dumps(llm.calls[0]["tools"], ensure_ascii=False)
    assert "integration_id" not in offered and "clinic_agent" not in offered and "password" not in offered
    system = llm.calls[0]["messages"][0].content
    assert "Never invent information" in system and "2026" in system or "20" in system

    r2 = await say(account, sid, "أبغى أول موعد")
    assert r2["tool_calls"][0]["status"] == "confirmation_required"
    assert r2["replies"] == ["لم يتم تنفيذ الطلب بعد. هل تريد أن أكمل؟"]
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments") == 0

    r3 = await say(account, sid, "نعم")
    assert r3["tool_calls"][0]["status"] == "succeeded"
    assert r3["replies"] == ["تم الحجز بنجاح. موعدك الأحد الساعة 6:30."]
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments WHERE status='booked'") == 1

    detail = (await account.get(f"/calls/{sid}")).json()
    statuses = [t["status"] for t in detail["tool_executions"]]
    assert statuses == ["succeeded", "confirmation_required", "succeeded"]
    assert detail["tool_executions"][-1]["confirmed"] is True
    assert any(e["type"] == "output_guard" for e in detail["events"])


async def test_confirmation_must_match_the_same_action(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="agent")
    slots = await clinic_db.fetch("SELECT slot_id, doctor_id FROM clinic.available_slots ORDER BY starts_at LIMIT 2")
    a = {"patient_id": 1, "doctor_id": slots[0]["doctor_id"], "slot_id": slots[0]["slot_id"]}
    b = {"patient_id": 1, "doctor_id": slots[1]["doctor_id"], "slot_id": slots[1]["slot_id"]}
    registry.override("llm", ScriptedLLM([
        {"tool": "book_appointment", "arguments": a}, "هل أحجز؟",
        {"tool": "book_appointment", "arguments": b}, "...",  # different slot after "yes" -> not confirmed
    ]))
    sid = (await start(account, setup["agent"]["id"]))["session_id"]
    await say(account, sid, "احجز لي")
    r = await say(account, sid, "نعم")
    assert r["tool_calls"][0]["status"] == "confirmation_required"
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments") == 0


async def test_unknown_tools_and_bad_arguments_are_rejected(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="agent")
    registry.override("llm", ScriptedLLM([
        [{"tool": "drop_database", "arguments": {}}, {"tool": "find_patient", "arguments": {"phone": 5}}],
        "عذراً",
    ]))
    sid = (await start(account, setup["agent"]["id"]))["session_id"]
    r = await say(account, sid, "hello")
    assert [t["status"] for t in r["tool_calls"]] == ["rejected", "rejected"]
    assert r["tool_calls"][0]["error_code"] == "unknown_tool"


async def test_explicit_human_request_transfers_without_llm(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="agent")
    llm = ScriptedLLM([])
    registry.override("llm", llm)
    sid = (await start(account, setup["agent"]["id"]))["session_id"]
    r = await say(account, sid, "ابي اكلم موظف لو سمحت")
    assert r["transferred"] is True
    assert r["actions"][0]["type"] == "transfer" and r["actions"][0]["phone_number"] == "+966110000000"
    assert llm.calls == []
    call = (await account.get(f"/calls/{sid}")).json()["call"]
    assert call["status"] == "transferred" and call["outcome"] == "transferred"


async def test_llm_outage_offers_human(account, clinic_db):
    from nexa.providers.llm.base import LLMError

    class DownLLM(ScriptedLLM):
        async def generate_with_tools(self, *a, **k):
            raise LLMError("down")

    setup = await setup_doctor_agent(account, mode="agent")
    registry.override("llm", DownLLM())
    sid = (await start(account, setup["agent"]["id"]))["session_id"]
    await say(account, sid, "مرحبا")
    r = await say(account, sid, "مرحبا؟")
    assert "تحب أحولك" in r["replies"][-1]
    r = await say(account, sid, "ايوه")
    assert r["transferred"] is True


async def test_mixed_language_turn_metadata(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="agent")
    registry.override("llm", ScriptedLLM(["أكيد، أي تخصص؟"]))
    sid = (await start(account, setup["agent"]["id"]))["session_id"]
    r = await say(account, sid, "أبغى أحجز appointment")
    assert r["language"] == "ar" and r["code_switching"] is True
    msgs = (await account.get(f"/conversations/{sid}")).json()["messages"]
    user = [m for m in msgs if m["role"] == "user"][0]
    assert user["original_text"] == "أبغى أحجز appointment"
