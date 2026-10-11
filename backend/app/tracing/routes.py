from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.auth.deps import Principal, get_principal
from app.db import get_session
from app.models import A2AMessage, AuditEvent, Role, Run, Span

router = APIRouter(tags=["tracing"])


class SpanIn(BaseModel):
    """Agents report their own steps (planning, writing...). Ids are client-generated so a
    child can reference its parent before the parent has finished."""

    id: str = Field(min_length=8, max_length=64)
    run_id: str
    parent_id: str | None = None
    name: str
    kind: str = "agent"
    status: str = "ok"
    start: datetime
    end: datetime
    attrs: dict[str, Any] = {}


@router.post("/traces/spans", status_code=201)
def report_span(
    body: SpanIn, principal: Principal = Depends(get_principal), session: Session = Depends(get_session)
) -> dict[str, str]:
    if principal.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers cannot write spans")
    if session.get(Span, body.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Span id already exists")
    span = Span(**body.model_dump())
    span.attrs = {**body.attrs, "reported_by": principal.name}
    session.add(span)
    session.commit()
    return {"id": body.id}


@router.get("/runs", response_model=list[Run], dependencies=[Depends(get_principal)])
def list_runs(limit: int = 50, session: Session = Depends(get_session)):
    return session.exec(select(Run).order_by(col(Run.started_at).desc()).limit(min(limit, 200))).all()


class RunDetail(BaseModel):
    run: Run
    spans: list[Span]
    messages: list[A2AMessage]
    audit: list[AuditEvent]


@router.get("/runs/{run_id}", response_model=RunDetail, dependencies=[Depends(get_principal)])
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunDetail:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return RunDetail(
        run=run,
        spans=list(session.exec(select(Span).where(Span.run_id == run_id).order_by(Span.start)).all()),
        messages=list(
            session.exec(select(A2AMessage).where(A2AMessage.run_id == run_id).order_by(A2AMessage.id)).all()
        ),
        audit=list(
            session.exec(select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)).all()
        ),
    )
