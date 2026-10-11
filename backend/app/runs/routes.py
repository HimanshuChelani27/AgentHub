import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth.deps import Principal, authenticate, get_principal
from app.db import get_session
from app.models import Run
from app.runs.service import MAX_CONCURRENT_RUNS, RunChannel

router = APIRouter(tags=["runs"])

KEEPALIVE_SECONDS = 15


class RunIn(BaseModel):
    task: str = Field(min_length=3, max_length=300)


@router.post("/runs", response_model=Run, status_code=201)
async def start_run(body: RunIn, request: Request, principal: Principal = Depends(get_principal)) -> Run:
    """Start the Research Crew. Viewers may run it too: the crew acts with its own agent key,
    so the demo account can watch governance in action without any write access."""
    manager = request.app.state.runs
    if not request.app.state.limiter.allow(f"run:{principal.name}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many runs, please wait a moment")
    if manager.active >= MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The crew is busy, try again in a few seconds"
        )
    return manager.start(body.task.strip(), started_by=principal.name)


async def _stream(channel: RunChannel, request: Request) -> AsyncIterator[str]:
    sent = 0
    while True:
        async with channel.changed:
            if sent >= len(channel.events) and not channel.done:
                with contextlib.suppress(TimeoutError):  # wake up to send a keep-alive
                    await asyncio.wait_for(channel.changed.wait(), KEEPALIVE_SECONDS)
            pending, finished = channel.events[sent:], channel.done
        for event in pending:
            yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
        sent += len(pending)
        if finished and sent >= len(channel.events):
            return
        if not pending:
            if await request.is_disconnected():
                return
            yield ": keep-alive\n\n"


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    token: str | None = Query(default=None, description="For EventSource, which can't send headers"),
    session: Session = Depends(get_session),
):
    """Server-Sent Events for a run. Replays everything so far, then streams live."""
    header = request.headers.get("authorization", "")
    credential = request.headers.get("x-api-key") or (
        header[7:] if header.lower().startswith("bearer ") else token
    )
    if not credential or not authenticate(credential, session):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid credentials")
    channel = request.app.state.runs.channels.get(run_id)
    if not channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No live events for this run (see /runs/{id} instead)")
    return StreamingResponse(
        _stream(channel, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
