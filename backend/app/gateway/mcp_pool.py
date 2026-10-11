"""Long-lived MCP client connections, one per registered server.

Each connection is owned by its own asyncio task: the MCP client opens anyio task groups, which
must be exited by the task that entered them. Other tasks only use the connected session."""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp_types
from mcp import Client, StdioServerParameters
from sqlmodel import Session, delete, select

from app.models import McpServer, Tool

logger = logging.getLogger("agenthub.mcp")

# Repo root: stdio servers like `python -m mcp_servers.utils` run from here.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONNECT_TIMEOUT = 20.0


class McpUnavailable(Exception):
    """The server isn't connected and couldn't be (re)connected."""


@dataclass
class _Connection:
    server: McpServer
    client: Client | None = None
    error: str | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def target(self) -> StdioServerParameters | str:
        s = self.server
        if s.transport == "http":
            return s.url or ""
        command = sys.executable if s.command in ("python", "python3") else s.command
        return StdioServerParameters(command=command or "", args=list(s.args), cwd=str(PROJECT_ROOT))

    async def run(self) -> None:
        try:
            async with Client(self.target(), read_timeout_seconds=30) as client:
                self.client = client
                self.ready.set()
                await self.stop.wait()
        except Exception as e:  # noqa: BLE001 - any failure just marks the server unhealthy
            self.error = f"{type(e).__name__}: {e}"[:500]
            logger.warning("MCP server %s failed: %s", self.server.slug, self.error)
        finally:
            self.client = None
            self.ready.set()


class McpPool:
    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}

    async def connect(self, server: McpServer) -> list[mcp_types.Tool]:
        """(Re)connect and return the server's tools. Raises McpUnavailable on failure."""
        await self.disconnect(server.slug)
        conn = _Connection(server=server.model_copy())
        conn.task = asyncio.create_task(conn.run(), name=f"mcp:{server.slug}")
        self._conns[server.slug] = conn
        try:
            await asyncio.wait_for(conn.ready.wait(), CONNECT_TIMEOUT)
        except TimeoutError:
            conn.error = "Timed out connecting"
        if not conn.client:
            await self.disconnect(server.slug)
            raise McpUnavailable(conn.error or "Connection failed")
        return (await conn.client.list_tools()).tools

    async def disconnect(self, slug: str) -> None:
        conn = self._conns.pop(slug, None)
        if conn and conn.task:
            conn.stop.set()
            try:
                await asyncio.wait_for(conn.task, 5)
            except (TimeoutError, asyncio.CancelledError):
                conn.task.cancel()

    async def close(self) -> None:
        for slug in list(self._conns):
            await self.disconnect(slug)

    def is_connected(self, slug: str) -> bool:
        conn = self._conns.get(slug)
        return bool(conn and conn.client)

    async def call_tool(
        self, slug: str, tool: str, arguments: dict[str, Any], timeout: float
    ) -> mcp_types.CallToolResult:
        conn = self._conns.get(slug)
        if not conn or not conn.client:
            raise McpUnavailable(f"MCP server '{slug}' is not connected")
        return await asyncio.wait_for(conn.client.call_tool(tool, arguments), timeout)


def save_discovery(
    session: Session, server: McpServer, tools: list[mcp_types.Tool] | None, error: str | None
) -> None:
    """Persist connection status and the discovered tool list for a server."""
    server.status = "error" if error else "connected"
    server.last_error = error
    session.add(server)
    if tools is not None:
        session.exec(delete(Tool).where(Tool.server_slug == server.slug))
        now = datetime.now(UTC)
        for t in tools:
            session.add(
                Tool(
                    server_slug=server.slug,
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.input_schema or {},
                    discovered_at=now,
                )
            )
    session.commit()


async def connect_and_save(pool: McpPool, session: Session, server: McpServer) -> None:
    try:
        tools = await pool.connect(server)
        save_discovery(session, server, tools, None)
        logger.info("MCP server %s connected with %d tools", server.slug, len(tools))
    except McpUnavailable as e:
        save_discovery(session, server, None, str(e))


async def connect_all(pool: McpPool, session: Session) -> None:
    servers = session.exec(select(McpServer).where(McpServer.enabled == True)).all()  # noqa: E712
    await asyncio.gather(*(connect_and_save(pool, session, s) for s in servers))
