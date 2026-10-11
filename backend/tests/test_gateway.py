import pytest

from app.config import get_settings
from app.gateway.ratelimit import RateLimiter
from app.models import AuditEvent, Span
from tests.test_auth_registry import login


@pytest.fixture
def agent():
    return {"X-API-Key": get_settings().crew_api_key}


def call(client, headers, server, tool, **arguments):
    return client.post(f"/gateway/tools/{server}/{tool}", json={"arguments": arguments}, headers=headers)


def test_agent_gets_masked_customer_data(client, agent, session):
    res = call(client, agent, "company_kb", "get_customer", customer_id="acme")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["decision"] == "allowed"

    data = body["structured"]
    assert data["company"] == "Acme Corp"  # business data passes through
    assert data["contact"]["email"] == "<EMAIL_ADDRESS>"
    assert data["contact"]["name"] == "<PERSON>"
    assert "priya.sharma@acme" not in body["content"][0]["text"]  # text mirror is masked too
    assert "Mark Liu" not in data["notes"]
    assert body["pii_masked"]["EMAIL_ADDRESS"] >= 2

    event = session.get(AuditEvent, body["audit_id"])
    assert event.principal == "research-crew" and event.decision == "allowed"
    assert event.pii_masked == sum(body["pii_masked"].values())


def test_admin_sees_unmasked_data(client):
    admin = login(client, "admin", "admin")
    body = call(client, admin, "company_kb", "get_customer", customer_id="acme").json()
    assert body["structured"]["contact"]["email"] == "priya.sharma@acme.example.com"
    assert body["pii_masked"] == {}


def test_policy_denial_is_explained_and_audited(client, agent, session):
    res = call(client, agent, "company_kb", "get_contract", customer_id="acme")
    assert res.status_code == 403
    body = res.json()
    assert body["decision"] == "denied" and "legal team" in body["reason"]
    assert body["content"] == []  # the tool was never called
    assert session.get(AuditEvent, body["audit_id"]).decision == "denied"


def test_tool_errors_are_reported_not_raised(client, agent):
    res = call(client, agent, "company_kb", "get_customer", customer_id="nobody")
    assert res.status_code == 200
    body = res.json()
    assert not body["ok"] and body["decision"] == "error"
    assert "Unknown customer" in body["content"][0]["text"]


def test_unmasked_utils_call(client, agent):
    body = call(client, agent, "utils", "calculator", expression="480000 * 0.18").json()
    assert body["ok"] and body["structured"]["result"] == 86400


def test_unknown_tool_is_404(client, agent):
    assert call(client, agent, "utils", "rm_rf").status_code == 404


def test_visible_tools_respect_policy(client, agent):
    names = {t["qualified_name"] for t in client.get("/gateway/tools", headers=agent).json()}
    assert "company_kb__get_customer" in names and "utils__calculator" in names
    assert "company_kb__get_contract" not in names


def test_rate_limit(client, agent):
    client.app.state.limiter = RateLimiter(per_minute=2)
    codes = [call(client, agent, "utils", "word_count", text="hi").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_run_headers_create_linked_span(client, agent, session):
    headers = {**agent, "X-AgentHub-Run-Id": "run123", "X-AgentHub-Parent-Span": "parent1"}
    body = call(client, headers, "utils", "current_time", timezone="Asia/Kolkata").json()
    span = session.get(Span, body["span_id"])
    assert (span.run_id, span.parent_id, span.kind, span.name) == (
        "run123",
        "parent1",
        "tool",
        "utils.current_time",
    )


def test_audit_and_stats_endpoints(client, agent):
    call(client, agent, "company_kb", "get_customer", customer_id="globex")
    call(client, agent, "company_kb", "get_contract", customer_id="globex")
    viewer = login(client, "demo", "demo")
    denied = client.get("/audit", params={"decision": "denied"}, headers=viewer).json()
    assert len(denied) == 1 and denied[0]["tool"] == "get_contract"
    stats = client.get("/stats", headers=viewer).json()
    assert stats["calls_24h"] == 2 and stats["denied_24h"] == 1 and stats["pii_masked_24h"] > 0
    assert sum(b["allowed"] + b["denied"] for b in stats["timeline"]) == 2
