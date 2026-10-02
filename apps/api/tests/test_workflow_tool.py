"""Workflow -> Tool: the doctor template conversation from the product spec, end to end, in Arabic."""

from tests.conftest import setup_doctor_agent


async def say(account, sid, text):
    r = await account.post(f"/test/sessions/{sid}/messages", {"text": text})
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def test_spec_conversation_books_in_customer_database(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="workflow")
    agent_id = setup["agent"]["id"]
    s = (await account.post("/test/sessions", {"agent_id": agent_id, "use": "draft"})).json()
    sid = s["session_id"]
    assert s["mode"] == "workflow"
    assert s["result"]["replies"] == ["السلام عليكم، معك المساعد الذكي في عيادة ABC. كيف أقدر أخدمك؟"]

    r = await say(account, sid, "السلام عليكم، أبغى أحجز موعد جلدية.")
    assert r["replies"] == ["هل تفضل طبيب معين؟"]
    assert r["intent"] == "book"
    assert r["workflow"]["variables"]["specialty"]["label"] == "الجلدية"

    r = await say(account, sid, "لا")
    offer = r["replies"][0]
    assert offer.startswith("عندي ") and "أي موعد يناسبك؟" in offer
    slots = await clinic_db.fetch("SELECT * FROM clinic.available_slots WHERE specialty_id=1 ORDER BY starts_at LIMIT 3")
    second = slots[1]

    r = await say(account, sid, "الثاني")
    assert r["workflow"]["variables"]["slot"]["value"] == second["slot_id"]
    assert r["replies"] == ["ممكن رقم جوالك عشان أسجل الموعد؟"]

    r = await say(account, sid, "٠٥٠٠٠٠٠٠٠١")
    assert r["replies"][0].startswith("ممتاز، هل أحجز لك موعد الجلدية")
    assert await clinic_db.fetchval("SELECT count(*) FROM clinic.appointments") == 0

    r = await say(account, sid, "نعم")
    assert r["replies"][0].startswith("تم الحجز بنجاح.")
    booked = await clinic_db.fetchrow("SELECT * FROM clinic.appointments")
    assert booked["slot_id"] == second["slot_id"] and booked["status"] == "booked"
    book_exec = [t for t in r["tool_calls"] if t["tool"] == "book_appointment"][0]
    assert book_exec["status"] == "succeeded"

    r = await say(account, sid, "لا شكراً")
    assert r["replies"] == ["شكراً لاتصالك، مع السلامة."]
    assert r["ended"] is True

    detail = (await account.get(f"/calls/{sid}")).json()
    assert detail["call"]["status"] == "completed"
    assert detail["call"]["outcome"] == "task_completed"
    assert detail["call"]["language"] == "ar"
    assert detail["workflow"]["status"] == "completed"
    assert "confirm_booking" in detail["workflow"]["path"] and "book" in detail["workflow"]["path"]
    assert [m["role"] for m in detail["messages"]][:2] == ["assistant", "user"]


async def test_cancellation_flow(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="workflow")
    slot = await clinic_db.fetchrow("SELECT slot_id, doctor_id FROM clinic.available_slots LIMIT 1")
    await clinic_db.execute("INSERT INTO clinic.appointments (patient_id, doctor_id, slot_id) VALUES (1, $1, $2)",
                            slot["doctor_id"], slot["slot_id"])
    sid = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"], "use": "draft",
                                                 "caller_number": "+966500000001"})).json()["session_id"]
    r = await say(account, sid, "أبغى ألغي موعدي")
    # Caller number is known on the phone, the single appointment is selected automatically
    assert r["replies"][0].startswith("هل أنت متأكد إنك تبغى تلغي موعد")
    r = await say(account, sid, "ايوه")
    assert r["replies"][0] == "تم إلغاء الموعد."
    assert await clinic_db.fetchval("SELECT status FROM clinic.appointments") == "cancelled"


async def test_english_caller_gets_english_flow(account, clinic_db):
    setup = await setup_doctor_agent(account, mode="workflow")
    sid = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"]})).json()["session_id"]
    r = await say(account, sid, "Hi, I want to book a dentist appointment")
    assert r["language"] == "en"
    assert r["replies"] == ["Do you prefer a specific doctor?"]
