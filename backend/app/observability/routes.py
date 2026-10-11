from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.deps import get_principal
from app.db import get_session
from app.models import Agent, AuditEvent, Decision, McpServer, Tool

router = APIRouter(tags=["observability"], dependencies=[Depends(get_principal)])


@router.get("/audit", response_model=list[AuditEvent])
def list_audit(
    session: Session = Depends(get_session),
    decision: Decision | None = None,
    server: str | None = None,
    principal: str | None = None,
    kind: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=100, le=500),
    before_id: int | None = None,
):
    q = select(AuditEvent)
    for column, value in (
        (AuditEvent.decision, decision),
        (AuditEvent.server, server),
        (AuditEvent.principal, principal),
        (AuditEvent.kind, kind),
        (AuditEvent.run_id, run_id),
    ):
        if value is not None:
            q = q.where(column == value)
    if before_id:
        q = q.where(col(AuditEvent.id) < before_id)
    return session.exec(q.order_by(col(AuditEvent.id).desc()).limit(limit)).all()


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    """Numbers for the dashboard overview (last 24 hours, hourly buckets)."""
    since = datetime.now(UTC) - timedelta(hours=24)
    events = session.exec(select(AuditEvent).where(AuditEvent.ts >= since)).all()

    buckets: dict[str, dict[str, int]] = {}
    for h in range(24, -1, -1):
        key = (datetime.now(UTC) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
        buckets[key] = {"allowed": 0, "denied": 0, "error": 0}
    for e in events:
        ts = e.ts if e.ts.tzinfo else e.ts.replace(tzinfo=UTC)
        key = ts.strftime("%Y-%m-%dT%H:00")
        if key in buckets:
            kind = {Decision.allowed: "allowed", Decision.denied: "denied"}.get(e.decision, "error")
            buckets[key][kind] += 1

    def count(model) -> int:
        return session.exec(select(func.count()).select_from(model)).one()

    return {
        "agents": count(Agent),
        "servers": count(McpServer),
        "tools": count(Tool),
        "calls_24h": len(events),
        "denied_24h": sum(e.decision == Decision.denied for e in events),
        "errors_24h": sum(e.decision in (Decision.error, Decision.rate_limited) for e in events),
        "pii_masked_24h": sum(e.pii_masked for e in events),
        "avg_latency_ms": round(sum(e.latency_ms for e in events) / len(events)) if events else 0,
        "timeline": [{"hour": k, **v} for k, v in buckets.items()],
    }
