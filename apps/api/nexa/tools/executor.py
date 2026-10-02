"""Executes tool requests coming from the LLM or the workflow engine.

Every request is: looked up in the agent version's allow-list -> validated ->
confirmation-checked -> executed with credentials loaded server-side -> logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.core.observability import TOOL_FAILURES, TOOL_LATENCY
from nexa.core.security import decrypt_json, redact
from nexa.knowledge.service import retrieve
from nexa.models import Integration, IntegrationCredential, ToolExecution
from nexa.schemas.agent_definition import AgentDefinition
from nexa.schemas.tool_definition import (
    DatabaseToolConfig,
    HandoffToolConfig,
    KnowledgeToolConfig,
    RestToolConfig,
    ToolDefinition,
)
from nexa.services.hours import is_open
from nexa.services.usage import record_usage
from nexa.tools.database import DatabaseToolError, execute_database_tool
from nexa.tools.network import BlockedDestination
from nexa.tools.rest import RestToolError, execute_rest_tool
from nexa.tools.validation import coerce_arguments, validate_arguments


@dataclass
class ToolResult:
    status: str  # succeeded | failed | rejected | confirmation_required
    tool_name: str
    data: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    action: dict[str, Any] | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    execution_id: UUID | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    def for_llm(self) -> dict[str, Any]:
        """What the model sees: outcome and data only - never config or credentials."""
        out: dict[str, Any] = {"status": self.status}
        if self.data is not None:
            out["data"] = {k: v for k, v in self.data.items() if k not in ("db_latency_ms",)}
        if self.error:
            out["error"] = self.error
        if self.status == "confirmation_required":
            out["instruction"] = ("Not executed yet. Read the details back to the caller and ask them to confirm. "
                                  "Do NOT say it is done. Call the tool again with the same arguments only after "
                                  "the caller clearly confirms.")
        elif self.status != "succeeded":
            out["instruction"] = "The action did NOT succeed. Do not tell the caller it succeeded."
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "tool": self.tool_name, "arguments": self.arguments, "data": self.data,
                "error": self.error, "error_code": self.error_code, "action": self.action,
                "latency_ms": round(self.latency_ms, 1)}


@dataclass
class ToolContext:
    db: AsyncSession
    tenant_id: UUID
    snapshot: dict[str, Any]
    call_id: UUID | None = None
    agent_id: UUID | None = None
    language: str = "ar"
    now: datetime | None = None


class ToolExecutor:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self.definition = AgentDefinition.model_validate(ctx.snapshot["definition"])
        self.tools: dict[str, dict[str, Any]] = {}
        for entry in ctx.snapshot.get("tools", []):
            try:
                td = ToolDefinition.model_validate(entry["definition"])
            except ValidationError:
                continue
            self.tools[td.name] = {**entry, "parsed": td}

    def llm_tools(self) -> list[dict[str, Any]]:
        return [e["parsed"].llm_schema() for e in self.tools.values()]

    def needs_confirmation(self, td: ToolDefinition) -> bool:
        if td.requires_confirmation:
            return True
        # Agent-level policy: bookings always need confirmation when enabled.
        return self.definition.policies.require_confirmation_for_booking and td.name.startswith(("book", "reserve"))

    async def execute(self, name: str, arguments: dict[str, Any], *, source: str = "llm",
                      confirmed: bool = False) -> ToolResult:
        start = time.perf_counter()
        entry = self.tools.get(name)
        if entry is None:
            # Never allow arbitrary tool execution: only tools attached to this agent version.
            result = ToolResult(status="rejected", tool_name=name, error="This action is not available.",
                                error_code="unknown_tool", arguments=redact(arguments))
            await self._log(None, result, source, False, confirmed)
            return result
        td: ToolDefinition = entry["parsed"]
        args = coerce_arguments(td.input_schema, arguments or {}, (self.ctx.now or datetime.now()).date())
        problems = validate_arguments(td.input_schema, args)
        if problems:
            result = ToolResult(status="rejected", tool_name=name, error="; ".join(problems),
                                error_code="invalid_arguments", arguments=redact(args))
        elif self.needs_confirmation(td) and not confirmed:
            result = ToolResult(status="confirmation_required", tool_name=name, arguments=redact(args),
                                data={"pending_action": td.display_name or td.name, "details": args})
        else:
            result = await self._run(td, args)
        result.latency_ms = (time.perf_counter() - start) * 1000
        TOOL_LATENCY.labels(td.category, result.status).observe(result.latency_ms / 1000)
        if result.status == "failed":
            TOOL_FAILURES.labels(td.name, result.error_code or "error").inc()
        await self._log(entry, result, source, self.needs_confirmation(td), confirmed)
        return result

    async def _run(self, td: ToolDefinition, args: dict[str, Any]) -> ToolResult:
        cfg = td.typed_config()
        try:
            if isinstance(cfg, DatabaseToolConfig):
                integ, secrets = await self._integration(cfg.integration_id, "postgres")
                data = await execute_database_tool(cfg, args, integration_id=str(integ.id),
                                                   integration_config=integ.config, secrets=secrets)
                if data.get("not_found") and td.typed_config().operation in ("update_record", "delete_record"):
                    return ToolResult(status="failed", tool_name=td.name, data=data, arguments=redact(args),
                                      error="No matching record was found, nothing was changed.",
                                      error_code="not_found")
                return ToolResult(status="succeeded", tool_name=td.name, data=data, arguments=redact(args))
            if isinstance(cfg, RestToolConfig):
                integ, secrets = await self._integration(cfg.integration_id, "rest_api")
                data = await execute_rest_tool(cfg, args, integration_config=integ.config, secrets=secrets)
                record_usage(self.ctx.db, self.ctx.tenant_id, "api_calls", 1, call_id=self.ctx.call_id,
                             agent_id=self.ctx.agent_id)
                return ToolResult(status="succeeded", tool_name=td.name, data=data, arguments=redact(args))
            if isinstance(cfg, HandoffToolConfig):
                return self._transfer(td, cfg, args)
            if isinstance(cfg, KnowledgeToolConfig):
                kb_ids = [UUID(str(k)) for k in self.definition.knowledge_base_ids]
                results = await retrieve(self.ctx.db, self.ctx.tenant_id, kb_ids, str(args.get("query", "")), cfg.top_k)
                return ToolResult(status="succeeded", tool_name=td.name, arguments=args,
                                  data={"results": [{"source": f"[{i + 1}] {r['document_title']}",
                                                     "content": r["content"], "score": r["score"],
                                                     "citation": {"document_id": r["document_id"],
                                                                  "chunk_id": r["chunk_id"]}}
                                                    for i, r in enumerate(results)],
                                        "found": bool(results)})
            # end_call
            return ToolResult(status="succeeded", tool_name=td.name, data={"ended": True}, arguments=args,
                              action={"type": "end_call"})
        except DatabaseToolError as exc:
            return ToolResult(status="failed", tool_name=td.name, error=exc.message, error_code=exc.code,
                              arguments=redact(args))
        except RestToolError as exc:
            return ToolResult(status="failed", tool_name=td.name, error=exc.message, error_code=exc.code,
                              arguments=redact(args))
        except BlockedDestination as exc:
            return ToolResult(status="failed", tool_name=td.name, error=str(exc), error_code="blocked_destination",
                              arguments=redact(args))
        except IntegrationUnavailable as exc:
            return ToolResult(status="failed", tool_name=td.name, error=str(exc), error_code="integration_unavailable",
                              arguments=redact(args))

    def _transfer(self, td: ToolDefinition, cfg: HandoffToolConfig, args: dict[str, Any]) -> ToolResult:
        h = self.definition.handoff
        if not (h.enabled and self.definition.policies.human_handoff_enabled):
            return ToolResult(status="failed", tool_name=td.name, error="Transfers are disabled for this agent.",
                              error_code="handoff_disabled", arguments=args)
        key = cfg.target or args.get("department") or h.default_target
        target = next((t for t in h.targets if t.key == key), None) or (
            next((t for t in h.targets if t.key == h.default_target), None) if h.default_target else None)
        if target is None:
            return ToolResult(status="failed", tool_name=td.name, error="No transfer destination is configured.",
                              error_code="no_target", arguments=args)
        if target.only_during_business_hours and not is_open(self.definition, self.ctx.now):
            return ToolResult(status="failed", tool_name=td.name, arguments=args, error_code="after_hours",
                              error=h.after_hours_message or "Staff are not available outside business hours.")
        return ToolResult(status="succeeded", tool_name=td.name, arguments=args,
                          data={"transferred_to": target.label},
                          action={"type": "transfer", "target": target.key, "label": target.label,
                                  "phone_number": target.phone_number, "reason": args.get("reason", "")})

    async def _integration(self, integration_id: UUID, kind: str) -> tuple[Integration, dict[str, Any]]:
        integ = await self.ctx.db.get(Integration, integration_id)
        if integ is None or integ.tenant_id != self.ctx.tenant_id or integ.deleted_at is not None:
            raise IntegrationUnavailable("The connected system is no longer available.")
        if integ.kind != kind or integ.status != "active":
            raise IntegrationUnavailable("The connected system is disabled.")
        cred = await self.ctx.db.scalar(select(IntegrationCredential).where(
            IntegrationCredential.integration_id == integ.id))
        secrets = decrypt_json(cred.encrypted_data) if cred else {}
        return integ, secrets

    async def _log(self, entry: dict[str, Any] | None, result: ToolResult, source: str, requires_conf: bool,
                   confirmed: bool) -> None:
        td: ToolDefinition | None = entry["parsed"] if entry else None
        row = ToolExecution(
            tenant_id=self.ctx.tenant_id, call_id=self.ctx.call_id,
            tool_id=UUID(entry["tool_id"]) if entry and entry.get("tool_id") else None,
            tool_version_id=UUID(entry["tool_version_id"]) if entry and entry.get("tool_version_id") else None,
            tool_name=result.tool_name, category=td.category if td else "unknown", source=source,
            arguments=redact(result.arguments), result=redact(result.data) if result.data is not None else None,
            status=result.status, error=result.error, latency_ms=result.latency_ms,
            requires_confirmation=requires_conf, confirmed=confirmed,
        )
        self.ctx.db.add(row)
        await self.ctx.db.flush()
        result.execution_id = row.id
        if result.status in ("succeeded", "failed"):
            record_usage(self.ctx.db, self.ctx.tenant_id, "tool_executions", 1, call_id=self.ctx.call_id,
                         agent_id=self.ctx.agent_id)


class IntegrationUnavailable(Exception):
    pass
