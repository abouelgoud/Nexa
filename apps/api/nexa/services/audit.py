from __future__ import annotations

from typing import Any
from uuid import UUID

from nexa.core.deps import TenantContext
from nexa.core.security import redact
from nexa.models import AuditLog


def audit(ctx: TenantContext, action: str, entity_type: str, entity_id: UUID | None = None,
          changes: dict[str, Any] | None = None) -> None:
    """Add an audit row to the current transaction (committed with the change itself)."""
    ctx.db.add(AuditLog(tenant_id=ctx.tenant_id, actor_user_id=ctx.user.id, action=action, entity_type=entity_type,
                        entity_id=entity_id, changes=redact(changes or {}), ip_address=ctx.ip))
