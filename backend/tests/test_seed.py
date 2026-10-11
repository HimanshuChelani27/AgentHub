from sqlmodel import select

from app.auth.security import hash_api_key, verify_password
from app.config import get_settings
from app.models import Agent, ApiKey, McpServer, Policy, Role, User
from app.seed import seed


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_seed_creates_demo_data(session):
    users = {u.username: u for u in session.exec(select(User)).all()}
    assert users["admin"].role == Role.admin
    assert users["demo"].role == Role.viewer
    assert verify_password("demo", users["demo"].password_hash)

    assert {a.slug for a in session.exec(select(Agent)).all()} >= {
        "planner",
        "researcher",
        "writer",
        "reviewer",
    }
    assert {s.slug for s in session.exec(select(McpServer)).all()} == {"company_kb", "utils"}

    crew_key = session.exec(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(get_settings().crew_api_key))
    ).one()
    assert crew_key.role == Role.agent


def test_seed_is_idempotent(session):
    def counts():
        return tuple(len(session.exec(select(m)).all()) for m in (User, Agent, McpServer, Policy, ApiKey))

    before = counts()
    seed(session, get_settings())
    assert counts() == before
