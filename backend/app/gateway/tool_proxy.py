"""The gateway pipeline for every tool call, whether it arrives over REST or the /mcp endpoint:

rate limit → policy → mask PII in arguments → call MCP server → mask PII in result → audit + span
"""

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.auth.deps import Principal
from app.config import get_settings
from app.gateway import pii
from app.gateway.mcp_pool import McpPool, McpUnavailable
from app.gateway.policy import evaluate, load_policies
from app.gateway.ratelimit import RateLimiter
from app.models import AuditEvent, Decision, Tool
from app.tracing.spans import record_span

PREVIEW_CHARS = 600


class ToolNotFound(Exception):
    pass


@dataclass
class ToolCallOutcome:
    ok: bool
    decision: Decision
    reason: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    pii_masked: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    audit_id: int | None = None
    span_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def text(self) -> str:
        return "\n".join(c.get("text", "") for c in self.content if c.get("type") == "text")


def _merge(*counts: dict[str, int]) -> dict[str, int]:
    total: dict[str, int] = {}
    for c in counts:
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
    return total


async def _mask_result(result, do_mask: bool) -> tuple[list[dict], dict | None, dict[str, int]]:
    structured = result.structured_content
    blocks = [b.model_dump(mode="json", exclude_none=True) for b in result.content]
    if not do_mask:
        return blocks, structured, {}
    counts: dict[str, int] = {}
    if structured is not None:
        structured, counts = await asyncio.to_thread(pii.mask, structured)
        # The text block mirrors the structured result; regenerate it so nothing leaks.
        blocks = [b for b in blocks if b.get("type") != "text"]
        blocks.insert(0, {"type": "text", "text": json.dumps(structured, indent=2)})
    else:
        for b in blocks:
            if b.get("type") == "text":
                b["text"], c = await asyncio.to_thread(pii.mask, b["text"])
                counts = _merge(counts, c)
    return blocks, structured, counts


async def call_tool(
    *,
    pool: McpPool,
    session: Session,
    limiter: RateLimiter,
    principal: Principal,
    server: str,
    tool: str,
    arguments: dict[str, Any],
    run_id: str | None = None,
    parent_span_id: str | None = None,
) -> ToolCallOutcome:
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    outcome: ToolCallOutcome
    detail: dict[str, Any] = {}
    masked_args = arguments

    if not limiter.allow(f"{principal.kind}:{principal.name}"):
        outcome = ToolCallOutcome(False, Decision.rate_limited, "Rate limit exceeded, try again shortly")
    elif not session.exec(select(Tool).where(Tool.server_slug == server, Tool.name == tool)).first():
        raise ToolNotFound(f"Tool '{server}/{tool}' is not registered")
    else:
        decision = evaluate(load_policies(session), principal.role.value, server, tool)
        detail["rule_id"] = decision.rule_id
        if not decision.allowed:
            outcome = ToolCallOutcome(False, Decision.denied, decision.reason)
        else:
            in_counts: dict[str, int] = {}
            if decision.mask_pii:
                masked_args, in_counts = await asyncio.to_thread(pii.mask, arguments, for_input=True)
            try:
                result = await pool.call_tool(
                    server, tool, masked_args, timeout=get_settings().tool_timeout_seconds
                )
                content, structured, out_counts = await _mask_result(result, decision.mask_pii)
                outcome = ToolCallOutcome(
                    ok=not result.is_error,
                    decision=Decision.error if result.is_error else Decision.allowed,
                    reason=decision.reason,
                    content=content,
                    structured=structured,
                    pii_masked=_merge(in_counts, out_counts),
                )
            except McpUnavailable as e:
                outcome = ToolCallOutcome(False, Decision.error, str(e))
            except TimeoutError:
                outcome = ToolCallOutcome(False, Decision.error, "Tool call timed out")

    outcome.latency_ms = int((time.perf_counter() - t0) * 1000)
    detail.update(
        arguments=masked_args,
        pii_by_type=outcome.pii_masked,
        result_preview=outcome.text[:PREVIEW_CHARS] if outcome.ok else None,
    )
    event = AuditEvent(
        principal=principal.name,
        role=principal.role.value,
        kind="tool",
        server=server,
        tool=tool,
        decision=outcome.decision,
        reason=outcome.reason,
        pii_masked=sum(outcome.pii_masked.values()),
        latency_ms=outcome.latency_ms,
        run_id=run_id,
        detail=detail,
    )
    session.add(event)
    span = record_span(
        session,
        name=f"{server}.{tool}",
        kind="tool",
        start=started,
        run_id=run_id,
        parent_id=parent_span_id,
        status={Decision.allowed: "ok", Decision.denied: "denied"}.get(outcome.decision, "error"),
        attrs={
            "principal": principal.name,
            "decision": outcome.decision.value,
            "pii_masked": outcome.pii_masked,
            "arguments": masked_args,
        },
    )
    session.commit()
    outcome.audit_id, outcome.span_id = event.id, span.id
    return outcome


def visible_tools(session: Session, role: str) -> list[dict[str, Any]]:
    """Tools the role may call, as the gateway exposes them (server__tool names)."""
    policies = load_policies(session)
    tools = []
    for t in session.exec(select(Tool).order_by(Tool.server_slug, Tool.name)).all():
        decision = evaluate(policies, role, t.server_slug, t.name)
        if decision.allowed:
            tools.append(
                {
                    "server": t.server_slug,
                    "name": t.name,
                    "qualified_name": f"{t.server_slug}__{t.name}",
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "mask_pii": decision.mask_pii,
                }
            )
    return tools
