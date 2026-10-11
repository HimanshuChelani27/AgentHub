"""The crew's only link to the outside world: AgentHub's HTTP API, authenticated with the
crew's API key. Tools, LLM calls, hand-offs and spans all go through here."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


def new_span_id() -> str:
    return uuid.uuid4().hex


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        run_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.run_id = run_id
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key, "X-AgentHub-Run-Id": run_id},
            transport=transport,
            timeout=90,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _parent(parent: str | None) -> dict[str, str]:
        return {"X-AgentHub-Parent-Span": parent} if parent else {}

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any], parent: str | None) -> dict:
        """Returns the gateway outcome, including denials (HTTP 403) and rate limits (429)."""
        res = await self._http.post(
            f"/gateway/tools/{server}/{tool}", json={"arguments": arguments}, headers=self._parent(parent)
        )
        if res.status_code in (200, 403, 429):
            return res.json()
        res.raise_for_status()
        return {}

    async def chat(
        self,
        *,
        agent: str,
        system: str,
        prompt: str,
        scripted_response: str,
        parent: str | None,
        max_tokens: int = 700,
    ) -> dict:
        res = await self._http.post(
            "/gateway/llm/chat",
            json={
                "agent": agent,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "scripted_response": scripted_response,
                "max_tokens": max_tokens,
            },
            headers=self._parent(parent),
        )
        res.raise_for_status()
        return res.json()

    async def send_task(self, sender: str, recipient: str, message: str, parent: str | None) -> dict:
        res = await self._http.post(
            f"/a2a/{recipient}/tasks",
            json={"sender": sender, "message": message},
            headers=self._parent(parent),
        )
        res.raise_for_status()
        return res.json()

    async def report_span(
        self,
        *,
        span_id: str,
        name: str,
        kind: str,
        start: datetime,
        parent: str | None,
        status: str = "ok",
        attrs: dict[str, Any] | None = None,
    ) -> None:
        res = await self._http.post(
            "/traces/spans",
            json={
                "id": span_id,
                "run_id": self.run_id,
                "parent_id": parent,
                "name": name,
                "kind": kind,
                "status": status,
                "start": start.isoformat(),
                "end": datetime.now(UTC).isoformat(),
                "attrs": attrs or {},
            },
        )
        res.raise_for_status()
