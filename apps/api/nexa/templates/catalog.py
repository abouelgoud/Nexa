"""Template catalog. Templates are configuration only - the runtime is shared by all industries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nexa.templates import doctor_appointment


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    name_ar: str
    industry: str
    description: str
    needs_database: bool = False

    def definition(self, business_name: str) -> dict[str, Any]:
        if self.key == doctor_appointment.KEY:
            return doctor_appointment.definition(business_name)
        return _generic_definition(self, business_name)

    def tools(self, integration_id: UUID) -> list[dict[str, Any]]:
        if self.key == doctor_appointment.KEY:
            return doctor_appointment.tools(integration_id)
        return []

    def workflow(self) -> dict[str, Any] | None:
        if self.key == doctor_appointment.KEY:
            return doctor_appointment.workflow()
        return None

    def integration_permissions(self) -> dict[str, Any] | None:
        if self.key == doctor_appointment.KEY:
            return doctor_appointment.INTEGRATION_PERMISSIONS
        return None


_GENERIC = {
    "blank": ("Start from scratch", "ابدأ من الصفر", "general", ["answer_questions", "transfer_call"]),
    "restaurant_reservations": ("Restaurant reservations", "حجوزات المطاعم", "restaurant",
                                ["answer_questions", "make_reservation", "take_order", "transfer_call"]),
    "customer_support": ("Customer support", "خدمة العملاء", "customer_support",
                         ["answer_questions", "check_order_status", "transfer_call"]),
    "real_estate_leads": ("Real estate leads", "عملاء العقار", "real_estate",
                          ["answer_questions", "capture_lead", "book_appointment", "transfer_call"]),
    "hotel_front_desk": ("Hotel front desk", "استقبال الفندق", "hospitality",
                         ["answer_questions", "make_reservation", "transfer_call"]),
}

TEMPLATES: dict[str, Template] = {
    doctor_appointment.KEY: Template(
        key=doctor_appointment.KEY, name="Doctor appointment booking", name_ar="حجز مواعيد الأطباء",
        industry="healthcare", needs_database=True,
        description="Answers patients, finds doctors and free slots, books, cancels and reschedules appointments.",
    ),
    **{k: Template(key=k, name=v[0], name_ar=v[1], industry=v[2],
                   description=f"{v[0]} agent. Connect your systems and add actions to complete tasks.")
       for k, v in _GENERIC.items()},
}


def _generic_definition(t: Template, business_name: str) -> dict[str, Any]:
    caps = _GENERIC[t.key][3]
    return {
        "name": f"{business_name} {t.name}" if t.key != "blank" else f"{business_name} Assistant",
        "description": t.description,
        "general": {"business_name": business_name, "industry": t.industry,
                    "greeting": f"أهلاً وسهلاً بك في {business_name}. كيف أقدر أساعدك؟",
                    "greeting_en": f"Welcome to {business_name}. How can I help you?"},
        "capabilities": caps,
    }


def get_template(key: str) -> Template | None:
    return TEMPLATES.get(key)
