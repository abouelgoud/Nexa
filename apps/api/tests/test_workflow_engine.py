from datetime import datetime
from typing import Any

import pytest

from nexa.schemas.workflow import WorkflowGraph, validate_workflow
from nexa.templates.doctor_appointment import workflow as doctor_workflow
from nexa.tools.executor import ToolResult
from nexa.workflow.conditions import ConditionError, evaluate
from nexa.workflow.engine import KeywordNLU, WorkflowEngine, new_state

NOW = datetime(2026, 10, 2, 10, 0)  # Friday

SPECIALTIES = [{"id": 1, "name_ar": "الجلدية", "name_en": "Dermatology", "keywords": "جلد بشرة skin"},
               {"id": 2, "name_ar": "الأسنان", "name_en": "Dentistry", "keywords": "اسنان ضرس teeth"}]
DOCTORS = [{"id": 1, "name_ar": "د. سارة العتيبي", "name_en": "Dr. Sara"},
           {"id": 2, "name_ar": "د. خالد الحربي", "name_en": "Dr. Khalid"}]
SLOTS = [{"slot_id": 11, "doctor_id": 1, "slot_date": "2026-10-04", "slot_time": "18:30",
          "label_ar": "الأحد الساعة 6:30 مساءً", "label_en": "Sunday 6:30 PM"},
         {"slot_id": 12, "doctor_id": 2, "slot_date": "2026-10-05", "slot_time": "19:00",
          "label_ar": "الاثنين الساعة 7 مساءً", "label_en": "Monday 7:00 PM"}]


class FakeDeps(KeywordNLU):
    def __init__(self, patient_exists: bool = True, book_ok: bool = True):
        self.calls: list[tuple[str, dict[str, Any], bool]] = []
        self.patient_exists = patient_exists
        self.book_ok = book_ok

    async def run_tool(self, name, args, confirmed):
        self.calls.append((name, args, confirmed))
        def ok(records):
            return ToolResult("succeeded", name, data={"records": records, "record": records[0] if records else None,
                                                       "count": len(records)})
        if name == "list_specialties":
            return ok(SPECIALTIES)
        if name == "find_doctors":
            return ok(DOCTORS)
        if name == "get_available_slots":
            return ok(SLOTS)
        if name == "find_patient":
            return ok([{"id": 7, "full_name": "محمد"}] if self.patient_exists else [])
        if name == "register_patient":
            return ok([{"id": 8, "full_name": args["full_name"]}])
        if name == "book_appointment":
            if not confirmed:
                return ToolResult("confirmation_required", name)
            if not self.book_ok:
                return ToolResult("failed", name, error="conflict", error_code="conflict")
            return ok([{"id": 100}])
        if name == "transfer_call":
            return ToolResult("succeeded", name, data={}, action={"type": "transfer", "target": "reception"})
        raise AssertionError(name)

    async def search_knowledge(self, query):
        if "سعر" in query:
            return {"found": True, "answer": "سعر الكشف 200 ريال", "results": [{"document_title": "Prices"}]}
        return {"found": False, "answer": "", "results": []}


def make(deps, lang="ar"):
    graph = WorkflowGraph.model_validate(doctor_workflow())
    return WorkflowEngine(graph, deps, lang, NOW)


async def start(engine):
    state = new_state({"greeting": "السلام عليكم، كيف أقدر أخدمك؟", "caller_number": None})
    out = await engine.start(state)
    return state, out


async def test_doctor_template_graph_is_valid():
    graph = WorkflowGraph.model_validate(doctor_workflow())
    assert [i for i in validate_workflow(graph) if i.severity == "error"] == []


async def test_spec_conversation_books_only_after_confirmation():
    deps = FakeDeps()
    engine = make(deps)
    state, out = await start(engine)
    assert out.utterances == ["السلام عليكم، كيف أقدر أخدمك؟"]
    assert state["status"] == "waiting"

    # Specialty is extracted from the first sentence - no need to ask again.
    out = await engine.handle_input(state, "السلام عليكم، أبغى أحجز موعد جلدية.")
    assert state["variables"]["intent"] == "book"
    assert state["variables"]["specialty"]["value"] == 1
    assert out.utterances == ["هل تفضل طبيب معين؟"]

    out = await engine.handle_input(state, "لا")
    assert state["variables"]["doctor"]["value"] is None
    assert "الأحد الساعة 6:30 مساءً" in out.utterances[0] and "الاثنين الساعة 7 مساءً" in out.utterances[0]

    out = await engine.handle_input(state, "الاثنين")
    assert state["variables"]["slot"]["value"] == 12
    assert out.utterances == ["ممكن رقم جوالك عشان أسجل الموعد؟"]

    out = await engine.handle_input(state, "٠٥٠٠٠٠٠٠٠١")
    assert state["variables"]["phone"] == "+966500000001"
    assert out.utterances[0].startswith("ممتاز، هل أحجز لك موعد الجلدية الاثنين الساعة 7 مساءً")
    assert not any(c[0] == "book_appointment" for c in deps.calls)

    out = await engine.handle_input(state, "نعم")
    book = [c for c in deps.calls if c[0] == "book_appointment"]
    assert book == [("book_appointment", {"patient_id": 7, "doctor_id": 2, "slot_id": 12}, True)]
    assert out.utterances[0] == "تم الحجز بنجاح. موعدك الاثنين الساعة 7 مساءً."

    out = await engine.handle_input(state, "لا شكراً")
    assert state["status"] == "completed"
    assert {"type": "end_call"} in out.actions


