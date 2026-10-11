"""Starts Research Crew runs in the background and fans their events out to SSE listeners.

The crew calls AgentHub over HTTP using an in-process ASGI transport: no network hop, but every
request still passes through authentication, policy, masking, audit and tracing like any client."""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from sqlmodel import Session

from app.config import get_settings
from app.db import engine
from app.gateway.mcp_pool import PROJECT_ROOT
from app.models import Run
from app.tracing.spans import record_span

# The example agents live at the repo root (agents/), next to backend/.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.research_crew.crew import ResearchCrew  # noqa: E402
from agents.research_crew.gateway_client import GatewayClient  # noqa: E402

logger = logging.getLogger("agenthub.runs")

MAX_CONCURRENT_RUNS = 3
KEEP_CHANNELS = 50


@dataclass
class RunChannel:
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False

    async def publish(self, event: dict[str, Any]) -> None:
        async with self.changed:
            self.events.append({**event, "ts": datetime.now(UTC).isoformat()})
            self.changed.notify_all()

    async def close(self) -> None:
        async with self.changed:
            self.done = True
            self.changed.notify_all()


class RunManager:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.channels: dict[str, RunChannel] = {}
        self.tasks: set[asyncio.Task] = set()

    @property
    def active(self) -> int:
        return sum(not t.done() for t in self.tasks)

    def start(self, task: str, started_by: str) -> Run:
        with Session(engine) as session:
            run = Run(task=task, started_by=started_by)
            session.add(run)
            session.commit()
            session.refresh(run)
        self.channels[run.id] = RunChannel()
        for old in list(self.channels)[:-KEEP_CHANNELS]:
            self.channels.pop(old, None)
        t = asyncio.create_task(self._execute(run.id, task), name=f"run:{run.id}")
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return run

    async def _execute(self, run_id: str, task: str) -> None:
        channel = self.channels[run_id]
        started = datetime.now(UTC)
        root_span = f"run-{run_id}"
        gateway = GatewayClient(
            base_url="http://agenthub.internal",
            api_key=get_settings().crew_api_key,
            run_id=run_id,
            transport=httpx.ASGITransport(app=self.app),
        )
        await channel.publish({"type": "run_started", "run_id": run_id, "task": task})
        status, output, final = "succeeded", None, {}
        try:
            final = await ResearchCrew(gateway, channel.publish, root_span).run(task)
            output = f"{final.get('draft', '')}\n\n---\n**Review:** {final.get('review', '')}"
        except Exception as e:  # noqa: BLE001 - surface any crew failure to the UI
            logger.exception("Run %s failed", run_id)
            status, output = "failed", f"Run failed: {type(e).__name__}: {e}"
        finally:
            await gateway.aclose()

        with Session(engine) as session:
            run = session.get(Run, run_id)
            mode = (
                "live"
                if any(e.get("mode") == "live" for e in channel.events if e["type"] == "llm")
                else "scripted"
            )
            run.status, run.output, run.mode, run.finished_at = status, output, mode, datetime.now(UTC)
            session.add(run)
            span = record_span(
                session,
                name="research-crew",
                kind="run",
                start=started,
                run_id=run_id,
                status="ok" if status == "succeeded" else "error",
                attrs={"task": task, "mode": mode},
            )
            span.id = root_span
            session.commit()
        await channel.publish(
            {"type": "run_finished", "status": status, "output": output, "approved": final.get("approved")}
        )
        await channel.close()

    async def shutdown(self) -> None:
        for t in list(self.tasks):
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
