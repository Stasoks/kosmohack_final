from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import TraceQError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import AuthSession, RefreshToken, User
from backend.app.security.audit import write_audit
from backend.app.security.auth import (
    Principal,
    create_access_token,
    create_refresh_token,
    current_principal,
)
from backend.app.security.crypto import token_hash, utcnow
from backend.app.security.passwords import verify_password
from backend.app.settings import Settings, get_settings


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=96)
    password: str = Field(min_length=1, max_length=512)


class TokenRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


def _token_response(db: Session, user: User, settings: Settings, session_id: uuid.UUID | None = None):
    session_id = session_id or uuid.uuid4()
    session = db.get(AuthSession, session_id)
    session_expiry = utcnow() + timedelta(hours=settings.refresh_token_ttl_hours)
    if session is None:
        session = AuthSession(
            id=session_id, user_id=user.id, last_authenticated_at=utcnow(), expires_at=session_expiry
        )
        db.add(session)
    else:
        session.last_authenticated_at = utcnow()
        session.expires_at = session_expiry
    access, expires_in = create_access_token(user, session_id, settings)
    raw_refresh = create_refresh_token()
    record = RefreshToken(
        user_id=user.id,
        session_id=session_id,
        token_hash=token_hash(raw_refresh),
        expires_at=utcnow() + timedelta(hours=settings.refresh_token_ttl_hours),
    )
    db.add(record)
    db.flush()
    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
    }, record


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = db.scalar(select(User).where(User.username == body.username))
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        write_audit(
            db,
            action="login_failure",
            outcome="locked",
            target_type="user",
            target_id=str(user.id),
            request_id=request.state.request_id,
        )
        db.commit()
        raise TraceQError("ACCOUNT_TEMPORARILY_LOCKED", "Account is temporarily locked", 423)
    if not user or not user.enabled or not verify_password(user.password_hash, body.password):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
        write_audit(
            db,
            action="login_failure",
            outcome="denied",
            target_type="user",
            target_id=str(user.id) if user else body.username,
            request_id=request.state.request_id,
        )
        db.commit()
        raise TraceQError("INVALID_CREDENTIALS", "Invalid username or password", 401)
    user.failed_login_attempts = 0
    user.locked_until = None
    response, refresh = _token_response(db, user, settings)
    write_audit(
        db,
        action="login_success",
        outcome="success",
        actor_user_id=user.id,
        session_id=refresh.session_id,
        target_type="user",
        target_id=str(user.id),
        request_id=request.state.request_id,
    )
    db.commit()
    return response


@router.post("/refresh")
def refresh(
    body: TokenRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    hashed = token_hash(body.refresh_token)
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashed).with_for_update())
    now = utcnow()
    if not record or record.revoked_at or record.expires_at <= now:
        raise TraceQError("INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired", 401)
    user = db.get(User, record.user_id)
    if not user or not user.enabled:
        raise TraceQError("INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired", 401)
    response, replacement = _token_response(db, user, settings, record.session_id)
    record.revoked_at = now
    record.replaced_by_hash = replacement.token_hash
    write_audit(
        db,
        action="refresh_rotation",
        outcome="success",
        actor_user_id=user.id,
        session_id=record.session_id,
        target_type="session",
        target_id=str(record.session_id),
        request_id=request.state.request_id,
    )
    db.commit()
    return response


@router.post("/logout")
def logout(body: TokenRequest, request: Request, db: Session = Depends(get_db)):
    hashed = token_hash(body.refresh_token)
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashed).with_for_update())
    if record and not record.revoked_at:
        now = utcnow()
        record.revoked_at = now
        session = db.get(AuthSession, record.session_id)
        if session and session.revoked_at is None:
            session.revoked_at = now
        for sibling in db.scalars(select(RefreshToken).where(RefreshToken.session_id == record.session_id)).all():
            if sibling.revoked_at is None:
                sibling.revoked_at = now
        write_audit(
            db,
            action="logout",
            outcome="success",
            actor_user_id=record.user_id,
            session_id=record.session_id,
            target_type="session",
            target_id=str(record.session_id),
            request_id=request.state.request_id,
        )
        db.commit()
    return {"status": "logged_out"}


@router.get("/me")
def me(principal: Principal = Depends(current_principal)):
    return {
        "user_id": str(principal.user_id),
        "username": principal.username,
        "roles": principal.roles,
        "permissions": sorted(principal.permissions),
        "session_id": str(principal.session_id),
    }
