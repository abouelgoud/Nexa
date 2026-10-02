import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from nexa.core.db import get_sessionmaker


async def make_agent(account, **overrides):
    r = await account.post("/agents", {"template_key": "blank", "business_name": "ABC"})
    agent = r.json()
    config = {**agent["draft_config"], **overrides}
    r = await account.put(f"/agents/{agent['id']}/config", config)
    assert r.status_code == 200, r.text
    return r.json()


async def test_checklist_explains_problems_in_business_language(account):
    agent = await make_agent(account, general={"greeting": ""}, capabilities=[])
    r = await account.get(f"/agents/{agent['id']}/checklist")
    body = r.json()
    assert body["ready"] is False
    failing = {i["key"]: i["message"] for i in body["items"] if not i["ok"]}
    assert "greeting" in failing and "General settings" in failing["greeting"]
    assert "capabilities" in failing
    r = await account.post(f"/agents/{agent['id']}/publish", {"notes": "v1"})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "The agent is not ready to publish yet."


async def test_capability_requires_action(account):
    agent = await make_agent(account, capabilities=["book_appointment"])
    items = {i["key"]: i for i in (await account.get(f"/agents/{agent['id']}/checklist")).json()["items"]}
    assert not items["required_tools"]["ok"]
    assert "book appointment" in items["required_tools"]["message"]


async def test_publish_creates_immutable_versions(account):
    agent = await make_agent(account)
    r = await account.post(f"/agents/{agent['id']}/publish", {"notes": "first"})
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["version_number"] == 1 and v1["kind"] == "published"

    # Editing the draft never changes the published version.
    cfg = (await account.get(f"/agents/{agent['id']}")).json()["draft_config"]
    cfg["general"]["greeting"] = "مرحبا من النسخة الثانية"
    await account.put(f"/agents/{agent['id']}/config", cfg)
    v1_detail = (await account.get(f"/agents/{agent['id']}/versions/{v1['id']}")).json()
    assert v1_detail["config"]["definition"]["general"]["greeting"] != "مرحبا من النسخة الثانية"

    v2 = (await account.post(f"/agents/{agent['id']}/publish", {"notes": "second"})).json()
    assert v2["version_number"] == 2
    a = (await account.get(f"/agents/{agent['id']}")).json()
    assert a["published_version_id"] == v2["id"] and a["status"] == "published"

    # Roll back to v1 by pointing production at it (no mutation).
    r = await account.post(f"/agents/{agent['id']}/versions/{v1['id']}/activate")
    assert r.json()["published_version_id"] == v1["id"]
    versions = (await account.get(f"/agents/{agent['id']}/versions")).json()
    assert [v["version_number"] for v in versions] == [2, 1]


async def test_database_rejects_mutating_a_version(account):
    agent = await make_agent(account)
    v = (await account.post(f"/agents/{agent['id']}/publish", {"notes": ""})).json()
    async with get_sessionmaker()() as db:
        with pytest.raises(DBAPIError, match="immutable"):
            await db.execute(text("UPDATE agent_versions SET config = '{}'::jsonb WHERE id = :id"), {"id": v["id"]})
        await db.rollback()
        # Non-configuration fields (notes) may still be annotated.
        await db.execute(text("UPDATE agent_versions SET notes = 'annotated' WHERE id = :id"), {"id": v["id"]})
        await db.commit()


async def test_test_sessions_snapshot_the_draft_and_dedupe(account):
    agent = await make_agent(account)
    s1 = (await account.post("/test/sessions", {"agent_id": agent["id"], "use": "draft"})).json()
    s2 = (await account.post("/test/sessions", {"agent_id": agent["id"], "use": "draft"})).json()
    assert s1["agent_version"]["id"] == s2["agent_version"]["id"]
    assert s1["agent_version"]["kind"] == "test"
    r = await account.post("/test/sessions", {"agent_id": agent["id"], "use": "published"})
    assert r.status_code == 422


async def test_restore_draft_from_version(account):
    agent = await make_agent(account)
    v = (await account.post(f"/agents/{agent['id']}/publish", {"notes": ""})).json()
    cfg = (await account.get(f"/agents/{agent['id']}")).json()["draft_config"]
    cfg["name"] = "Changed"
    await account.put(f"/agents/{agent['id']}/config", cfg)
    r = await account.post(f"/agents/{agent['id']}/versions/{v['id']}/restore-draft")
    assert r.json()["draft_config"]["name"] != "Changed"


async def test_invalid_config_explained(account):
    agent = await make_agent(account)
    r = await account.put(f"/agents/{agent['id']}/config", {"name": "", "languages": []})
    assert r.status_code == 422
    details = r.json()["error"]["details"]
    assert any("Name" in d["message"] for d in details)


async def test_create_second_agent_without_code(account):
    await make_agent(account)
    r = await account.post("/agents", {"template_key": "restaurant_reservations", "business_name": "مطعم"})
    assert r.status_code == 201
    assert len((await account.get("/agents")).json()) == 2
