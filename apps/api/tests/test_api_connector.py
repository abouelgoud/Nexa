"""Agent -> REST API: the no-code connector, credentials handling and SSRF protection."""

import json

import httpx
import pytest

from nexa.core.config import get_settings
from nexa.tools import rest


@pytest.fixture
def fake_api():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/doctors/42/slots":
            return httpx.Response(200, json={"data": {"items": [{"id": 1, "start": "18:30"}, {"id": 2, "start": "19:00"}]}})
        if request.url.path == "/v1/appointments" and request.method == "POST":
            return httpx.Response(201, json={"appointment": {"id": "A-77", "status": "confirmed"}})
        if request.url.path == "/v1/missing":
            return httpx.Response(404, json={"error": "nope"})
        return httpx.Response(500)

    rest.set_transport(httpx.MockTransport(handler))
    yield seen
    rest.set_transport(None)


async def create_integration(account) -> dict:
    r = await account.post("/integrations", {
        "name": "Clinic API", "kind": "rest_api",
        "config": {"base_url": "https://api.clinic.example.com/v1", "auth": {"type": "bearer"},
                   "default_headers": {"Accept": "application/json"}},
        "credentials": {"token": "super-secret-token"}})
    assert r.status_code == 201, r.text
    return r.json()


async def test_credentials_are_write_only(account):
    integ = await create_integration(account)
    assert integ["has_credentials"] is True
    assert "super-secret-token" not in json.dumps(integ)
    listing = (await account.get("/integrations")).json()
    assert "super-secret-token" not in json.dumps(listing)
    r = await account.post("/integrations", {"name": "bad", "kind": "rest_api",
                                             "config": {"base_url": "https://x.example.com", "api_key": "leak"}})
    assert r.status_code == 422 and "secret" in r.json()["error"]["message"]


async def test_get_with_path_params_and_response_mapping(account, fake_api):
    integ = await create_integration(account)
    r = await account.post("/tools", {
        "name": "doctor_slots", "description": "Get a doctor's slots", "category": "rest_api", "executor": "rest_api",
        "input_schema": {"type": "object", "properties": {"doctor_id": {"type": "integer"}, "date": {"type": "string"}},
                         "required": ["doctor_id"]},
        "config": {"integration_id": integ["id"], "method": "GET", "path": "/doctors/{doctor_id}/slots",
                   "query": {"date": "{{date}}"}, "response_mapping": {"slot_ids": "data.items[].id",
                                                                       "times": "data.items[].start"}}})
    assert r.status_code == 201, r.text
    result = (await account.post(f"/tools/{r.json()['id']}/test", {"arguments": {"doctor_id": 42}})).json()
    assert result["status"] == "succeeded", result
    assert result["data"]["data"] == {"slot_ids": [1, 2], "times": ["18:30", "19:00"]}
    req = fake_api[-1]
    assert req.headers["authorization"] == "Bearer super-secret-token"
    assert "date" not in req.url.params  # empty optional query values are dropped
    # Secrets never appear in the logged execution
    detail = json.dumps(result)
    assert "super-secret-token" not in detail


async def test_post_body_mapping(account, fake_api):
    integ = await create_integration(account)
    r = await account.post("/tools", {
        "name": "create_booking", "description": "Create a booking", "category": "rest_api", "executor": "rest_api",
        "requires_confirmation": True,
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "doctor_id": {"type": "integer"}},
                         "required": ["name", "doctor_id"]},
        "config": {"integration_id": integ["id"], "method": "POST", "path": "/appointments",
                   "body": {"customer.fullName": "{{name}}", "doctor.doctorId": "{{doctor_id}}", "source": "ai"},
                   "response_mapping": {"booking_id": "appointment.id"}}})
    result = (await account.post(f"/tools/{r.json()['id']}/test",
                                 {"arguments": {"name": "Ali", "doctor_id": "42"}})).json()
    assert result["data"]["data"] == {"booking_id": "A-77"}
    assert json.loads(fake_api[-1].content) == {"customer": {"fullName": "Ali"}, "doctor": {"doctorId": 42},
                                                "source": "ai"}


async def test_http_errors_are_failures(account, fake_api):
    integ = await create_integration(account)
    r = await account.post("/tools", {
        "name": "missing", "description": "Missing endpoint", "category": "rest_api", "executor": "rest_api",
        "config": {"integration_id": integ["id"], "path": "/missing"}})
    result = (await account.post(f"/tools/{r.json()['id']}/test", {"arguments": {}})).json()
    assert result["status"] == "failed" and result["error_code"] == "not_found"


async def test_private_network_blocked(account, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_network_integrations", False)
    r = await account.post("/integrations", {"name": "internal", "kind": "rest_api",
                                             "config": {"base_url": "http://127.0.0.1:8080"}})
    r = await account.post("/tools", {
        "name": "internal_call", "description": "Internal", "category": "rest_api", "executor": "rest_api",
        "config": {"integration_id": r.json()["id"], "path": "/admin"}})
    result = (await account.post(f"/tools/{r.json()['id']}/test", {"arguments": {}})).json()
    assert result["status"] == "failed"
    assert "internal network" in result["error"]
