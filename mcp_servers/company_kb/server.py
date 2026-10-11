"""Company Knowledge Base: a demo MCP server over fictional CRM data.

It deliberately returns personal data (names, emails, phone numbers) so the
AgentHub gateway has something to mask. All people and companies are made up."""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer(
    "company_kb",
    description="Fictional CRM: customers, support tickets and contracts.",
    version="1.0.0",
)

CUSTOMERS: dict[str, dict[str, Any]] = {
    "acme": {
        "id": "acme",
        "company": "Acme Corp",
        "industry": "Manufacturing",
        "tier": "Enterprise",
        "region": "North America",
        "arr_usd": 480_000,
        "health": "at-risk",
        "contact": {
            "name": "Priya Sharma",
            "email": "priya.sharma@acme.example.com",
            "phone": "+1 555 0142 881",
        },
        "account_manager": "Daniel Brooks",
        "notes": (
            "Renewal due in Q1. Priya Sharma (priya.sharma@acme.example.com) raised concerns about "
            "dashboard latency. Escalation contact: Mark Liu, +1 555 0199 230."
        ),
    },
    "globex": {
        "id": "globex",
        "company": "Globex Logistics",
        "industry": "Logistics",
        "tier": "Growth",
        "region": "Europe",
        "arr_usd": 126_000,
        "health": "healthy",
        "contact": {
            "name": "Sofia Romano",
            "email": "sofia.romano@globex.example.com",
            "phone": "+44 20 7946 0321",
        },
        "account_manager": "Aisha Khan",
        "notes": "Expanding to two new warehouses; interested in the routing add-on. Prefers email.",
    },
    "initech": {
        "id": "initech",
        "company": "Initech Health",
        "industry": "Healthcare",
        "tier": "Enterprise",
        "region": "Asia Pacific",
        "arr_usd": 315_000,
        "health": "healthy",
        "contact": {
            "name": "Rahul Mehta",
            "email": "rahul.mehta@initech.example.com",
            "phone": "+91 98765 43210",
        },
        "account_manager": "Daniel Brooks",
        "notes": "HIPAA review completed in March. Rahul Mehta wants a quarterly business review.",
    },
}

TICKETS: dict[str, list[dict[str, Any]]] = {
    "acme": [
        {
            "id": "T-1042",
            "priority": "high",
            "status": "open",
            "summary": "Dashboard takes 12s to load for plant managers",
        },
        {
            "id": "T-1057",
            "priority": "medium",
            "status": "open",
            "summary": "SSO login loop reported by john.doe@acme.example.com",
        },
    ],
    "globex": [
        {
            "id": "T-0988",
            "priority": "low",
            "status": "open",
            "summary": "Request for CSV export of route history",
        }
    ],
    "initech": [],
}

CONTRACTS: dict[str, dict[str, Any]] = {
    "acme": {"value_usd": 1_440_000, "term_years": 3, "renewal_date": "2027-01-31", "discount_pct": 18},
    "globex": {"value_usd": 252_000, "term_years": 2, "renewal_date": "2027-06-30", "discount_pct": 10},
    "initech": {"value_usd": 945_000, "term_years": 3, "renewal_date": "2028-03-15", "discount_pct": 15},
}


def _find(customer_id: str) -> dict[str, Any]:
    customer = CUSTOMERS.get(customer_id.lower().strip())
    if not customer:
        raise ToolError(f"Unknown customer '{customer_id}'. Try search_customers first.")
    return customer


@mcp.tool()
def search_customers(query: str = "") -> dict[str, Any]:
    """Search customers by company name, industry or region. Returns summary rows (no contact details)."""
    q = query.lower().strip()
    rows = [
        {k: c[k] for k in ("id", "company", "industry", "tier", "region", "health", "account_manager")}
        for c in CUSTOMERS.values()
        if not q or q in f"{c['company']} {c['industry']} {c['region']}".lower()
    ]
    return {"count": len(rows), "customers": rows}


@mcp.tool()
def get_customer(customer_id: str) -> dict[str, Any]:
    """Full customer profile including primary contact, account health and notes."""
    return _find(customer_id)


@mcp.tool()
def list_open_tickets(customer_id: str) -> dict[str, Any]:
    """Open support tickets for a customer."""
    _find(customer_id)
    tickets = [t for t in TICKETS.get(customer_id, []) if t["status"] == "open"]
    return {"customer_id": customer_id, "open": len(tickets), "tickets": tickets}


@mcp.tool()
def get_contract(customer_id: str) -> dict[str, Any]:
    """Commercial contract terms (restricted: AgentHub policy only allows the legal team)."""
    _find(customer_id)
    return {"customer_id": customer_id, **CONTRACTS[customer_id]}
