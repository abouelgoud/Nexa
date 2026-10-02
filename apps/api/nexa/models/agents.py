import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nexa.models.base import Audited, Base, SoftDelete, TenantScoped, Timestamps, UUIDPk


class Agent(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_tenant_active", "tenant_id", postgresql_where=text("deleted_at IS NULL")),)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    industry: Mapped[str | None] = mapped_column(String(100))
    template_key: Mapped[str | None] = mapped_column(String(100))
    # draft | published | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Working copy of the AgentDefinition (validated by nexa.schemas.agent_definition).
    draft_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL", use_alter=True)
    )


class AgentVersion(UUIDPk, Timestamps, Audited, TenantScoped, Base):
    """Immutable snapshot of an agent's full configuration.

    ``config`` holds the AgentDefinition plus the resolved workflow graph and tool
    definitions, so a running call is never affected by later edits. A database
    trigger (see migration) rejects any UPDATE of ``config``/``config_hash``.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_number"),
        Index("ix_agent_versions_agent_hash", "agent_id", "config_hash"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # test (snapshot of a draft used for testing) | published
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentLanguage(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "agent_languages"
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    dialect: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)


class AgentVoice(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "agent_voices"
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(200), nullable=False)
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class AgentRule(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "agent_rules"
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # policy | handoff | privacy
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Workflow(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    __tablename__ = "workflows"
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkflowNode(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (UniqueConstraint("workflow_id", "node_key", name="uq_workflow_nodes_key"),)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    position: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class WorkflowEdge(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "workflow_edges"
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edge_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    target_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Branch label: "default", "yes", "no", "success", "error", or an intent name.
    handle: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    condition: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
