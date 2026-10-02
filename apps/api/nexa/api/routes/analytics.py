from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select

from nexa.core.deps import TenantContext, get_tenant_context
from nexa.models import Call, ToolExecution, UsageRecord

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(agent_id: UUID | None = None, days: int = Query(30, ge=1, le=365), include_tests: bool = True,
                   ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    conds = [Call.tenant_id == ctx.tenant_id, Call.started_at >= since]
    if agent_id:
        conds.append(Call.agent_id == agent_id)
    if not include_tests:
        conds.append(Call.is_test.is_(False))
    where = and_(*conds)
    totals = (await ctx.db.execute(select(
        func.count(Call.id),
        func.count(case((Call.metrics["turns"].as_integer() > 0, 1))),
        func.count(case((Call.outcome == "task_completed", 1))),
        func.count(case((Call.status == "transferred", 1))),
        func.count(case((Call.outcome == "failed", 1))),
        func.avg(Call.duration_seconds),
        func.avg(Call.metrics["avg_turn_latency_ms"].as_float()),
        func.avg(Call.satisfaction),
    ).where(where))).one()

    async def dist(col) -> list[dict[str, Any]]:
        rows = (await ctx.db.execute(select(col, func.count()).where(where, col.is_not(None)).group_by(col)
                                     .order_by(func.count().desc()).limit(10))).all()
        return [{"key": k, "count": n} for k, n in rows]

    day = func.date_trunc("day", Call.started_at)
    series = (await ctx.db.execute(select(day, func.count()).where(where).group_by(day).order_by(day))).all()
    tool_conds = [ToolExecution.tenant_id == ctx.tenant_id, ToolExecution.created_at >= since,
                  ToolExecution.status == "failed"]
    if agent_id:
        tool_conds.append(ToolExecution.call_id.in_(select(Call.id).where(where)))
    failures = (await ctx.db.execute(select(ToolExecution.tool_name, func.count()).where(*tool_conds)
                                     .group_by(ToolExecution.tool_name).order_by(func.count().desc()))).all()
    return {
        "period_days": days,
        "calls": totals[0], "answered_calls": totals[1], "completed_tasks": totals[2], "transferred_calls": totals[3],
        "failed_tasks": totals[4], "avg_duration_seconds": round(totals[5] or 0, 1),
        "avg_response_latency_ms": round(totals[6] or 0, 1),
        "customer_satisfaction": round(totals[7], 2) if totals[7] is not None else None,
        "languages": await dist(Call.language), "dialects": await dist(Call.dialect),
        "top_intents": await dist(Call.intent), "outcomes": await dist(Call.outcome),
        "tool_failures": [{"tool": t, "count": n} for t, n in failures],
        "calls_per_day": [{"day": d.date().isoformat(), "count": n} for d, n in series],
    }


@router.get("/usage")
async def usage(days: int = Query(30, ge=1, le=365), ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await ctx.db.execute(select(UsageRecord.metric, func.sum(UsageRecord.quantity))
                                 .where(UsageRecord.tenant_id == ctx.tenant_id, UsageRecord.recorded_at >= since)
                                 .group_by(UsageRecord.metric))).all()
    return {"period_days": days, "usage": {m: round(q, 2) for m, q in rows}}
