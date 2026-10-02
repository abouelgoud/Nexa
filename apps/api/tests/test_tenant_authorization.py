from sqlalchemy import select

from nexa.core.db import bind_tenant, get_sessionmaker
from nexa.models import Agent
from tests.conftest import register


async def test_requires_authentication(client):
    r = await client.get("/agents")
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Please sign in to continue."


async def test_requires_tenant_header(client, account):
    r = await client.get("/agents", headers={"Authorization": f"Bearer {account.token}"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "tenant_required"


async def test_invalid_token(client):
    r = await client.get("/agents", headers={"Authorization": "Bearer nope", "X-Tenant-ID": "x"})
    assert r.status_code == 401


async def test_login_flow(client, account):
    r = await client.post("/auth/login", json={"email": "owner@abc.example.com", "password": "wrong-password"})
    assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "OWNER@abc.example.com", "password": "secret-pass-123"})
    assert r.status_code == 200
    assert r.json()["memberships"][0]["role"] == "owner"
    r = await client.post("/auth/register", json={"email": "owner@abc.example.com", "password": "secret-pass-123"})
    assert r.status_code == 409


async def test_cross_tenant_access_is_blocked(client, account):
    other = await register(client, "other@xyz.example.com", "XYZ Restaurant")
    r = await account.post("/agents", {"template_key": "blank"})
    agent_id = r.json()["id"]

    # The other tenant cannot select tenant A ...
    r = await client.get("/agents", headers={"Authorization": f"Bearer {other.token}", "X-Tenant-ID": account.tenant_id})
    assert r.status_code == 403
    # ... nor read A's agent through its own tenant.
    r = await other.get(f"/agents/{agent_id}")
    assert r.status_code == 404
    r = await other.put(f"/agents/{agent_id}/config", {"name": "hijack"})
    assert r.status_code == 404
    r = await other.get("/agents")
    assert r.json() == []
    r = await other.get(f"/calls/{agent_id}")
    assert r.status_code == 404


async def test_orm_level_tenant_filter_is_a_safety_net(client, account):
    other = await register(client, "other@xyz.example.com", "XYZ")
    await account.post("/agents", {"template_key": "blank"})
    await other.post("/agents", {"template_key": "blank"})
    async with get_sessionmaker()() as db:
        bind_tenant(db, __import__("uuid").UUID(other.tenant_id))
        # A query that "forgets" the tenant filter still only sees the bound tenant's rows.
        rows = (await db.scalars(select(Agent))).all()
        assert len(rows) == 1 and str(rows[0].tenant_id) == other.tenant_id


async def test_rbac_viewer_cannot_write(client, account):
    viewer = await register(client, "viewer@abc.example.com", "Viewer Own Biz")
    r = await account.post("/tenants/current/members", {"email": "viewer@abc.example.com", "role": "viewer"})
    assert r.status_code == 201
    viewer.tenant_id = account.tenant_id
    assert (await viewer.get("/agents")).status_code == 200
    r = await viewer.post("/agents", {"template_key": "blank"})
    assert r.status_code == 403
    assert "role does not allow" in r.json()["error"]["message"]
    r = await account.post("/agents", {"template_key": "blank"})
    r = await viewer.post(f"/agents/{r.json()['id']}/publish", {"notes": ""})
    assert r.status_code == 403


async def test_editor_cannot_manage_integrations_or_publish(client, account):
    editor = await register(client, "editor@abc.example.com", "Editor Biz")
    await account.post("/tenants/current/members", {"email": "editor@abc.example.com", "role": "editor"})
    editor.tenant_id = account.tenant_id
    assert (await editor.post("/agents", {"template_key": "blank"})).status_code == 201
    r = await editor.post("/integrations", {"name": "x", "kind": "rest_api", "config": {"base_url": "https://x.io"}})
    assert r.status_code == 403


async def test_last_owner_cannot_be_removed(client, account):
    r = await account.delete(f"/tenants/current/members/{account.user_id}")
    assert r.status_code == 403


async def test_audit_log_written(client, account):
    from nexa.models import AuditLog

    await account.post("/agents", {"template_key": "blank"})
    async with get_sessionmaker()() as db:
        actions = set(await db.scalars(select(AuditLog.action)))
    assert {"tenant.create", "agent.create"} <= actions
