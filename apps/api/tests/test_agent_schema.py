import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexa.schemas.agent_definition import AgentDefinition, render_greeting
from nexa.templates.catalog import TEMPLATES

SCHEMA_FILE = Path(__file__).resolve().parents[3] / "packages" / "agent-schema" / "agent-definition.schema.json"

EXAMPLE = {
    "name": "ABC Receptionist",
    "description": "AI receptionist for ABC Clinic",
    "languages": ["ar", "en"],
    "arabic_dialects": ["sa", "gulf", "eg", "levant", "iq", "ye", "sd", "ma", "dz", "tn", "ly", "ar"],
    "language_behavior": {"mode": "match_caller", "code_switching": True},
    "voice": {"provider": "local", "voice_id": "default-ar"},
    "personality": {"tone": "professional", "verbosity": "concise"},
    "capabilities": ["answer_questions", "book_appointment", "cancel_appointment", "reschedule_appointment",
                     "transfer_call"],
    "knowledge_base_ids": [],
    "tool_ids": [],
    "workflow_id": str(uuid.uuid4()),
    "policies": {"require_confirmation_for_booking": True, "never_invent_information": True,
                 "human_handoff_enabled": True},
}


def test_spec_example_is_valid():
    d = AgentDefinition.model_validate(EXAMPLE)
    assert d.languages == ["ar", "en"]
    assert d.language_behavior.code_switching is True
    assert d.execution_mode == "agent"


def test_defaults_are_sensible():
    d = AgentDefinition(name="Agent")
    assert d.languages == ["ar", "en"]
    assert "ar" in d.arabic_dialects and "eg" in d.arabic_dialects
    assert d.policies.require_confirmation_for_booking
    assert d.privacy.store_audio is False and d.privacy.record_calls is False


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({**EXAMPLE, "secret_api_key": "x"})


def test_invalid_dialect_rejected():
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({**EXAMPLE, "arabic_dialects": ["klingon"]})


def test_duplicates_removed_and_dialects_cleared_without_arabic():
    d = AgentDefinition.model_validate({**EXAMPLE, "languages": ["en", "en"]})
    assert d.languages == ["en"]
    assert d.arabic_dialects == []
    assert d.language_behavior.primary_language == "en"


def test_workflow_mode_requires_workflow():
    with pytest.raises(ValidationError, match="Workflow mode requires"):
        AgentDefinition.model_validate({**EXAMPLE, "workflow_id": None, "execution_mode": "workflow"})


def test_handoff_default_target_must_exist():
    with pytest.raises(ValidationError, match="does not exist"):
        AgentDefinition.model_validate({**EXAMPLE, "handoff": {"default_target": "sales", "targets": []}})


def test_greeting_rendering_by_language():
    d = AgentDefinition.model_validate({**EXAMPLE, "general": {
        "business_name": "ABC", "greeting": "أهلاً بك في {{business_name}}", "greeting_en": "Welcome to {{business_name}}"}})
    assert render_greeting(d, "ar") == "أهلاً بك في ABC"
    assert render_greeting(d, "en") == "Welcome to ABC"


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_all_templates_produce_valid_definitions(key):
    AgentDefinition.model_validate(TEMPLATES[key].definition("Biz"))


def test_committed_json_schema_is_in_sync():
    """packages/agent-schema/agent-definition.schema.json must be regenerated when the model changes
    (run: python apps/api/scripts/export_schemas.py)."""
    committed = json.loads(SCHEMA_FILE.read_text())
    assert committed == AgentDefinition.model_json_schema()
