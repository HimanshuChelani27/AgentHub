"""Drives /mcp with the official MCP client over real Streamable HTTP (uvicorn on a free port)."""

import asyncio
import socket
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def connect(base_url: str, key: str):
    http = httpx2.AsyncClient(headers={"X-API-Key": key}, timeout=30)
    return Client(streamable_http_client(f"{base_url}/mcp", http_client=http))


def test_rejects_missing_key(base_url):
    res = httpx.post(f"{base_url}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert res.status_code == 401


def test_agent_sees_only_allowed_tools_and_gets_masked_data(base_url):
    async def scenario():
        async with connect(base_url, get_settings().crew_api_key) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "company_kb__get_customer" in names and "utils__calculator" in names
            assert "company_kb__get_contract" not in names

            result = await client.call_tool("company_kb__get_customer", {"customer_id": "globex"})
            assert not result.is_error
            assert result.structured_content["contact"]["email"] == "<EMAIL_ADDRESS>"

            blocked = await client.call_tool("company_kb__get_contract", {"customer_id": "globex"})
            assert blocked.is_error and "legal team" in blocked.content[0].text

    asyncio.run(scenario())
