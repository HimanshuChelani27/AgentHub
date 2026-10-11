import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, delete, select

from app.auth.deps import admin_only, can_edit, get_principal
from app.config import get_settings
from app.db import get_session
from app.gateway.mcp_pool import connect_and_save
from app.models import Agent, McpServer, Policy, Tool

router = APIRouter(tags=["registry"], dependencies=[Depends(get_principal)])

SLUG = r"^[a-z0-9][a-z0-9_-]{1,62}$"


def _get_or_404(session: Session, model, slug: str):
    obj = session.exec(select(model).where(model.slug == slug)).first()
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} '{slug}' not found")
    return obj


# ---------- agents ----------


class Skill(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = []


class AgentIn(BaseModel):
    slug: str = Field(pattern=SLUG)
    name: str
    description: str = ""
    version: str = "1.0.0"
    framework: str = "custom"
    owner: str = "unknown"
    status: Literal["active", "inactive"] = "active"
    endpoint: str | None = None
    skills: list[Skill] = []


@router.get("/agents", response_model=list[Agent])
def list_agents(session: Session = Depends(get_session)):
    return session.exec(select(Agent).order_by(Agent.name)).all()


@router.get("/agents/{slug}", response_model=Agent)
def get_agent(slug: str, session: Session = Depends(get_session)):
    return _get_or_404(session, Agent, slug)


@router.post("/agents", response_model=Agent, status_code=201, dependencies=[Depends(can_edit)])
def create_agent(body: AgentIn, session: Session = Depends(get_session)):
    if session.exec(select(Agent).where(Agent.slug == body.slug)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Agent '{body.slug}' already exists")
    agent = Agent(**body.model_dump())
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.put("/agents/{slug}", response_model=Agent, dependencies=[Depends(can_edit)])
def update_agent(slug: str, body: AgentIn, session: Session = Depends(get_session)):
    agent = _get_or_404(session, Agent, slug)
    if body.slug != slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Slug cannot be changed")
    for k, v in body.model_dump().items():
        setattr(agent, k, v)
    agent.updated_at = datetime.now(UTC)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.delete("/agents/{slug}", status_code=204, dependencies=[Depends(admin_only)])
def delete_agent(slug: str, session: Session = Depends(get_session)) -> None:
    session.delete(_get_or_404(session, Agent, slug))
    session.commit()


@router.get("/agents/{slug}/card")
def agent_card(slug: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """The agent described as an A2A Agent Card."""
    a = _get_or_404(session, Agent, slug)
    return {
        "name": a.name,
        "description": a.description,
        "url": a.endpoint or f"{str(request.base_url).rstrip('/')}/a2a/{a.slug}/tasks",
        "version": a.version,
        "provider": {"organization": a.owner},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": a.skills,
        "metadata": {"framework": a.framework, "status": a.status, "registry": "agenthub"},
    }


class CardImport(BaseModel):
    card: dict[str, Any]
    slug: str | None = Field(default=None, pattern=SLUG)


@router.post("/agents/import-card", response_model=Agent, status_code=201, dependencies=[Depends(can_edit)])
def import_card(body: CardImport, session: Session = Depends(get_session)):
    card = body.card
    if "name" not in card:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Agent Card must include 'name'")
    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", card["name"].lower()).strip("-")[:63]
    meta = card.get("metadata", {})
    agent_in = AgentIn(
        slug=slug,
        name=card["name"],
        description=card.get("description", ""),
        version=card.get("version", "1.0.0"),
        framework=meta.get("framework", "custom"),
        owner=(card.get("provider") or {}).get("organization", "unknown"),
        endpoint=card.get("url"),
        skills=card.get("skills", []),
    )
    return create_agent(agent_in, session)


# ---------- MCP servers ----------


class ServerIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,40}$")  # no dashes: used in "server__tool" names
    name: str
    description: str = ""
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def check_transport(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio servers need a command")
        if self.transport == "http" and not self.url:
            raise ValueError("http servers need a url")
        return self


class ServerOut(BaseModel):
    server: McpServer
    tools: list[Tool]


def _server_out(session: Session, server: McpServer) -> ServerOut:
    tools = session.exec(select(Tool).where(Tool.server_slug == server.slug).order_by(Tool.name)).all()
    return ServerOut(server=server, tools=list(tools))


@router.get("/servers", response_model=list[ServerOut])
def list_servers(session: Session = Depends(get_session)):
    return [_server_out(session, s) for s in session.exec(select(McpServer).order_by(McpServer.name)).all()]


@router.get("/servers/{slug}", response_model=ServerOut)
def get_server(slug: str, session: Session = Depends(get_session)):
    return _server_out(session, _get_or_404(session, McpServer, slug))


@router.post("/servers", response_model=ServerOut, status_code=201, dependencies=[Depends(admin_only)])
async def create_server(body: ServerIn, request: Request, session: Session = Depends(get_session)):
    if body.transport == "stdio" and not get_settings().allow_stdio_registration:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registering stdio servers is disabled (set AGENTHUB_ALLOW_STDIO_REGISTRATION=true to enable)",
        )
    if session.exec(select(McpServer).where(McpServer.slug == body.slug)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Server '{body.slug}' already exists")
    server = McpServer(**body.model_dump())
    session.add(server)
    session.commit()
    session.refresh(server)
    if server.enabled:
        await connect_and_save(request.app.state.pool, session, server)
    return _server_out(session, server)


@router.post("/servers/{slug}/refresh", response_model=ServerOut, dependencies=[Depends(can_edit)])
async def refresh_server(slug: str, request: Request, session: Session = Depends(get_session)):
    """Reconnect to the server and rediscover its tools."""
    server = _get_or_404(session, McpServer, slug)
    await connect_and_save(request.app.state.pool, session, server)
    return _server_out(session, server)


@router.delete("/servers/{slug}", status_code=204, dependencies=[Depends(admin_only)])
async def delete_server(slug: str, request: Request, session: Session = Depends(get_session)) -> None:
    server = _get_or_404(session, McpServer, slug)
    await request.app.state.pool.disconnect(slug)
    session.exec(delete(Tool).where(Tool.server_slug == slug))
    session.delete(server)
    session.commit()


# ---------- policies ----------


class PolicyIn(BaseModel):
    priority: int = 100
    role: str = "*"
    server: str = "*"
    tool: str = "*"
    effect: Literal["allow", "deny"] = "allow"
    mask_pii: bool = True
    description: str = ""


@router.get("/policies", response_model=list[Policy])
def list_policies(session: Session = Depends(get_session)):
    return session.exec(select(Policy).order_by(Policy.priority, Policy.id)).all()


@router.put("/policies", response_model=list[Policy], dependencies=[Depends(admin_only)])
def replace_policies(body: list[PolicyIn], session: Session = Depends(get_session)):
    """Replace the whole rule set atomically (the dashboard edits it as one list)."""
    session.exec(delete(Policy))
    for p in body:
        session.add(Policy(**p.model_dump()))
    session.commit()
    return list_policies(session)
