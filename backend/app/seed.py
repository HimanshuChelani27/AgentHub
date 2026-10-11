"""Demo data: users, the Research Crew's API key, policies, registered agents and MCP servers.
Idempotent: rows are only created when missing."""

from sqlmodel import Session, select

from app.auth.security import hash_api_key, hash_password, key_display_prefix
from app.config import Settings
from app.models import Agent, ApiKey, McpServer, Policy, Role, User

CREW_AGENTS = [
    {
        "slug": "planner",
        "name": "Planner",
        "description": "Breaks a request into research questions and delegates them to the researcher.",
        "skills": [{"id": "plan", "name": "Task planning", "description": "Decompose a goal into steps"}],
    },
    {
        "slug": "researcher",
        "name": "Researcher",
        "description": "Gathers facts with MCP tools (knowledge base, utilities) via the gateway.",
        "skills": [{"id": "research", "name": "Tool-based research", "description": "Query MCP tools"}],
    },
    {
        "slug": "writer",
        "name": "Writer",
        "description": "Turns research notes into a concise, structured brief.",
        "skills": [{"id": "write", "name": "Brief writing", "description": "Summarise findings"}],
    },
    {
        "slug": "reviewer",
        "name": "Reviewer",
        "description": "Checks the brief for unsupported claims and leaked personal data.",
        "skills": [{"id": "review", "name": "Quality review", "description": "Fact and PII check"}],
    },
]

# Registry-only examples, to show agents from other frameworks living in one catalogue.
EXAMPLE_AGENTS = [
    {
        "slug": "support-triage",
        "name": "Support Triage",
        "description": "Classifies incoming support tickets and routes them to the right queue.",
        "framework": "autogen",
        "owner": "customer-success",
        "skills": [{"id": "triage", "name": "Ticket triage", "description": "Classify and route tickets"}],
    },
    {
        "slug": "invoice-extractor",
        "name": "Invoice Extractor",
        "description": "Extracts line items and totals from supplier invoices.",
        "framework": "google-adk",
        "owner": "finance-ops",
        "status": "inactive",
        "skills": [{"id": "extract", "name": "Invoice extraction", "description": "PDF to structured data"}],
    },
]

MCP_SERVERS = [
    {
        "slug": "company_kb",
        "name": "Company Knowledge Base",
        "description": "Customers, accounts and contracts. Returns personal data, so the gateway masks it.",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "mcp_servers.company_kb"],
    },
    {
        "slug": "utils",
        "name": "Utilities",
        "description": "Calculator, clock and text helpers.",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "mcp_servers.utils"],
    },
]

POLICIES = [
    {
        "priority": 10,
        "role": "admin",
        "effect": "allow",
        "mask_pii": False,
        "description": "Admins have full, unmasked access",
    },
    {
        "priority": 20,
        "role": "*",
        "server": "company_kb",
        "tool": "get_contract",
        "effect": "deny",
        "description": "Contracts are restricted to the legal team",
    },
    {
        "priority": 30,
        "role": "agent",
        "server": "company_kb",
        "effect": "allow",
        "mask_pii": True,
        "description": "Agents may read the knowledge base with PII masked",
    },
    {
        "priority": 40,
        "role": "agent",
        "server": "utils",
        "effect": "allow",
        "mask_pii": False,
        "description": "Agents may use utilities",
    },
    {
        "priority": 50,
        "role": "developer",
        "effect": "allow",
        "mask_pii": True,
        "description": "Developers may call any tool, PII masked",
    },
    {
        "priority": 60,
        "role": "viewer",
        "effect": "allow",
        "mask_pii": True,
        "description": "Viewers may try tools in the console, PII masked",
    },
]


def seed(session: Session, settings: Settings) -> None:
    def ensure_user(username: str, password: str, role: Role) -> None:
        if not session.exec(select(User).where(User.username == username)).first():
            session.add(User(username=username, password_hash=hash_password(password), role=role))

    ensure_user(settings.admin_username, settings.admin_password, Role.admin)
    if settings.demo_mode:
        ensure_user(settings.demo_username, settings.demo_password, Role.viewer)

    crew_hash = hash_api_key(settings.crew_api_key)
    if not session.exec(select(ApiKey).where(ApiKey.key_hash == crew_hash)).first():
        session.add(
            ApiKey(
                name="research-crew",
                prefix=key_display_prefix(settings.crew_api_key),
                key_hash=crew_hash,
                role=Role.agent,
                agent_slug="research-crew",
            )
        )

    existing_agents = set(session.exec(select(Agent.slug)).all())
    for spec in CREW_AGENTS:
        if spec["slug"] not in existing_agents:
            session.add(Agent(framework="langgraph", owner="platform-team", version="1.2.0", **spec))
    for spec in EXAMPLE_AGENTS:
        if spec["slug"] not in existing_agents:
            session.add(Agent(**spec))

    existing_servers = set(session.exec(select(McpServer.slug)).all())
    for spec in MCP_SERVERS:
        if spec["slug"] not in existing_servers:
            session.add(McpServer(**spec))

    if not session.exec(select(Policy)).first():
        for spec in POLICIES:
            session.add(Policy(**spec))

    session.commit()
