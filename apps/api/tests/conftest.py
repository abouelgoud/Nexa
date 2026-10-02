"""Test configuration: a real PostgreSQL database (pgvector) and the demo clinic database.

Environment overrides:
  TEST_DATABASE_ADMIN_URL  superuser URL used to (re)create the test database
  TEST_CLINIC_ADMIN_URL    superuser URL of the demo clinic database (reset between tests)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
TEST_DB = os.environ.get("TEST_DATABASE_NAME", "nexa_test")
CLINIC_ADMIN_URL = os.environ.get("TEST_CLINIC_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/clinic_demo")
_base = ADMIN_URL.rsplit("/", 1)[0]

os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"{_base.replace('postgresql://', 'postgresql+asyncpg://')}/{TEST_DB}",
    "JOBS_INLINE": "true",
    "ALLOW_PRIVATE_NETWORK_INTEGRATIONS": "true",
    "LLM_PROVIDER": "scripted",
    "STT_PROVIDER": "none",
    "TTS_PROVIDER": "none",
    "SIP_PROVIDER": "none",
    "EMBEDDING_PROVIDER": "hashing",
    "DEMO_CLINIC_DATABASE_URL": os.environ.get(
        "TEST_DEMO_CLINIC_URL", "postgresql://clinic_agent:clinic_agent@localhost:5432/clinic_demo"),
})

import asyncpg  # noqa: E402
import httpx  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def _create_db() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database():
    _run(_create_db())
    env = {**os.environ}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True,
                   capture_output=True)
    yield


TABLES_TO_KEEP = {"alembic_version"}


@pytest.fixture(autouse=True)
async def clean_db(database):
    from sqlalchemy import text

    from nexa.core.db import get_engine
    from nexa.providers import registry

    engine = get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        tables = [r[0] for r in rows if r[0] not in TABLES_TO_KEEP]
        await conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
    yield
    for kind in ("llm", "stt", "tts", "embeddings", "sip"):
        registry.override(kind, None)


@pytest.fixture
async def clinic_db():
    """Reset the demo clinic's mutable data. Skips if the clinic database is not available."""
    try:
        conn = await asyncpg.connect(CLINIC_ADMIN_URL)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"clinic demo database not available: {exc}")
    try:
        await conn.execute("DELETE FROM clinic.appointments")
        await conn.execute("DELETE FROM clinic.patients WHERE phone NOT IN ('+966500000001', '+966500000002')")
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def client():
    from nexa.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


class Account:
    def __init__(self, client: httpx.AsyncClient, token: str, tenant_id: str, user_id: str):
        self.client, self.token, self.tenant_id, self.user_id = client, token, tenant_id, user_id

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Tenant-ID": self.tenant_id}

    async def get(self, url: str, **kw):
        return await self.client.get(url, headers=self.headers, **kw)

    async def post(self, url: str, json=None, **kw):
        return await self.client.post(url, json=json, headers=self.headers, **kw)

    async def put(self, url: str, json=None, **kw):
        return await self.client.put(url, json=json, headers=self.headers, **kw)

    async def patch(self, url: str, json=None, **kw):
        return await self.client.patch(url, json=json, headers=self.headers, **kw)

    async def delete(self, url: str, **kw):
        return await self.client.delete(url, headers=self.headers, **kw)


async def register(client: httpx.AsyncClient, email: str, tenant: str = "ABC Clinic") -> Account:
    r = await client.post("/auth/register", json={"email": email, "password": "secret-pass-123",
                                                  "full_name": "Test User", "tenant_name": tenant})
    assert r.status_code == 201, r.text
    data = r.json()
    return Account(client, data["access_token"], data["memberships"][0]["tenant_id"], data["user"]["id"])


@pytest.fixture
async def account(client) -> Account:
    return await register(client, "owner@abc.example.com")


async def setup_doctor_agent(acc: Account, mode: str = "workflow") -> dict:
    """Create the doctor template agent connected to the demo clinic database."""
    r = await acc.post("/agents", {"template_key": "doctor_appointment", "business_name": "عيادة ABC"})
    assert r.status_code == 201, r.text
    agent = r.json()
    r = await acc.post("/integrations/demo-clinic")
    assert r.status_code == 201, r.text
    integ = r.json()
    r = await acc.post(f"/agents/{agent['id']}/template/setup", {"integration_id": integ["id"]})
    assert r.status_code == 200, r.text
    agent = r.json()
    config = agent["draft_config"]
    config["execution_mode"] = mode
    r = await acc.put(f"/agents/{agent['id']}/config", config)
    assert r.status_code == 200, r.text
    return {"agent": r.json(), "integration": integ}
