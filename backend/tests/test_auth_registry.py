import pytest

from app.config import get_settings


def login(client, username: str, password: str) -> dict:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client, "admin", "admin")


@pytest.fixture
def viewer(client):
    return login(client, "demo", "demo")


NEW_AGENT = {
    "slug": "sales-copilot",
    "name": "Sales Copilot",
    "framework": "langgraph",
    "owner": "sales",
    "skills": [{"id": "qualify", "name": "Lead qualification"}],
}


def test_login_rejects_bad_password(client):
    assert client.post("/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401


def test_requests_without_credentials_are_rejected(client):
    assert client.get("/agents").status_code == 401
    assert client.get("/agents", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_viewer_can_read_but_not_write(client, viewer):
    assert client.get("/agents", headers=viewer).status_code == 200
    assert client.post("/agents", json=NEW_AGENT, headers=viewer).status_code == 403
    assert client.put("/policies", json=[], headers=viewer).status_code == 403


def test_agent_crud_and_card(client, admin):
    res = client.post("/agents", json=NEW_AGENT, headers=admin)
    assert res.status_code == 201
    assert client.post("/agents", json=NEW_AGENT, headers=admin).status_code == 409

    card = client.get("/agents/sales-copilot/card", headers=admin).json()
    assert card["name"] == "Sales Copilot"
    assert card["provider"]["organization"] == "sales"
    assert card["url"].endswith("/a2a/sales-copilot/tasks")

    # Round-trip: an exported card can be imported as a new agent
    res = client.post("/agents/import-card", json={"card": card, "slug": "sales-copilot-2"}, headers=admin)
    assert res.status_code == 201
    assert res.json()["framework"] == "langgraph"

    assert client.delete("/agents/sales-copilot", headers=admin).status_code == 204
    assert client.get("/agents/sales-copilot", headers=admin).status_code == 404


def test_api_key_lifecycle(client, admin):
    res = client.post("/keys", json={"name": "ci-bot", "role": "developer"}, headers=admin)
    assert res.status_code == 201
    raw, key_id = res.json()["key"], res.json()["id"]
    assert raw.startswith("ah_")

    # Works as X-API-Key and as a bearer token
    assert client.get("/auth/me", headers={"X-API-Key": raw}).json()["role"] == "developer"
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    # The raw key is never listed again
    assert all("key" not in k for k in client.get("/keys", headers=admin).json())

    assert client.delete(f"/keys/{key_id}", headers=admin).status_code == 204
    assert client.get("/auth/me", headers={"X-API-Key": raw}).status_code == 401


def test_crew_key_authenticates_as_agent(client):
    me = client.get("/auth/me", headers={"X-API-Key": get_settings().crew_api_key}).json()
    assert me == {"name": "research-crew", "role": "agent", "kind": "key"}


def test_server_validation_and_listing(client, admin):
    bad = {"slug": "web", "name": "Web", "transport": "http"}  # http without url
    assert client.post("/servers", json=bad, headers=admin).status_code == 422
    slugs = {s["server"]["slug"] for s in client.get("/servers", headers=admin).json()}
    assert slugs == {"company_kb", "utils"}


def test_policies_replace(client, admin):
    rules = [{"priority": 1, "role": "*", "effect": "deny", "description": "lockdown"}]
    res = client.put("/policies", json=rules, headers=admin)
    assert res.status_code == 200
    assert [p["description"] for p in res.json()] == ["lockdown"]


def test_stdio_registration_disabled_by_default(client, admin):
    body = {"slug": "shell", "name": "Shell", "transport": "stdio", "command": "bash"}
    assert client.post("/servers", json=body, headers=admin).status_code == 403
    http = {"slug": "weather", "name": "Weather", "transport": "http", "url": "http://localhost:9000/mcp"}
    assert client.post("/servers", json=http, headers=admin).status_code == 201
