"""One aggregated MCP endpoint (/mcp) in front of every registered server.

Any MCP client (Claude Desktop, VS Code, MCP Inspector, another agent) connects once with an
API key and sees only the tools its role may call, named `server__tool`. Every call runs through
the same gateway pipeline as the REST API: policy, PII masking, audit and tracing."""

import json
from typing import Any

import mcp_types as types
from fastapi import FastAPI
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlmodel import Session
from starlette.types import Receive, Scope, Send

from app.auth.deps import Principal, authenticate
from app.db import engine
from app.gateway.tool_proxy import ToolNotFound, call_tool, visible_tools

SEP = "__"
STATE_KEY = "agenthub_principal"


def _principal(ctx) -> Principal:
    return ctx.request.scope["state"][STATE_KEY]


def build_mcp_server(app: FastAPI) -> Server:
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        with Session(engine) as session:
            tools = visible_tools(session, _principal(ctx).role.value)
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=t["qualified_name"],
                    description=f"[{t['server']}] {t['description']}",
                    input_schema=t["input_schema"] or {"type": "object", "properties": {}},
                )
                for t in tools
            ]
        )

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        server, _, tool = params.name.partition(SEP)
        with Session(engine) as session:
            try:
                outcome = await call_tool(
                    pool=app.state.pool,
                    session=session,
                    limiter=app.state.limiter,
                    principal=_principal(ctx),
                    server=server,
                    tool=tool,
                    arguments=dict(params.arguments or {}),
                )
            except ToolNotFound as e:
                return _error(str(e))
        if outcome.decision.value in ("denied", "rate_limited"):
            return _error(f"Blocked by AgentHub ({outcome.decision.value}): {outcome.reason}")
        content: list[Any] = [
            types.TextContent(type="text", text=c["text"]) for c in outcome.content if c.get("type") == "text"
        ] or [types.TextContent(type="text", text=json.dumps(outcome.structured or {}))]
        return types.CallToolResult(
            content=content, structured_content=outcome.structured, is_error=not outcome.ok
        )

    return Server(
        "agenthub",
        version="0.1.0",
        description="AgentHub gateway: governed access to registered MCP servers",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], is_error=True)


class AuthenticatedMcpApp:
    """ASGI wrapper: rejects requests without a valid API key/JWT before they reach MCP."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        credential = headers.get("x-api-key")
        auth = headers.get("authorization", "")
        if not credential and auth.lower().startswith("bearer "):
            credential = auth[7:].strip()
        with Session(engine) as session:
            principal = authenticate(credential, session) if credential else None
        if not principal:
            body = b'{"error":"Missing or invalid API key. Send X-API-Key or Authorization: Bearer."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        scope.setdefault("state", {})[STATE_KEY] = principal
        await self.app.state.mcp_manager.handle_request(scope, receive, send)


def create_mcp_manager(app: FastAPI) -> StreamableHTTPSessionManager:
    # Stateless + JSON responses: every request is self-contained, which suits a gateway
    # sitting behind load balancers. Auth is enforced by AuthenticatedMcpApp.
    return StreamableHTTPSessionManager(app=build_mcp_server(app), stateless=True, json_response=True)
