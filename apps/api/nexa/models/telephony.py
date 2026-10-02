import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nexa.models.base import Audited, Base, SoftDelete, TenantScoped, Timestamps, UUIDPk


class PhoneNumber(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    __tablename__ = "phone_numbers"
    e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # test | production
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    # pending | active | disabled | error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )


class PhoneRoute(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "phone_routes"
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # e.g. {"business_hours": "inside" | "outside" | "any"}
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # use the published version (default) or the latest test snapshot
    version_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
