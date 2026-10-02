"""Agent -> Database: generic database actions against the demo clinic (a separate customer DB)."""

import pytest

from tests.conftest import setup_doctor_agent


async def tools_by_name(account) -> dict[str, dict]:
    return {t["name"]: t for t in (await account.get("/tools")).json()}


async def test_template_setup_creates_tools_and_workflow(account, clinic_db):
    setup = await setup_doctor_agent(account)
    tools = await tools_by_name(account)
    assert {"find_patient", "list_specialties", "get_available_slots", "book_appointment", "cancel_appointment",
            "reschedule_appointment"} <= set(tools)
    assert setup["agent"]["draft_config"]["workflow_id"]
    checklist = (await account.get(f"/agents/{setup['agent']['id']}/checklist")).json()
    assert checklist["ready"], checklist
    # Credentials are never returned to the browser
    integ = (await account.get(f"/integrations/{setup['integration']['id']}")).json()
    assert integ["has_credentials"] and "password" not in str(integ["config"]).lower()


async def test_search_and_create_records(account, clinic_db):
    await setup_doctor_agent(account)
    tools = await tools_by_name(account)
    r = await account.post(f"/tools/{tools['get_available_slots']['id']}/test", {"arguments": {"specialty_id": "1"}})
    body = r.json()
    assert body["status"] == "succeeded", body
    assert 1 <= body["data"]["count"] <= 3
    slot = body["data"]["records"][0]
    assert {"slot_id", "label_ar", "label_en", "slot_date"} <= set(slot)

    r = await account.post(f"/tools/{tools['find_patient']['id']}/test", {"arguments": {"phone": "+966500000001"}})
    patient = r.json()["data"]["record"]
    assert patient["full_name"] == "محمد عبدالله"
    # Denied columns are never selected
    assert "national_id" not in patient and "medical_notes" not in patient

    r = await account.post(f"/tools/{tools['book_appointment']['id']}/test", {"arguments": {
        "patient_id": patient["id"], "doctor_id": slot["doctor_id"], "slot_id": slot["slot_id"]}})
    assert r.json()["status"] == "succeeded"
    row = await clinic_db.fetchrow("SELECT * FROM clinic.appointments WHERE slot_id = $1", slot["slot_id"])
    assert row["status"] == "booked" and row["patient_id"] == patient["id"]

    # Double booking is rejected by the customer's database constraint - never reported as success.
    r = await account.post(f"/tools/{tools['book_appointment']['id']}/test", {"arguments": {
        "patient_id": patient["id"], "doctor_id": slot["doctor_id"], "slot_id": slot["slot_id"]}})
    assert r.json()["status"] == "failed" and r.json()["error_code"] == "conflict"

    # Cancel requires a matching patient: a different patient id changes nothing.
    r = await account.post(f"/tools/{tools['cancel_appointment']['id']}/test", {"arguments": {
        "appointment_id": row["id"], "patient_id": 999}})
    assert r.json()["status"] == "failed" and r.json()["error_code"] == "not_found"
    assert (await clinic_db.fetchval("SELECT status FROM clinic.appointments WHERE id=$1", row["id"])) == "booked"


async def test_permission_denied_tool_cannot_be_created(account, clinic_db):
    setup = await setup_doctor_agent(account)
    r = await account.post("/tools", {
        "name": "read_national_ids", "description": "Read sensitive data", "category": "database",
        "executor": "database",
        "config": {"integration_id": setup["integration"]["id"], "operation": "search_records", "db_schema": "clinic",
                   "table": "patients", "return_fields": ["full_name", "national_id"]}})
    assert r.status_code == 422
    assert "not allowed to read" in str(r.json()["error"]["details"])

    r = await account.post("/tools", {
        "name": "wipe_patients", "description": "Delete patients", "category": "database", "executor": "database",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
        "config": {"integration_id": setup["integration"]["id"], "operation": "delete_record", "db_schema": "clinic",
                   "table": "patients", "filters": [{"field": "id", "arg": "id"}]}})
    assert r.status_code == 422
    assert "permission to delete" in str(r.json()["error"]["details"])


async def test_tool_versions_are_recorded(account, clinic_db):
    await setup_doctor_agent(account)
    tool = (await tools_by_name(account))["find_doctors"]
    definition = {**tool["definition"], "description": "Find doctors (updated)"}
    r = await account.put(f"/tools/{tool['id']}", definition)
    assert r.json()["current_version"] == 2
    versions = (await account.get(f"/tools/{tool['id']}/versions")).json()
    assert [v["version_number"] for v in versions] == [2, 1]


async def test_schema_discovery(account, clinic_db):
    setup = await setup_doctor_agent(account)
    r = await account.get(f"/integrations/{setup['integration']['id']}/schema")
    tables = {t["schema"] + "." + t["table"] for t in r.json()["tables"]}
    assert "clinic.appointments" in tables


@pytest.mark.parametrize("args,code", [({"phone": None}, "invalid_arguments"), ({}, "invalid_arguments")])
async def test_invalid_arguments_rejected(account, clinic_db, args, code):
    await setup_doctor_agent(account)
    tool = (await tools_by_name(account))["find_patient"]
    r = await account.post(f"/tools/{tool['id']}/test", {"arguments": args})
    assert r.json()["status"] == "rejected" and r.json()["error_code"] == code
