import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from nexa.models.base import Audited, Base, SoftDelete, TenantScoped, Timestamps, UUIDPk


class Voice(UUIDPk, Timestamps, SoftDelete, Audited, TenantScoped, Base):
    """A cloned voice owned by a business. The original recording is kept so the clone can be recreated."""

    __tablename__ = "voices"
    __table_args__ = (Index("ix_voices_provider_voice", "provider", "provider_voice_id"),)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # neural (self-hosted) | elevenlabs
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(200), nullable=False)
    seconds: Mapped[float | None] = mapped_column(Float)
    recording_mime: Mapped[str] = mapped_column(String(100), nullable=False, default="audio/wav")
    recording = deferred(mapped_column(LargeBinary, nullable=False))
    consent_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
