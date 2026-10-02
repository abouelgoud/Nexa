import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nexa.models.base import utcnow, Base, TenantScoped, Timestamps, UUIDPk


class Call(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "calls"
    __table_args__ = (Index("ix_calls_tenant_started", "tenant_id", "started_at"),)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    # web | phone | text
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # inbound | outbound
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="inbound")
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_number: Mapped[str | None] = mapped_column(String(32))
    to_number: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)
    # active | completed | transferred | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(String(10))
    dialect: Mapped[str | None] = mapped_column(String(20))
    intent: Mapped[str | None] = mapped_column(String(100))
    # task_completed | transferred | abandoned | failed | info_provided
    outcome: Mapped[str | None] = mapped_column(String(50))
    transferred_to: Mapped[str | None] = mapped_column(String(200))
    recording_uri: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    satisfaction: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class CallParticipant(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "call_participants"
    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # caller | agent | human_agent
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    identity: Mapped[str] = mapped_column(String(200), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallEvent(UUIDPk, Timestamps, TenantScoped, Base):
    """Operational timeline of a call (never contains model chain-of-thought)."""

    __tablename__ = "call_events"
    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float)


class Conversation(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "conversations"
    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Serialized VoiceSession conversation state (pending confirmations, slots, ...)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    workflow_state: Mapped[dict | None] = mapped_column(JSONB)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Message(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # user | assistant | tool | system
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(10))
    dialect: Mapped[str | None] = mapped_column(String(20))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Transcript(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "transcripts"
    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10))
    dialect: Mapped[str | None] = mapped_column(String(20))
    dialect_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)


class ToolExecution(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "tool_executions"
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tools.id", ondelete="SET NULL"), index=True
    )
    tool_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tool_versions.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # llm | workflow | api_test
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="llm")
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    # succeeded | failed | rejected | confirmation_required
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorkflowExecution(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "workflow_executions"
    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    current_node: Mapped[str | None] = mapped_column(String(100))
    path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
