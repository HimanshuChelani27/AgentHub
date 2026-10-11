"""Database tables. JSON columns hold flexible data (skills, tool schemas, span attributes)."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(StrEnum):
    admin = "admin"
    developer = "developer"
    agent = "agent"
    viewer = "viewer"


class Decision(StrEnum):
    allowed = "allowed"
    denied = "denied"
    error = "error"
    rate_limited = "rate_limited"


# ---------- identity ----------


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: Role
    created_at: datetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    prefix: str = Field(index=True)  # first chars, shown in UI to identify a key
    key_hash: str = Field(unique=True, index=True)
    role: Role
    agent_slug: str | None = None  # set when the key belongs to a registered agent
    revoked: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None


# ---------- registry ----------


class Agent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str = ""
    version: str = "1.0.0"
    framework: str = "langgraph"  # langgraph | autogen | google-adk | crewai | custom
    owner: str = "platform-team"
    status: str = "active"  # active | inactive
    endpoint: str | None = None
    skills: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class McpServer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str = ""
    transport: str = "stdio"  # stdio | http
    command: str | None = None
    args: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    url: str | None = None
    enabled: bool = True
    status: str = "unknown"  # unknown | connected | error
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Tool(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("server_slug", "name"),)

    id: int | None = Field(default=None, primary_key=True)
    server_slug: str = Field(index=True)
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    discovered_at: datetime = Field(default_factory=utcnow)


class Policy(SQLModel, table=True):
    """First matching rule (lowest priority number) wins; no match means deny."""

    id: int | None = Field(default=None, primary_key=True)
    priority: int = 100
    role: str = "*"  # role name or "*"
    server: str = "*"  # glob on server slug
    tool: str = "*"  # glob on tool name
    effect: str = "allow"  # allow | deny
    mask_pii: bool = True
    description: str = ""


# ---------- observability ----------


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    principal: str  # username, key name or agent slug
    role: str
    kind: str  # tool | llm | a2a
    server: str | None = None
    tool: str | None = None
    decision: Decision
    reason: str = ""
    pii_masked: int = 0
    latency_ms: int = 0
    run_id: str | None = Field(default=None, index=True)
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Run(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    task: str
    status: str = "running"  # running | succeeded | failed
    mode: str = "scripted"  # scripted | live
    started_by: str
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = None
    output: str | None = None


class Span(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    parent_id: str | None = None
    name: str
    kind: str  # run | agent | llm | tool | a2a
    status: str = "ok"  # ok | error | denied
    start: datetime = Field(default_factory=utcnow)
    end: datetime | None = None
    attrs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class A2AMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    ts: datetime = Field(default_factory=utcnow)
    sender: str
    recipient: str
    content: str
