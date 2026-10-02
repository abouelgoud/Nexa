import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nexa.models.base import Audited, Base, SoftDelete, TenantScoped, Timestamps, UUIDPk


class Tool(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tools_tenant_name"),)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # Current ToolDefinition (nexa.schemas.tool_definition). Every change writes a ToolVersion.
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), index=True
    )


class ToolVersion(UUIDPk, Timestamps, Audited, TenantScoped, Base):
    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version_number", name="uq_tool_versions_tool_number"),)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AgentTool(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id", name="uq_agent_tools_agent_tool"),)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Integration(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    __tablename__ = "integrations"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # postgres | rest_api
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # Non-secret configuration (base URL, host, table/field permissions, ...)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class IntegrationCredential(UUIDPk, Timestamps, TenantScoped, Base):
    """Encrypted secrets for an integration. Never returned to clients or sent to the LLM."""

    __tablename__ = "integration_credentials"
    integration_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Human hint such as "token ending in ...a1b2"
    hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
