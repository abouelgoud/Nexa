"""The strongly-typed Agent definition.

This is the single source of truth for what an agent is allowed to do. The JSON
Schema generated from these models is committed to
``packages/agent-schema/agent-definition.schema.json`` and mirrored by the Zod
schema in ``packages/agent-schema/src/index.ts`` (a test keeps them in sync).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Language(StrEnum):
    ar = "ar"
    en = "en"


class ArabicDialect(StrEnum):
    sa = "sa"  # Saudi / Najdi
    gulf = "gulf"
    ae = "ae"  # Emirati
    kw = "kw"  # Kuwaiti
    qa = "qa"  # Qatari
    bh = "bh"  # Bahraini
    om = "om"  # Omani
    iq = "iq"  # Iraqi
    levant = "levant"
    eg = "eg"
    sd = "sd"
    ye = "ye"
    ly = "ly"
    tn = "tn"
    dz = "dz"
    ma = "ma"  # Moroccan / Darija
    ar = "ar"  # Modern Standard Arabic


DIALECT_LABELS: dict[str, tuple[str, str]] = {
    "sa": ("Saudi / Najdi", "سعودي / نجدي"),
    "gulf": ("Gulf", "خليجي"),
    "ae": ("Emirati", "إماراتي"),
    "kw": ("Kuwaiti", "كويتي"),
    "qa": ("Qatari", "قطري"),
    "bh": ("Bahraini", "بحريني"),
    "om": ("Omani", "عماني"),
    "iq": ("Iraqi", "عراقي"),
    "levant": ("Levantine", "شامي"),
    "eg": ("Egyptian", "مصري"),
    "sd": ("Sudanese", "سوداني"),
    "ye": ("Yemeni", "يمني"),
    "ly": ("Libyan", "ليبي"),
    "tn": ("Tunisian", "تونسي"),
    "dz": ("Algerian", "جزائري"),
    "ma": ("Moroccan / Darija", "مغربي / دارجة"),
    "ar": ("Modern Standard Arabic", "العربية الفصحى"),
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class LanguageBehavior(Strict):
    # match_caller: answer in the caller's language; fixed: always use primary_language
    mode: Literal["match_caller", "fixed"] = "match_caller"
    primary_language: Language = Language.ar
    code_switching: bool = True
    # Dialect the agent itself speaks when replying in Arabic.
    response_dialect: ArabicDialect | Literal["match_caller"] = "match_caller"


class VoiceConfig(Strict):
    provider: str = "local"
    voice_id: str = "default-ar"
    english_voice_id: str | None = "default-en"
    speed: float = Field(1.0, ge=0.5, le=2.0)


class Personality(Strict):
    tone: Literal["professional", "friendly", "warm", "formal", "energetic"] = "professional"
    verbosity: Literal["concise", "balanced", "detailed"] = "concise"
    custom_instructions: str = Field("", max_length=4000)


class Capability(StrEnum):
    answer_questions = "answer_questions"
    book_appointment = "book_appointment"
    cancel_appointment = "cancel_appointment"
    reschedule_appointment = "reschedule_appointment"
    get_appointment = "get_appointment"
    transfer_call = "transfer_call"
    take_order = "take_order"
    check_order_status = "check_order_status"
    make_reservation = "make_reservation"
    capture_lead = "capture_lead"
    collect_information = "collect_information"


class Policies(Strict):
    require_confirmation_for_booking: bool = True
    never_invent_information: bool = True
    human_handoff_enabled: bool = True


class OperatingDay(Strict):
    day: Literal["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
    open: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    close: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class TransferTarget(Strict):
    key: str = Field(..., pattern=r"^[a-z0-9_]{1,50}$")
    label: str
    phone_number: str = Field(..., pattern=r"^\+?[0-9]{3,20}$")
    only_during_business_hours: bool = False


class HandoffConfig(Strict):
    enabled: bool = True
    default_target: str | None = None
    targets: list[TransferTarget] = Field(default_factory=list)
    on_explicit_request: bool = True
    on_low_confidence: bool = True
    confidence_threshold: float = Field(0.5, ge=0, le=1)
    on_task_failure: bool = True
    after_hours_message: str = ""


class PrivacyConfig(Strict):
    record_calls: bool = False
    store_audio: bool = False
    store_transcript: bool = True
    retention_days: int = Field(30, ge=1, le=3650)
    consent_required: bool = False
    consent_message: str = ""


class GeneralSettings(Strict):
    business_name: str = ""
    industry: str = "general"
    greeting: str = ""
    greeting_en: str = ""
    timezone: str = "Asia/Riyadh"
    operating_hours: list[OperatingDay] = Field(default_factory=list)


class AgentDefinition(Strict):
    schema_version: Literal[1] = 1
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    languages: list[Language] = Field(default_factory=lambda: [Language.ar, Language.en], min_length=1)
    arabic_dialects: list[ArabicDialect] = Field(default_factory=lambda: list(ArabicDialect))
    language_behavior: LanguageBehavior = Field(default_factory=LanguageBehavior)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    personality: Personality = Field(default_factory=Personality)
    capabilities: list[Capability] = Field(default_factory=list)
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    tool_ids: list[UUID] = Field(default_factory=list)
    workflow_id: UUID | None = None
    # agent: LLM decides which tools to call; workflow: the visual workflow drives the call.
    execution_mode: Literal["agent", "workflow"] = "agent"
    policies: Policies = Field(default_factory=Policies)
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)

    @field_validator("languages", "arabic_dialects", "capabilities", "knowledge_base_ids", "tool_ids")
    @classmethod
    def _unique(cls, v: list) -> list:
        seen: list = []
        for item in v:
            if item not in seen:
                seen.append(item)
        return seen

    @model_validator(mode="after")
    def _consistency(self) -> AgentDefinition:
        if "ar" not in self.languages and self.arabic_dialects:
            self.arabic_dialects = []
        if self.language_behavior.primary_language not in self.languages:
            self.language_behavior.primary_language = self.languages[0]
        keys = [t.key for t in self.handoff.targets]
        if len(keys) != len(set(keys)):
            raise ValueError("Transfer destinations must have unique keys")
        if self.handoff.default_target and self.handoff.default_target not in keys:
            raise ValueError(f"Default transfer destination '{self.handoff.default_target}' does not exist")
        if self.execution_mode == "workflow" and self.workflow_id is None:
            raise ValueError("Workflow mode requires a workflow to be selected")
        return self


_GREETING_VARS = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_greeting(defn: AgentDefinition, language: str) -> str:
    text = defn.general.greeting_en if language == "en" and defn.general.greeting_en else defn.general.greeting
    return _GREETING_VARS.sub(lambda m: {"business_name": defn.general.business_name}.get(m.group(1), ""), text)
