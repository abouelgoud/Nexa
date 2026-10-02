import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nexa.models.base import Base, SoftDelete, TenantScoped, Timestamps, UUIDPk


class User(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tenant(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Riyadh")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")


class TenantUser(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "tenant_users"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_users_tenant_user"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # owner | admin | editor | viewer
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
