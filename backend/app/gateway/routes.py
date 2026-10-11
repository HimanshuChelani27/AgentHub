from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.deps import Principal, get_principal
from app.config import get_settings
from app.db import get_session
from app.gateway import llm
from app.gateway.llm import ChatIn, ChatOut, resolve_provider
from app.gateway.tool_proxy import ToolNotFound, call_tool, visible_tools
from app.models import Decision

router = APIRouter(prefix="/gateway", tags=["gateway"])

STATUS_FOR = {
    Decision.denied: status.HTTP_403_FORBIDDEN,
    Decision.rate_limited: status.HTTP_429_TOO_MANY_REQUESTS,
}


class ToolCallIn(BaseModel):
    arguments: dict[str, Any] = {}


@router.get("/tools")
def list_visible_tools(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """Tools the caller's role is allowed to use."""
    return visible_tools(session, principal.role.value)


@router.post("/tools/{server}/{tool}")
async def call(
    server: str,
    tool: str,
    body: ToolCallIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
    x_agenthub_run_id: str | None = Header(default=None),
    x_agenthub_parent_span: str | None = Header(default=None),
):
    """Call a tool through the gateway. Denials and rate limits are returned with details
    (and audited) rather than as bare errors, so agents can explain them."""
    try:
        outcome = await call_tool(
            pool=request.app.state.pool,
            session=session,
            limiter=request.app.state.limiter,
            principal=principal,
            server=server,
            tool=tool,
            arguments=body.arguments,
            run_id=x_agenthub_run_id,
            parent_span_id=x_agenthub_parent_span,
        )
    except ToolNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return JSONResponse(outcome.to_dict(), status_code=STATUS_FOR.get(outcome.decision, 200))


@router.get("/llm/provider")
def llm_provider(principal: Principal = Depends(get_principal)) -> dict[str, str]:
    """Which LLM backs the gateway right now (the dashboard shows live vs scripted)."""
    p = resolve_provider(get_settings())
    return {"provider": p.name, "model": p.model, "mode": "scripted" if p.name == "scripted" else "live"}


@router.post("/llm/chat", response_model=ChatOut)
async def llm_chat(
    body: ChatIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
    x_agenthub_run_id: str | None = Header(default=None),
    x_agenthub_parent_span: str | None = Header(default=None),
) -> ChatOut:
    if not request.app.state.limiter.allow(f"{principal.kind}:{principal.name}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
    return await llm.chat(
        session=session,
        principal=principal,
        body=body,
        run_id=x_agenthub_run_id,
        parent_span_id=x_agenthub_parent_span,
    )
