from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import ForbiddenError, TraceQError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import AuthSession, Permission, RolePermission, User, UserRole
from backend.app.security.crypto import utcnow
from backend.app.settings import Settings, get_settings


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    username: str
    session_id: uuid.UUID
    permissions: frozenset[str]
    roles: tuple[str, ...]


def create_access_token(user: User, session_id: uuid.UUID, settings: Settings) -> tuple[str, int]:
    now = utcnow()
    expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    token = jwt.encode(
        {
            "sub": user.username,
            "user_id": str(user.id),
            "session_id": str(session_id),
            "iat": now,
            "exp": expires,
        },
        settings.jwt_signing_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int((expires - now).total_seconds())


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _permissions_for_user(db: Session, user_id: uuid.UUID) -> frozenset[str]:
    statement = (
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return frozenset(db.scalars(statement).all())


def current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise TraceQError("AUTHENTICATION_REQUIRED", "Authentication required", 401)
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_signing_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id = uuid.UUID(claims["user_id"])
        session_id = uuid.UUID(claims["session_id"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise TraceQError("INVALID_ACCESS_TOKEN", "Access token is invalid or expired", 401) from exc
    user = db.get(User, user_id)
    session = db.get(AuthSession, session_id)
    now = utcnow()
    if (not user or not user.enabled or not session or session.user_id != user_id
            or session.revoked_at is not None or session.expires_at <= now):
        raise TraceQError("INVALID_ACCESS_TOKEN", "Access token is invalid or expired", 401)
    principal = Principal(
        user_id=user.id,
        username=user.username,
        session_id=session_id,
        permissions=_permissions_for_user(db, user.id),
        roles=tuple(sorted(role.name for role in user.roles)),
    )
    request.state.principal = principal
    return principal


def require_permission(permission: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if permission not in principal.permissions:
            raise ForbiddenError(f"Permission {permission} is required")
        return principal

    return dependency


def require_critical_permission(permission: str, *, freshness_minutes: int = 30):
    def dependency(
        principal: Principal = Depends(current_principal),
        db: Session = Depends(get_db),
    ) -> Principal:
        if permission not in principal.permissions:
            raise ForbiddenError(f"Permission {permission} is required")
        session = db.get(AuthSession, principal.session_id)
        if not session or session.revoked_at is not None or session.expires_at <= utcnow():
            raise TraceQError("SESSION_REVOKED", "The authenticated session is no longer active", 401)
        if session.last_authenticated_at < utcnow() - timedelta(minutes=freshness_minutes):
            raise TraceQError("FRESH_AUTH_REQUIRED", "Fresh authentication is required", 403)
        return principal
    return dependency


def require_any_permission(*permissions: str):
    allowed = frozenset(permissions)

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.permissions.intersection(allowed):
            raise ForbiddenError(f"One of these permissions is required: {', '.join(sorted(allowed))}")
        return principal

    return dependency
