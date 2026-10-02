"""Knowledge base: ingestion -> chunks -> pgvector retrieval with citations -> grounded answers."""

import io

from nexa.providers import registry
from nexa.providers.llm.scripted import ScriptedLLM

FAQ = [
    {"question": "ما هي أوقات الدوام؟", "answer": "نعمل من الأحد إلى الخميس من الساعة 4 عصراً حتى 10 مساءً."},
    {"question": "كم سعر الكشف؟", "answer": "سعر كشف الجلدية 250 ريال وكشف الأسنان 150 ريال."},
    {"question": "هل تقبلون التأمين؟", "answer": "نعم، نقبل تأمين بوبا والتعاونية."},
    {"question": "Where are you located?", "answer": "We are on King Fahd Road, Riyadh."},
]


async def make_kb(account) -> str:
    kb = (await account.post("/knowledge", {"name": "Clinic info"})).json()
    r = await account.post(f"/knowledge/{kb['id']}/documents", {"title": "FAQ", "source_type": "faq", "faq": FAQ})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ready" and r.json()["chunk_count"] == 4
    return kb["id"]


async def test_faq_ingestion_and_search(account):
    kb_id = await make_kb(account)
    res = (await account.post(f"/knowledge/{kb_id}/search", {"query": "كم سعر كشف الجلديه"})).json()["results"]
    assert "250" in res[0]["content"]
    assert res[0]["document_title"] == "FAQ" and res[0]["chunk_id"]
    res = (await account.post(f"/knowledge/{kb_id}/search", {"query": "where is the clinic located"})).json()["results"]
    assert "King Fahd" in res[0]["content"]


async def test_text_and_docx_documents(account):
    import docx

    kb = (await account.post("/knowledge", {"name": "Docs"})).json()
    r = await account.post(f"/knowledge/{kb['id']}/documents", {"title": "Policy", "source_type": "text",
                                                                "content": "سياسة الإلغاء: يجب الإلغاء قبل 24 ساعة."})
    assert r.json()["status"] == "ready"
    d = docx.Document()
    d.add_paragraph("Parking is free for patients in the basement.")
    buf = io.BytesIO()
    d.save(buf)
    r = await account.client.post(f"/knowledge/{kb['id']}/documents/upload", headers=account.headers,
                                  files={"file": ("info.docx", buf.getvalue())})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    r = await account.client.post(f"/knowledge/{kb['id']}/documents/upload", headers=account.headers,
                                  files={"file": ("virus.exe", b"MZ")})
    assert r.status_code == 422


async def test_tenant_isolation_of_knowledge(client, account):
    from tests.conftest import register

    kb_id = await make_kb(account)
    other = await register(client, "o@xyz.example.com", "Other")
    r = await other.post(f"/knowledge/{kb_id}/search", {"query": "سعر"})
    assert r.status_code == 404


async def test_agent_answers_from_knowledge_with_citations(account):
    kb_id = await make_kb(account)
    agent = (await account.post("/agents", {"template_key": "blank", "business_name": "ABC"})).json()
    cfg = {**agent["draft_config"], "knowledge_base_ids": [kb_id]}
    await account.put(f"/agents/{agent['id']}/config", cfg)
    llm = ScriptedLLM([{"tool": "search_knowledge", "arguments": {"query": "سعر كشف الجلدية"}},
                       "سعر كشف الجلدية 250 ريال."])
    registry.override("llm", llm)
    sid = (await account.post("/test/sessions", {"agent_id": agent["id"]})).json()["session_id"]
    r = (await account.post(f"/test/sessions/{sid}/messages", {"text": "كم سعر كشف الجلدية؟"})).json()["result"]
    data = r["tool_calls"][0]["data"]
    assert data["found"] and "250" in data["results"][0]["content"]
    assert data["results"][0]["citation"]["document_id"]
    assert r["replies"] == ["سعر كشف الجلدية 250 ريال."]


async def test_workflow_knowledge_answer_is_grounded_without_llm(account, clinic_db):
    """With no LLM available the workflow reads the matching passage instead of inventing an answer."""
    from nexa.providers.llm.base import LLMError
    from tests.conftest import setup_doctor_agent

    class Down(ScriptedLLM):
        async def generate(self, *a, **k):
            raise LLMError("offline")

    registry.override("llm", Down())
    kb_id = await make_kb(account)
    setup = await setup_doctor_agent(account)
    cfg = {**setup["agent"]["draft_config"], "knowledge_base_ids": [kb_id]}
    await account.put(f"/agents/{setup['agent']['id']}/config", cfg)
    sid = (await account.post("/test/sessions", {"agent_id": setup["agent"]["id"]})).json()["session_id"]
    r = (await account.post(f"/test/sessions/{sid}/messages", {"text": "هل تقبلون التأمين؟"})).json()["result"]
    assert "بوبا" in r["replies"][0]
    r = (await account.post(f"/test/sessions/{sid}/messages", {"text": "ايه"})).json()["result"]
    r = (await account.post(f"/test/sessions/{sid}/messages", {"text": "هل عندكم مواقف سيارات للطائرات؟"})).json()["result"]
    assert "ما عندي معلومة مؤكدة" in r["replies"][0]
