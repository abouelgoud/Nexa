"""Doctor appointment booking template.

The template is pure configuration on top of the generic platform: an agent
definition, database actions (generic ``search_records``/``create_record``/
``update_record`` against the clinic's own tables) and a workflow graph. No
clinic-specific code exists in the runtime.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

KEY = "doctor_appointment"

INTEGRATION_PERMISSIONS: dict[str, Any] = {
    "tables": {
        "clinic.patients": {
            "operations": ["read", "create"],
            "fields": {"id": "read", "full_name": "read_write", "phone": "read_write",
                       "national_id": "deny", "medical_notes": "deny", "date_of_birth": "deny"},
        },
        "clinic.specialties": {"operations": ["read"],
                               "fields": {"id": "read", "name_ar": "read", "name_en": "read", "keywords": "read"}},
        "clinic.doctors": {"operations": ["read"], "fields": {"id": "read", "name_ar": "read", "name_en": "read",
                                                              "specialty_id": "read", "active": "read"}},
        "clinic.available_slots": {
            "operations": ["read"],
            "fields": {f: "read" for f in ["slot_id", "doctor_id", "doctor_name_ar", "doctor_name_en", "specialty_id",
                                           "specialty_name_ar", "specialty_name_en", "starts_at", "slot_date",
                                           "slot_time", "label_ar", "label_en"]},
        },
        "clinic.appointments": {
            "operations": ["read", "create", "update"],
            "fields": {"id": "read", "patient_id": "read_write", "doctor_id": "read_write", "slot_id": "read_write",
                       "status": "read_write"},
        },
        "clinic.appointment_details": {
            "operations": ["read"],
            "fields": {f: "read" for f in ["appointment_id", "patient_id", "status", "doctor_id", "slot_id",
                                           "doctor_name_ar", "doctor_name_en", "specialty_name_ar",
                                           "specialty_name_en", "starts_at", "label_ar", "label_en"]},
        },
    }
}


def definition(business_name: str = "عيادة") -> dict[str, Any]:
    return {
        "name": f"{business_name} Receptionist",
        "description": f"AI receptionist for {business_name}: books, cancels and reschedules appointments.",
        "general": {
            "business_name": business_name,
            "industry": "healthcare",
            "greeting": f"السلام عليكم، معك المساعد الذكي في {business_name}. كيف أقدر أخدمك؟",
            "greeting_en": f"Hello, you've reached the AI assistant at {business_name}. How can I help you?",
            "timezone": "Asia/Riyadh",
            "operating_hours": [{"day": d, "open": "16:00", "close": "22:00"}
                                for d in ["sun", "mon", "tue", "wed", "thu"]],
        },
        "languages": ["ar", "en"],
        "language_behavior": {"mode": "match_caller", "primary_language": "ar", "code_switching": True,
                              "response_dialect": "match_caller"},
        "voice": {"provider": "local", "voice_id": "ar_JO-kareem-medium", "english_voice_id": "en_US-amy-medium"},
        "personality": {"tone": "warm", "verbosity": "concise", "custom_instructions": ""},
        "capabilities": ["answer_questions", "book_appointment", "cancel_appointment", "reschedule_appointment",
                         "get_appointment", "transfer_call"],
        "policies": {"require_confirmation_for_booking": True, "never_invent_information": True,
                     "human_handoff_enabled": True},
        "handoff": {"enabled": True, "default_target": "reception",
                    "targets": [{"key": "reception", "label": "Reception", "phone_number": "+966110000000"}]},
        "privacy": {"record_calls": False, "store_audio": False, "store_transcript": True, "retention_days": 30,
                    "consent_required": False, "consent_message": ""},
    }


def _db(integration_id: UUID, **cfg: Any) -> dict[str, Any]:
    return {"integration_id": str(integration_id), "db_schema": "clinic", **cfg}


def tools(integration_id: UUID) -> list[dict[str, Any]]:
    i = integration_id
    s = "string"
    integer = "integer"
    return [
        {"name": "find_patient", "display_name": "Find patient", "category": "database", "executor": "database",
         "description": "Find a patient record by phone number.",
         "input_schema": {"type": "object", "properties": {"phone": {"type": s, "description": "Phone in +966... format"}},
                          "required": ["phone"]},
         "config": _db(i, operation="search_records", table="patients", limit=1,
                       filters=[{"field": "phone", "op": "eq", "arg": "phone"}],
                       return_fields=["id", "full_name", "phone"])},
        {"name": "register_patient", "display_name": "Register patient", "category": "database",
         "executor": "database", "description": "Create a new patient record with name and phone number.",
         "input_schema": {"type": "object", "properties": {"full_name": {"type": s}, "phone": {"type": s}},
                          "required": ["full_name", "phone"]},
         "config": _db(i, operation="create_record", table="patients",
                       values={"full_name": "{{full_name}}", "phone": "{{phone}}"},
                       return_fields=["id", "full_name", "phone"])},
        {"name": "list_specialties", "display_name": "List specialties", "category": "database",
         "executor": "database", "description": "List the clinic's medical specialties with their ids.",
         "input_schema": {"type": "object", "properties": {}},
         "config": _db(i, operation="search_records", table="specialties", limit=50,
                       return_fields=["id", "name_ar", "name_en", "keywords"], order_by=["id"])},
        {"name": "find_doctors", "display_name": "Find doctors", "category": "database", "executor": "database",
         "description": "Find active doctors, optionally for one specialty.",
         "input_schema": {"type": "object", "properties": {"specialty_id": {"type": integer}}},
         "config": _db(i, operation="search_records", table="doctors", limit=20,
                       filters=[{"field": "specialty_id", "op": "eq", "arg": "specialty_id", "optional": True},
                                {"field": "active", "op": "eq", "value": True}],
                       return_fields=["id", "name_ar", "name_en", "specialty_id"], order_by=["id"])},
        {"name": "get_available_slots", "display_name": "Get available slots", "category": "calendar",
         "executor": "database",
         "description": "Get the next free appointment slots for a specialty and/or doctor, optionally on a date "
                        "(YYYY-MM-DD) or from a date.",
         "input_schema": {"type": "object", "properties": {
             "specialty_id": {"type": integer}, "doctor_id": {"type": integer},
             "date": {"type": s, "format": "date"}, "from_date": {"type": s, "format": "date"}}},
         "config": _db(i, operation="search_records", table="available_slots", limit=3, order_by=["starts_at"],
                       filters=[{"field": "specialty_id", "op": "eq", "arg": "specialty_id", "optional": True},
                                {"field": "doctor_id", "op": "eq", "arg": "doctor_id", "optional": True},
                                {"field": "slot_date", "op": "eq", "arg": "date", "optional": True},
                                {"field": "slot_date", "op": "gte", "arg": "from_date", "optional": True}],
                       return_fields=["slot_id", "doctor_id", "doctor_name_ar", "doctor_name_en",
                                      "specialty_name_ar", "slot_date", "slot_time", "label_ar", "label_en"])},
        {"name": "book_appointment", "display_name": "Book appointment", "category": "calendar",
         "executor": "database", "requires_confirmation": True,
         "confirmation_template": "Book {slot_id} for patient {patient_id}",
         "description": "Book an appointment slot for a patient. Requires the caller's explicit confirmation.",
         "input_schema": {"type": "object", "properties": {
             "patient_id": {"type": integer}, "doctor_id": {"type": integer}, "slot_id": {"type": integer}},
             "required": ["patient_id", "doctor_id", "slot_id"]},
         "config": _db(i, operation="create_record", table="appointments",
                       values={"patient_id": "{{patient_id}}", "doctor_id": "{{doctor_id}}",
                               "slot_id": "{{slot_id}}", "status": "booked"},
                       return_fields=["id", "patient_id", "doctor_id", "slot_id", "status"])},
        {"name": "get_appointments", "display_name": "Get appointments", "category": "calendar",
         "executor": "database", "description": "Get a patient's upcoming booked appointments.",
         "input_schema": {"type": "object", "properties": {"patient_id": {"type": integer}},
                          "required": ["patient_id"]},
         "config": _db(i, operation="search_records", table="appointment_details", limit=5, order_by=["starts_at"],
                       filters=[{"field": "patient_id", "op": "eq", "arg": "patient_id"},
                                {"field": "status", "op": "eq", "value": "booked"}],
                       return_fields=["appointment_id", "doctor_name_ar", "doctor_name_en", "specialty_name_ar",
                                      "starts_at", "label_ar", "label_en", "slot_id", "doctor_id"])},
        {"name": "cancel_appointment", "display_name": "Cancel appointment", "category": "calendar",
         "executor": "database", "requires_confirmation": True,
         "description": "Cancel one of the patient's appointments. Requires the caller's explicit confirmation.",
         "input_schema": {"type": "object", "properties": {"appointment_id": {"type": integer},
                                                           "patient_id": {"type": integer}},
                          "required": ["appointment_id", "patient_id"]},
         "config": _db(i, operation="update_record", table="appointments", values={"status": "cancelled"},
                       filters=[{"field": "id", "op": "eq", "arg": "appointment_id"},
                                {"field": "patient_id", "op": "eq", "arg": "patient_id"},
                                {"field": "status", "op": "eq", "value": "booked"}],
                       return_fields=["id", "status"])},
        {"name": "reschedule_appointment", "display_name": "Reschedule appointment", "category": "calendar",
         "executor": "database", "requires_confirmation": True,
         "description": "Move a patient's appointment to another free slot. Requires explicit confirmation.",
         "input_schema": {"type": "object", "properties": {
             "appointment_id": {"type": integer}, "patient_id": {"type": integer},
             "new_slot_id": {"type": integer}, "new_doctor_id": {"type": integer}},
             "required": ["appointment_id", "patient_id", "new_slot_id", "new_doctor_id"]},
         "config": _db(i, operation="update_record", table="appointments",
                       values={"slot_id": "{{new_slot_id}}", "doctor_id": "{{new_doctor_id}}"},
                       filters=[{"field": "id", "op": "eq", "arg": "appointment_id"},
                                {"field": "patient_id", "op": "eq", "arg": "patient_id"},
                                {"field": "status", "op": "eq", "value": "booked"}],
                       return_fields=["id", "slot_id", "doctor_id", "status"])},
    ]


INTENTS = {
    "book": ["احجز", "أحجز", "حجز", "موعد", "معاد", "ميعاد", "book", "appointment", "booking", "schedule"],
    "cancel": ["الغي", "ألغي", "الغاء", "إلغاء", "كنسل", "cancel"],
    "human": ["موظف", "الاستقبال", "شخص", "انسان", "human", "reception", "person", "agent"],
    "question": ["كم", "سعر", "اسعار", "وين", "موقع", "متى", "دوام", "تأمين", "price", "cost", "where", "hours",
                 "insurance", "location", "open"],
}


def _n(nid: str, ntype: str, label: str, x: float, y: float, **config: Any) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "label": label, "config": config, "position": {"x": x, "y": y}}


def _e(src: str, dst: str, handle: str = "default", condition: str | None = None, label: str = "") -> dict[str, Any]:
    return {"id": f"{src}__{handle}__{dst}", "source": src, "target": dst, "handle": handle,
            "condition": condition, "label": label or ("" if handle == "default" else handle)}


def workflow() -> dict[str, Any]:
    nodes = [
        _n("start", "start", "Start", 0, 0),
        _n("ask_intent", "ask", "How can I help?", 0, 120, question="{{greeting}}",
           question_en="{{greeting}}", revisit_question="تفضل، كيف أقدر أساعدك؟",
           revisit_question_en="Sure, how else can I help?", variable="request", intents=INTENTS),
        # --- booking ---
        _n("load_specialties", "tool", "Load specialties", -400, 260, tool="list_specialties", arguments={},
           result_variable="specialties"),
        _n("collect_specialty", "collect", "Which specialty?", -400, 380, variable="specialty", type="choice",
           prompt="أكيد. أي تخصص تحتاج؟", prompt_en="Sure. Which specialty do you need?",
           options_from="specialties.records", label_fields=["name_ar", "name_en", "keywords"], value_field="id",
           display_field="name", prefill_from="request", max_attempts=2),
        _n("load_doctors", "tool", "Find doctors", -400, 500, tool="find_doctors",
           arguments={"specialty_id": "{{specialty.value}}"}, result_variable="doctors"),
        _n("collect_doctor", "collect", "Preferred doctor?", -400, 620, variable="doctor", type="choice",
           prompt="هل تفضل طبيب معين؟", prompt_en="Do you prefer a specific doctor?",
           options_from="doctors.records", label_fields=["name_ar", "name_en"], value_field="id",
           display_field="name", optional=True, max_attempts=1),
        _n("load_slots", "tool", "Get available slots", -400, 740, tool="get_available_slots",
           arguments={"specialty_id": "{{specialty.value}}", "doctor_id": "{{doctor.value}}"},
           result_variable="slots"),
        _n("has_slots", "condition", "Any free slots?", -400, 860),
        _n("no_slots", "say", "No slots", -700, 980,
           text="للأسف ما عندي مواعيد متاحة حالياً لهذا التخصص.",
           text_en="Unfortunately there are no available appointments for this specialty right now."),
        _n("collect_slot", "collect", "Choose a slot", -400, 980, variable="slot", type="choice", match="datetime",
           date_field="slot_date", time_field="slot_time",
           prompt="عندي {{slots.records|list:label}}. أي موعد يناسبك؟",
           prompt_en="I have {{slots.records|list:label}}. Which one suits you?",
           options_from="slots.records", label_fields=["label_ar", "label_en"], value_field="slot_id",
           display_field="label", max_attempts=2),
        _n("collect_phone", "collect", "Phone number", -400, 1100, variable="phone", type="phone",
           prompt="ممكن رقم جوالك عشان أسجل الموعد؟", prompt_en="May I have your mobile number for the booking?",
           prefill_from="caller_number", max_attempts=2),
        _n("find_patient", "tool", "Find patient", -400, 1220, tool="find_patient",
           arguments={"phone": "{{phone}}"}, result_variable="patient"),
        _n("patient_known", "condition", "Existing patient?", -400, 1340),
        _n("collect_name", "collect", "Patient name", -700, 1460, variable="full_name", type="text",
           prompt="ما اسمك الكامل؟", prompt_en="What is your full name?"),
        _n("register_patient", "tool", "Register patient", -700, 1580, tool="register_patient",
           arguments={"full_name": "{{full_name}}", "phone": "{{phone}}"}, result_variable="patient"),
        _n("confirm_booking", "confirm", "Confirm booking", -400, 1700,
           text="ممتاز، هل أحجز لك موعد {{specialty.label}} {{slot.label}}؟",
           text_en="Great, shall I book your {{specialty.label}} appointment on {{slot.label}}?"),
        _n("book", "tool", "Book appointment", -400, 1820, tool="book_appointment", confirmed_by="confirm_booking",
           arguments={"patient_id": "{{patient.record.id}}", "doctor_id": "{{slot.record.doctor_id}}",
                      "slot_id": "{{slot.value}}"}, result_variable="booking"),
        _n("booked", "say", "Booked", -400, 1940, text="تم الحجز بنجاح. موعدك {{slot.label}}.",
           text_en="Your appointment is booked: {{slot.label}}."),
        _n("book_failed", "say", "Booking failed", -700, 1940,
           text="للأسف ما قدرت أكمل الحجز، يمكن الموعد انحجز للتو. خلني أشوف لك مواعيد ثانية.",
           text_en="Sorry, I couldn't complete the booking - the slot may have just been taken. Let me check other times."),
        # --- cancellation ---
        _n("cancel_phone", "collect", "Phone number", 0, 260, variable="phone", type="phone",
           prompt="ممكن رقم الجوال المسجل عندنا؟", prompt_en="What phone number is the booking under?",
           prefill_from="caller_number", max_attempts=2),
        _n("cancel_find_patient", "tool", "Find patient", 0, 380, tool="find_patient",
           arguments={"phone": "{{phone}}"}, result_variable="patient"),
        _n("cancel_load", "tool", "Get appointments", 0, 500, tool="get_appointments",
           arguments={"patient_id": "{{patient.record.id}}"}, result_variable="appointments"),
        _n("has_appointments", "condition", "Has appointments?", 0, 620),
        _n("no_appointments", "say", "No appointments", 300, 740, text="ما لقيت مواعيد محجوزة على هذا الرقم.",
           text_en="I couldn't find any booked appointments for this number."),
        _n("collect_appointment", "collect", "Which appointment?", 0, 740, variable="appointment", type="choice",
           match="datetime", date_field="starts_at",
           prompt="عندك {{appointments.records|list:label}}. أي موعد تبغى تلغي؟",
           prompt_en="You have {{appointments.records|list:label}}. Which one should I cancel?",
           options_from="appointments.records", label_fields=["label_ar", "label_en"], value_field="appointment_id",
           display_field="label", auto_select_single=True, max_attempts=2),
        _n("confirm_cancel", "confirm", "Confirm cancellation", 0, 860,
           text="هل أنت متأكد إنك تبغى تلغي موعد {{appointment.label}}؟",
           text_en="Are you sure you want to cancel your appointment on {{appointment.label}}?"),
        _n("cancel", "tool", "Cancel appointment", 0, 980, tool="cancel_appointment", confirmed_by="confirm_cancel",
           arguments={"appointment_id": "{{appointment.value}}", "patient_id": "{{patient.record.id}}"},
           result_variable="cancellation"),
        _n("cancelled", "say", "Cancelled", 0, 1100, text="تم إلغاء الموعد.",
           text_en="Your appointment has been cancelled."),
        # --- questions ---
        _n("kb_search", "knowledge_search", "Search knowledge", 400, 260, query="{{request}}",
           result_variable="knowledge"),
        _n("kb_answer", "say", "Answer", 400, 380, text="{{knowledge.answer}}", text_en="{{knowledge.answer}}"),
        _n("kb_unknown", "confirm", "Unknown - offer human", 700, 380,
           text="ما عندي معلومة مؤكدة عن هذا. تبغى أحولك على الاستقبال؟",
           text_en="I don't have confirmed information about that. Would you like me to transfer you to reception?"),
        # --- shared ---
        _n("anything_else", "confirm", "Anything else?", 0, 2060, text="تحتاج أي شيء ثاني؟",
           text_en="Is there anything else I can help with?"),
        _n("tech_failure", "say", "Technical problem", 400, 1820,
           text="عذراً، واجهت مشكلة تقنية.", text_en="Sorry, I ran into a technical problem."),
        _n("transfer_reception", "transfer", "Transfer to reception", 400, 1940, target="reception",
           text="لحظة من فضلك، بحولك على موظف الاستقبال.", text_en="One moment please, transferring you to reception."),
        _n("end", "end", "Goodbye", 0, 2180, text="شكراً لاتصالك، مع السلامة.",
           text_en="Thank you for calling. Goodbye!"),
    ]
    edges = [
        _e("start", "ask_intent"),
        _e("ask_intent", "load_specialties", "book"),
        _e("ask_intent", "cancel_phone", "cancel"),
        _e("ask_intent", "transfer_reception", "human"),
        _e("ask_intent", "kb_search", "question"),
        _e("ask_intent", "kb_search", "default"),
        _e("load_specialties", "collect_specialty", "success"),
        _e("load_specialties", "tech_failure", "error"),
        _e("collect_specialty", "load_doctors"),
        _e("collect_specialty", "transfer_reception", "failed"),
        _e("load_doctors", "collect_doctor", "success"),
        _e("load_doctors", "tech_failure", "error"),
        _e("collect_doctor", "load_slots"),
        _e("collect_doctor", "load_slots", "failed"),
        _e("load_slots", "has_slots", "success"),
        _e("load_slots", "tech_failure", "error"),
        _e("has_slots", "collect_slot", "available", condition="not empty(slots.records)"),
        _e("has_slots", "no_slots", "else", condition="else"),
        _e("no_slots", "anything_else"),
        _e("collect_slot", "collect_phone"),
        _e("collect_slot", "transfer_reception", "failed"),
        _e("collect_phone", "find_patient"),
        _e("collect_phone", "transfer_reception", "failed"),
        _e("find_patient", "patient_known", "success"),
        _e("find_patient", "tech_failure", "error"),
        _e("patient_known", "confirm_booking", "known", condition="not empty(patient.record)"),
        _e("patient_known", "collect_name", "else", condition="else"),
        _e("collect_name", "register_patient"),
        _e("register_patient", "confirm_booking", "success"),
        _e("register_patient", "tech_failure", "error"),
        _e("confirm_booking", "book", "yes"),
        _e("confirm_booking", "collect_slot", "no"),
        _e("book", "booked", "success"),
        _e("book", "book_failed", "error"),
        _e("book_failed", "load_slots"),
        _e("booked", "anything_else"),
        _e("cancel_phone", "cancel_find_patient"),
        _e("cancel_phone", "transfer_reception", "failed"),
        _e("cancel_find_patient", "cancel_load", "success"),
        _e("cancel_find_patient", "tech_failure", "error"),
        _e("cancel_load", "has_appointments", "success"),
        _e("cancel_load", "no_appointments", "error"),
        _e("has_appointments", "collect_appointment", "found", condition="not empty(appointments.records)"),
        _e("has_appointments", "no_appointments", "else", condition="else"),
        _e("no_appointments", "anything_else"),
        _e("collect_appointment", "confirm_cancel"),
        _e("collect_appointment", "transfer_reception", "failed"),
        _e("confirm_cancel", "cancel", "yes"),
        _e("confirm_cancel", "anything_else", "no"),
        _e("cancel", "cancelled", "success"),
        _e("cancel", "tech_failure", "error"),
        _e("cancelled", "anything_else"),
        _e("kb_search", "kb_answer", "found"),
        _e("kb_search", "kb_unknown", "not_found"),
        _e("kb_answer", "anything_else"),
        _e("kb_unknown", "transfer_reception", "yes"),
        _e("kb_unknown", "anything_else", "no"),
        _e("anything_else", "ask_intent", "yes"),
        _e("anything_else", "end", "no"),
        _e("tech_failure", "transfer_reception"),
    ]
    return {"nodes": nodes, "edges": edges}
