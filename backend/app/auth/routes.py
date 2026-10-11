from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.deps import Principal, admin_only, create_token, get_principal
from app.auth.security import generate_api_key, hash_api_key, key_display_prefix, verify_password
from app.db import get_session
from app.models import ApiKey, Role, User

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: Role


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> LoginOut:
    user = session.exec(select(User).where(User.username == body.username)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return LoginOut(
        access_token=create_token(user.username, user.role), username=user.username, role=user.role
    )


@router.get("/auth/me")
def me(principal: Principal = Depends(get_principal)) -> dict:
    return {"name": principal.name, "role": principal.role, "kind": principal.kind}


# ---------- API keys (admin) ----------


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    role: Role
    agent_slug: str | None
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None


class KeyCreate(BaseModel):
    name: str
    role: Role = Role.agent
    agent_slug: str | None = None


class KeyCreated(KeyOut):
    key: str  # the raw key, returned exactly once


@router.get("/keys", response_model=list[KeyOut], dependencies=[Depends(admin_only)])
def list_keys(session: Session = Depends(get_session)) -> list[ApiKey]:
    return list(session.exec(select(ApiKey).order_by(ApiKey.created_at.desc())).all())


@router.post("/keys", response_model=KeyCreated, status_code=201, dependencies=[Depends(admin_only)])
def create_key(body: KeyCreate, session: Session = Depends(get_session)) -> KeyCreated:
    raw = generate_api_key()
    key = ApiKey(
        name=body.name,
        role=body.role,
        agent_slug=body.agent_slug,
        prefix=key_display_prefix(raw),
        key_hash=hash_api_key(raw),
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    return KeyCreated(**key.model_dump(), key=raw)


@router.delete("/keys/{key_id}", status_code=204, dependencies=[Depends(admin_only)])
def revoke_key(key_id: int, session: Session = Depends(get_session)) -> None:
    key = session.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    key.revoked = True
    session.add(key)
    session.commit()
