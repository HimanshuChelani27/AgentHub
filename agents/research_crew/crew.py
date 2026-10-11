"""Research Crew: four LangGraph agents that prepare a customer brief.

    Planner ──A2A──► Researcher ──A2A──► Writer ──A2A──► Reviewer ──A2A──► Planner

The agents never touch tools or models directly; everything goes through AgentHub, so the
demo shows real policy decisions (the contract lookup is denied), real PII masking and a full
trace. Each LLM call carries a deterministic `scripted_response` built from the (already masked)
tool data, so the crew produces a sensible brief even with no LLM key configured."""

import json
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.research_crew.gateway_client import GatewayClient, new_span_id

Emit = Callable[[dict[str, Any]], Awaitable[None]]

MAX_TARGETS = 2
_LEAK = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+\d{1,3}(?:[\s.-]?\d{2,5}){2,4}")


class CrewState(TypedDict, total=False):
    task: str
    plan: str
    notes: list[dict[str, Any]]
    draft: str
    review: str
    approved: bool


class ResearchCrew:
    def __init__(self, gateway: GatewayClient, emit: Emit, root_span: str) -> None:
        self.gw = gateway
        self.emit = emit
        self.root_span = root_span

    # ---------- plumbing ----------

    @asynccontextmanager
    async def _step(self, agent: str):
        span_id, start = new_span_id(), datetime.now(UTC)
        await self.emit({"type": "agent_started", "agent": agent})
        status = "ok"
        try:
            yield span_id
        except Exception:
            status = "error"
            raise
        finally:
            await self.gw.report_span(
                span_id=span_id, name=agent, kind="agent", start=start, parent=self.root_span, status=status
            )
            await self.emit({"type": "agent_finished", "agent": agent, "status": status})

    async def _tool(self, agent: str, span: str, server: str, tool: str, **arguments) -> dict:
        out = await self.gw.call_tool(server, tool, arguments, parent=span)
        await self.emit(
            {
                "type": "tool_call",
                "agent": agent,
                "server": server,
                "tool": tool,
                "arguments": arguments,
                "decision": out.get("decision"),
                "reason": out.get("reason") if out.get("decision") != "allowed" else "",
                "pii_masked": out.get("pii_masked", {}),
                "latency_ms": out.get("latency_ms", 0),
            }
        )
        return out

    async def _think(self, agent: str, span: str, system: str, prompt: str, scripted: str) -> str:
        out = await self.gw.chat(
            agent=agent, system=system, prompt=prompt, scripted_response=scripted, parent=span
        )
        await self.emit(
            {
                "type": "llm",
                "agent": agent,
                "mode": out["mode"],
                "provider": out["provider"],
                "model": out["model"],
                "tokens": out["input_tokens"] + out["output_tokens"],
                "pii_masked": out["pii_masked"],
            }
        )
        return out["text"].strip() or scripted

    async def _handoff(self, sender: str, recipient: str, message: str, span: str) -> None:
        await self.gw.send_task(sender, recipient, message, parent=span)
        await self.emit({"type": "a2a", "from": sender, "to": recipient, "message": message[:400]})

    # ---------- agents ----------

    async def planner(self, state: CrewState) -> CrewState:
        task = state["task"]
        scripted = (
            "1. Identify the customer(s) named in the request\n"
            "2. Pull the profile, account health and open support tickets\n"
            "3. Check commercial terms, if policy allows\n"
            "4. Draft a brief with risks and next steps\n"
            "5. Review the brief for leaked personal data"
        )
        async with self._step("planner") as span:
            plan = await self._think(
                "planner",
                span,
                system=(
                    "You are the Planner in a customer-research crew. The researcher can use: "
                    "search_customers, get_customer, list_open_tickets, get_contract, calculator. "
                    "Reply with 3-5 short numbered steps only."
                ),
                prompt=f"Request: {task}",
                scripted=scripted,
            )
            await self._handoff("planner", "researcher", f"Request: {task}\n\nPlan:\n{plan}", span)
        return {"plan": plan}

    async def researcher(self, state: CrewState) -> CrewState:
        task = state["task"].lower()
        notes: list[dict[str, Any]] = []
        async with self._step("researcher") as span:
            found = await self._tool("researcher", span, "company_kb", "search_customers", query="")
            rows = (found.get("structured") or {}).get("customers", [])
            targets = [r for r in rows if r["id"] in task or r["company"].lower().split()[0] in task]
            if not targets:  # nothing named: brief on accounts that need attention
                targets = [r for r in rows if r["health"] != "healthy"] or rows
            for row in targets[:MAX_TARGETS]:
                cid = row["id"]
                profile = (
                    await self._tool("researcher", span, "company_kb", "get_customer", customer_id=cid)
                ).get("structured") or {}
                tickets = (
                    await self._tool("researcher", span, "company_kb", "list_open_tickets", customer_id=cid)
                ).get("structured") or {}
                contract = await self._tool("researcher", span, "company_kb", "get_contract", customer_id=cid)
                monthly = await self._tool(
                    "researcher", span, "utils", "calculator", expression=f"{profile.get('arr_usd', 0)} / 12"
                )
                notes.append(
                    {
                        **{
                            k: profile.get(k)
                            for k in ("company", "industry", "tier", "region", "health", "arr_usd")
                        },
                        "monthly_revenue": (monthly.get("structured") or {}).get("result"),
                        "contact": profile.get("contact"),
                        "account_manager": profile.get("account_manager"),
                        "notes": profile.get("notes"),
                        "tickets": tickets.get("tickets", []),
                        "contract": contract.get("structured") if contract.get("ok") else None,
                        "contract_blocked": None if contract.get("ok") else contract.get("reason"),
                    }
                )
            await self._handoff(
                "researcher", "writer", "Research notes:\n" + json.dumps(notes, indent=1, default=str), span
            )
        return {"notes": notes}

    async def writer(self, state: CrewState) -> CrewState:
        notes = state["notes"]
        scripted = "\n\n".join(_brief_section(n) for n in notes) or "No matching customers were found."
        async with self._step("writer") as span:
            draft = await self._think(
                "writer",
                span,
                system=(
                    "You are the Writer. Turn research notes into a concise customer brief in "
                    "Markdown: snapshot, revenue, open tickets, risks and 2-3 recommended next steps. "
                    "Keep placeholders like <PERSON> exactly as they are; never invent contact "
                    "details or contract terms."
                ),
                prompt=f"Request: {state['task']}\n\nResearch notes (JSON):\n"
                + json.dumps(notes, default=str),
                scripted=scripted,
            )
            await self._handoff("writer", "reviewer", draft, span)
        return {"draft": draft}

    async def reviewer(self, state: CrewState) -> CrewState:
        draft = state["draft"]
        async with self._step("reviewer") as span:
            stats = await self._tool("reviewer", span, "utils", "word_count", text=draft)
            leaks = _LEAK.findall(draft)
            if leaks:  # belt and braces: redact anything that slipped through
                draft = _LEAK.sub("<REDACTED>", draft)
            words = (stats.get("structured") or {}).get("words", len(draft.split()))
            scripted = (
                f"{'Approved' if not leaks else 'Approved after redacting ' + str(len(leaks)) + ' item(s)'}. "
                f"{draft.count('<')} personal-data placeholders remain masked, contract terms are excluded "
                f"as required by policy, and the brief is {words} words."
            )
            review = await self._think(
                "reviewer",
                span,
                system=(
                    "You are the Reviewer. Check the brief for leaked personal data (emails, phone numbers, "
                    "names that are not placeholders) and unsupported claims. Reply in 1-2 sentences, "
                    "starting with 'Approved' or 'Needs changes'."
                ),
                prompt=draft,
                scripted=scripted,
            )
            await self._handoff("reviewer", "planner", f"Review complete: {review}", span)
        return {"draft": draft, "review": review, "approved": not review.lower().startswith("needs")}

    # ---------- graph ----------

    def build(self):
        graph = StateGraph(CrewState)
        for name in ("planner", "researcher", "writer", "reviewer"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "researcher")
        graph.add_edge("researcher", "writer")
        graph.add_edge("writer", "reviewer")
        graph.add_edge("reviewer", END)
        return graph.compile()

    async def run(self, task: str) -> CrewState:
        return await self.build().ainvoke({"task": task})


