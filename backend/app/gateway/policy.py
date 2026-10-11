from dataclasses import dataclass
from fnmatch import fnmatchcase

from sqlmodel import Session, select

from app.models import Policy


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    mask_pii: bool
    reason: str
    rule_id: int | None = None


def _matches(pattern: str, value: str) -> bool:
    return pattern == "*" or fnmatchcase(value, pattern)


def evaluate(policies: list[Policy], role: str, server: str, tool: str) -> PolicyDecision:
    """First matching rule in priority order wins. No match means deny (default-deny)."""
    for p in sorted(policies, key=lambda p: (p.priority, p.id or 0)):
        if _matches(p.role, role) and _matches(p.server, server) and _matches(p.tool, tool):
            reason = p.description or f"Rule #{p.id}"
            return PolicyDecision(p.effect == "allow", p.mask_pii, reason, p.id)
    return PolicyDecision(False, True, "No policy allows this call (default deny)")


def load_policies(session: Session) -> list[Policy]:
    return list(session.exec(select(Policy)).all())
