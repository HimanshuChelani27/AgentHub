"""A2A-style messaging: agents hand tasks to each other through the hub, so every
hand-off is checked against the registry, logged as a conversation, audited and traced."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.auth.deps import Principal, get_principal
from app.db import get_session
from app.models import A2AMessage, Agent, AuditEvent, Decision, Role
from app.tracing.spans import record_span

router = APIRouter(prefix="/a2a", tags=["a2a"])


class TaskIn(BaseModel):
    sender: str  # the sending agent's slug
    message: str = Field(min_length=1, max_length=20_000)


class TaskOut(BaseModel):
    task_id: int
    status: str
    recipient: str
    span_id: str


@router.post("/{slug}/tasks", response_model=TaskOut, name="send_task")
def send_task(
    slug: str,
    body: TaskIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
    x_agenthub_run_id: str | None = Header(default=None),
    x_agenthub_parent_span: str | None = Header(default=None),
) -> TaskOut:
    if principal.role not in (Role.agent, Role.admin, Role.developer):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only agents can send A2A tasks")
    started = datetime.now(UTC)
    agents = {a.slug: a for a in session.exec(select(Agent).where(col(Agent.slug).in_([slug, body.sender])))}
    problem = None
    if slug not in agents:
        problem = f"Unknown agent '{slug}'"
    elif agents[slug].status != "active":
        problem = f"Agent '{slug}' is inactive"
    elif body.sender not in agents:
        problem = f"Sender '{body.sender}' is not a registered agent"

    session.add(
        AuditEvent(
            principal=principal.name,
            role=principal.role.value,
            kind="a2a",
            server=body.sender,
            tool=slug,
            decision=Decision.denied if problem else Decision.allowed,
            reason=problem or "Delivered",
            run_id=x_agenthub_run_id,
            detail={"preview": body.message[:200]},
        )
    )
    if problem:
        session.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND if "Unknown" in problem else 409, problem)

    msg = A2AMessage(run_id=x_agenthub_run_id, sender=body.sender, recipient=slug, content=body.message)
    session.add(msg)
    span = record_span(
        session,
        name=f"{body.sender} → {slug}",
        kind="a2a",
        start=started,
        run_id=x_agenthub_run_id,
        parent_id=x_agenthub_parent_span,
        attrs={"sender": body.sender, "recipient": slug, "chars": len(body.message)},
    )
    session.commit()
    return TaskOut(task_id=msg.id, status="delivered", recipient=slug, span_id=span.id)


@router.get("/messages", response_model=list[A2AMessage], dependencies=[Depends(get_principal)])
def list_messages(run_id: str | None = None, limit: int = 100, session: Session = Depends(get_session)):
    q = select(A2AMessage)
    if run_id:
        q = q.where(A2AMessage.run_id == run_id)
    return session.exec(q.order_by(col(A2AMessage.id).desc()).limit(min(limit, 500))).all()