def _brief_section(n: dict[str, Any]) -> str:
    money = lambda v: f"${v:,.0f}" if isinstance(v, int | float) else "n/a"  # noqa: E731
    tickets = n.get("tickets") or []
    lines = [
        f"## {n.get('company')}",
        f"**Snapshot:** {n.get('tier')} · {n.get('industry')} · {n.get('region')} · "
        f"health: **{n.get('health')}**",
        f"**Revenue:** {money(n.get('arr_usd'))} ARR (≈ {money(n.get('monthly_revenue'))}/month)",
        f"**Primary contact:** {(n.get('contact') or {}).get('name', 'n/a')} · "
        f"account manager {n.get('account_manager')} (contact details withheld by AgentHub)",
        f"**Open tickets ({len(tickets)}):**",
        *([f"- [{t['priority']}] {t['id']}: {t['summary']}" for t in tickets] or ["- none"]),
        f"**Account notes:** {n.get('notes')}",
        "**Contract terms:** "
        + (
            f"blocked by policy: {n['contract_blocked']}"
            if n.get("contract_blocked")
            else json.dumps(n.get("contract"))
        ),
        "**Recommended next steps:**",
    ]
    steps = []
    if n.get("health") != "healthy":
        steps.append("- Book an executive check-in before the renewal window opens")
    if any(t["priority"] == "high" for t in tickets):
        top = next(t for t in tickets if t["priority"] == "high")
        steps.append(f"- Escalate {top['id']} with engineering and share a fix date")
    steps.append("- Ask the legal team for contract terms before discussing pricing")
    return "\n".join(lines + steps)
