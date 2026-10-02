"""Request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field("", max_length=200)
    tenant_name: str | None = Field(None, max_length=200)
    locale: str = "en"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: UUID
    email: str
    full_name: str
    locale: str


class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    memberships: list[MembershipOut]


class TenantIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    industry: str | None = None
    default_timezone: str = "Asia/Riyadh"


class TenantOut(ORM):
    id: UUID
    name: str
    slug: str
    industry: str | None
    default_timezone: str
    plan: str
    created_at: datetime


class MemberIn(BaseModel):
    email: EmailStr
    role: str = "editor"


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: str


class AgentCreate(BaseModel):
    name: str | None = Field(None, max_length=200)
    template_key: str = "blank"
    business_name: str | None = Field(None, max_length=200)


class AgentOut(ORM):
    id: UUID
    name: str
    description: str
    industry: str | None
    template_key: str | None
    status: str
    published_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentOut):
    draft_config: dict[str, Any]


class AgentVersionOut(ORM):
    id: UUID
    agent_id: UUID
    version_number: int
    kind: str
    config_hash: str
    notes: str
    published_at: datetime | None
    created_at: datetime


class AgentVersionDetail(AgentVersionOut):
    config: dict[str, Any]


class PublishIn(BaseModel):
    notes: str = Field("", max_length=2000)


class TemplateSetupIn(BaseModel):
    integration_id: UUID | None = None


class WorkflowIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    agent_id: UUID | None = None
    graph: dict[str, Any] | None = None


class WorkflowOut(ORM):
    id: UUID
    name: str
    description: str
    agent_id: UUID | None
    revision: int
    updated_at: datetime


class ToolOut(ORM):
    id: UUID
    name: str
    display_name: str
    description: str
    category: str
    definition: dict[str, Any]
    current_version: int
    integration_id: UUID | None
    updated_at: datetime


class ToolTestIn(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class IntegrationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., pattern="^(postgres|rest_api)$")
    config: dict[str, Any] = Field(default_factory=dict)
    # Write-only. Never returned by the API.
    credentials: dict[str, Any] | None = None


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    status: str | None = Field(None, pattern="^(active|disabled)$")


class IntegrationOut(ORM):
    id: UUID
    name: str
    kind: str
    config: dict[str, Any]
    status: str
    has_credentials: bool = False
    credential_hint: str = ""
    updated_at: datetime


class KnowledgeBaseIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""


class KnowledgeBaseOut(ORM):
    id: UUID
    name: str
    description: str
    embedding_model: str
    created_at: datetime


class DocumentTextIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    source_type: str = Field("text", pattern="^(text|faq|url)$")
    content: str | None = None
    faq: list[dict[str, str]] | None = None
    url: str | None = None


class DocumentOut(ORM):
    id: UUID
    knowledge_base_id: UUID
    title: str
    source_type: str
    source_uri: str | None
    status: str
    error: str | None
    size_bytes: int
    chunk_count: int
    created_at: datetime


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(4, ge=1, le=10)


class PhoneNumberIn(BaseModel):
    e164: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$")
    agent_id: UUID | None = None
    purpose: str = Field("test", pattern="^(test|production)$")
    # SIP trunk details from the carrier (Twilio/Telnyx/...). Secrets are write-only.
    trunk: dict[str, Any] = Field(default_factory=dict)


class PhoneNumberUpdate(BaseModel):
    agent_id: UUID | None = None
    status: str | None = Field(None, pattern="^(active|disabled)$")


class PhoneNumberOut(ORM):
    id: UUID
    e164: str
    provider: str
    purpose: str
    status: str
    agent_id: UUID | None
    provider_ref: dict[str, Any]
    created_at: datetime


class OutboundCallIn(BaseModel):
    to: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$")


class TestSessionIn(BaseModel):
    agent_id: UUID
    use: str = Field("draft", pattern="^(draft|published)$")
    caller_number: str | None = None


class TestMessageIn(BaseModel):
    text: str = Field(..., max_length=4000)
