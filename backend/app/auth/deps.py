"""Request authentication. Accepts either a dashboard JWT or an API key:
Authorization: Bearer <jwt | ah_...>   or   X-API-Key: ah_..."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.auth.security import KEY_PREFIX, hash_api_key
from app.config import get_settings
from app.db import get_session
from app.models import ApiKey, Role


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role
    kind: str  # user | key
    key_id: int | None = None


def create_token(username: str, role: Role) -> str:
    settings = get_settings()
    payload = {
        "sub": username,
        "role": role.value,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def principal_from_key(raw: str, session: Session) -> Principal | None:
    key = session.exec(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw))).first()
    if not key or key.revoked:
        return None
    key.last_used_at = datetime.now(UTC)
    session.add(key)
    session.commit()
    return Principal(name=key.agent_slug or key.name, role=key.role, kind="key", key_id=key.id)


def principal_from_token(token: str) -> Principal | None:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return Principal(name=data["sub"], role=Role(data["role"]), kind="user")
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def authenticate(credential: str, session: Session) -> Principal | None:
    if credential.startswith(KEY_PREFIX):
        return principal_from_key(credential, session)
    return principal_from_token(credential)


def get_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Principal:
    credential = x_api_key
    if not credential and authorization and authorization.lower().startswith("bearer "):
        credential = authorization[7:].strip()
    principal = authenticate(credential, session) if credential else None
    if not principal:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_roles(*roles: Role):
    def check(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return principal

    return check


# Common guards
can_edit = require_roles(Role.admin, Role.developer)
admin_only = require_roles(Role.admin)