async def test_declining_confirmation_does_not_book():
    deps = FakeDeps()
    engine = make(deps)
    state, _ = await start(engine)
    for text in ["أبغى موعد جلدية", "لا", "الأحد", "0500000001"]:
        await engine.handle_input(state, text)
    out = await engine.handle_input(state, "لا")
    assert not any(c[0] == "book_appointment" for c in deps.calls)
    assert "أي موعد يناسبك" in out.utterances[-1]


async def test_failed_booking_never_claims_success():
    deps = FakeDeps(book_ok=False)
    engine = make(deps)
    state, _ = await start(engine)
    for text in ["أبغى موعد جلدية", "لا", "الأحد", "0500000001"]:
        await engine.handle_input(state, text)
    out = await engine.handle_input(state, "نعم")
    assert not any("تم الحجز" in u for u in out.utterances)
    assert "ما قدرت أكمل الحجز" in out.utterances[0]


async def test_new_patient_is_registered():
    deps = FakeDeps(patient_exists=False)
    engine = make(deps)
    state, _ = await start(engine)
    for text in ["أبغى موعد جلدية", "لا", "الأحد"]:
        await engine.handle_input(state, text)
    out = await engine.handle_input(state, "0551112222")
    assert out.utterances == ["ما اسمك الكامل؟"]
    out = await engine.handle_input(state, "سارة أحمد")
    assert ("register_patient", {"full_name": "سارة أحمد", "phone": "+966551112222"}, False) in deps.calls
    assert out.utterances[0].startswith("ممتاز، هل أحجز")


async def test_retry_then_transfer_when_not_understood():
    deps = FakeDeps()
    engine = make(deps)
    state, _ = await start(engine)
    out = await engine.handle_input(state, "أبغى أحجز موعد")
    assert out.utterances == ["أكيد. أي تخصص تحتاج؟"]
    out = await engine.handle_input(state, "ما أدري")
    assert out.utterances[0].startswith("عذراً، ما فهمت عليك.")
    out = await engine.handle_input(state, "شيء ثاني")
    assert state["status"] == "transferred"
    assert out.actions[-1]["type"] == "transfer"


async def test_human_intent_transfers():
    deps = FakeDeps()
    engine = make(deps)
    state, _ = await start(engine)
    out = await engine.handle_input(state, "أبغى أكلم موظف الاستقبال")
    assert state["status"] == "transferred"
    assert out.actions[-1]["type"] == "transfer"


async def test_knowledge_question_and_unknown():
    deps = FakeDeps()
    engine = make(deps)
    state, _ = await start(engine)
    out = await engine.handle_input(state, "كم سعر الكشف؟")
    assert out.utterances == ["سعر الكشف 200 ريال", "تحتاج أي شيء ثاني؟"]
    await engine.handle_input(state, "نعم")
    out = await engine.handle_input(state, "وين موقعكم؟")
    assert "ما عندي معلومة مؤكدة" in out.utterances[0]


async def test_english_conversation_uses_english_texts():
    deps = FakeDeps()
    engine = make(deps, "en")
    state = new_state({"greeting": "Hello, how can I help?"})
    await engine.start(state)
    out = await engine.handle_input(state, "I want to book a dermatology appointment")
    assert out.utterances == ["Do you prefer a specific doctor?"]
    out = await engine.handle_input(state, "no preference")
    assert out.utterances[0].startswith("I have Sunday 6:30 PM or Monday 7:00 PM")
    out = await engine.handle_input(state, "Sunday at 6:30")
    assert state["variables"]["slot"]["value"] == 11


def test_condition_evaluator():
    v = {"intent": "book", "slots": {"records": [1, 2]}, "patient": {"record": None}}
    assert evaluate('intent == "book" and not empty(slots.records)', v)
    assert evaluate("count(slots.records) >= 2", v)
    assert evaluate("empty(patient.record)", v)
    assert not evaluate("missing.value == 1", v)


@pytest.mark.parametrize("expr", ["__import__('os').system('id')", "open('/etc/passwd')", "(lambda: 1)()",
                                  "slots.__class__", "[x for x in slots]"])
def test_condition_evaluator_rejects_code(expr):
    with pytest.raises(ConditionError):
        evaluate(expr, {"slots": []})
