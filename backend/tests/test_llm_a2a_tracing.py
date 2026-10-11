from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.config import Settings, get_settings
from app.gateway.llm import resolve_provider
from app.models import Run, Span
from tests.test_auth_registry import login


@pytest.fixture
def agent():
    return {"X-API-Key": get_settings().crew_api_key}


def test_provider_resolution():
    assert resolve_provider(Settings(_env_file=None)).name == "scripted"
    p = resolve_provider(Settings(_env_file=None, GROQ_API_KEY="g", OPENAI_API_KEY="o"))
    assert (p.name, p.base_url) == ("groq", "https://api.groq.com/openai/v1")
    p = resolve_provider(Settings(_env_file=None, ANTHROPIC_API_KEY="a", GOOGLE_API_KEY="g"))
    assert (p.name, p.model) == ("anthropic", "claude-haiku-5-5")
    assert resolve_provider(Settings(_env_file=None, llm_provider="ollama")).base_url.endswith("/v1")


def test_scripted_chat_masks_prompt_and_records_span(client, agent, session):
    body = {
        "agent": "writer",
        "system": "You write customer briefs.",
        "messages": [
            {"role": "user", "content": "Summarise: Priya Sharma, priya@acme.example.com, wants a QBR."}
        ],
        "scripted_response": "Acme wants a quarterly business review.",
    }
    res = client.post("/gateway/llm/chat", json=body, headers={**agent, "X-AgentHub-Run-Id": "r1"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["mode"] == "scripted" and out["text"] == "Acme wants a quarterly business review."
    assert out["pii_masked"]["EMAIL_ADDRESS"] == 1 and out["pii_masked"]["PERSON"] >= 1
    span = session.get(Span, out["span_id"])
    assert span.kind == "llm" and span.run_id == "r1" and span.attrs["mode"] == "scripted"


def test_provider_failure_falls_back_to_scripted(client, agent, monkeypatch):
    # A bogus key against an unreachable endpoint must not break the run.
    monkeypatch.setattr(
        "app.gateway.llm.get_settings",
        lambda: Settings(
            _env_file=None, llm_provider="ollama", ollama_url="http://127.0.0.1:9/v1", llm_timeout_seconds=2
        ),
    )
    body = {"messages": [{"role": "user", "content": "hi"}], "scripted_response": "fallback text"}
    out = client.post("/gateway/llm/chat", json=body, headers=agent).json()
    assert out["mode"] == "scripted" and out["text"] == "fallback text"
    assert out["fallback_reason"].startswith("ollama failed")


def test_a2a_delivery_and_validation(client, agent, session):
    headers = {**agent, "X-AgentHub-Run-Id": "r2"}
    ok = client.post(
        "/a2a/researcher/tasks", json={"sender": "planner", "message": "Find Acme facts"}, headers=headers
    )
    assert ok.status_code == 200 and ok.json()["status"] == "delivered"
    assert (
        client.post("/a2a/ghost/tasks", json={"sender": "planner", "message": "x"}, headers=agent).status_code
        == 404
    )
    inactive = client.post(
        "/a2a/invoice-extractor/tasks", json={"sender": "planner", "message": "x"}, headers=agent
    )
    assert inactive.status_code == 409
    viewer = login(client, "demo", "demo")
    assert (
        client.post(
            "/a2a/writer/tasks", json={"sender": "planner", "message": "x"}, headers=viewer
        ).status_code
        == 403
    )
    msgs = client.get("/a2a/messages", params={"run_id": "r2"}, headers=viewer).json()
    assert [(m["sender"], m["recipient"]) for m in msgs] == [("planner", "researcher")]


def test_reported_spans_and_run_detail(client, agent, session):
    session.add(Run(id="r3", task="demo", started_by="test"))
    session.commit()
    now = datetime.now(UTC)
    span = {
        "id": "span-abc-123",
        "run_id": "r3",
        "name": "planner",
        "kind": "agent",
        "start": (now - timedelta(seconds=1)).isoformat(),
        "end": now.isoformat(),
    }
    assert client.post("/traces/spans", json=span, headers=agent).status_code == 201
    assert client.post("/traces/spans", json=span, headers=agent).status_code == 409
    client.post(
        "/gateway/tools/utils/word_count",
        json={"arguments": {"text": "a b"}},
        headers={**agent, "X-AgentHub-Run-Id": "r3", "X-AgentHub-Parent-Span": "span-abc-123"},
    )

    viewer = login(client, "demo", "demo")
    detail = client.get("/runs/r3", headers=viewer).json()
    kinds = {s["kind"] for s in detail["spans"]}
    assert kinds == {"agent", "tool"}
    tool_span = next(s for s in detail["spans"] if s["kind"] == "tool")
    assert tool_span["parent_id"] == "span-abc-123"
    assert len(detail["audit"]) == 1
    assert (
        session.exec(select(Span).where(Span.id == "span-abc-123")).one().attrs["reported_by"]
        == "research-crew"
    )
