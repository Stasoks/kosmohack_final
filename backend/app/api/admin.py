from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.domain.events import SUPPORTED_EVENT_TYPES
from backend.app.persistence.database import SessionLocal, get_db
from backend.app.persistence.models import AuditEntry, EventSource, Role, User
from backend.app.projections.rebuild import mark_projection_failed, rebuild_item
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_permission
from backend.app.security.integrity import verify_integrity
from backend.app.security.passwords import hash_password
from backend.app.security.crypto import token_hash
from backend.app.security.permissions import ROLE_PERMISSIONS
from backend.app.settings import Settings, get_settings


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=96, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=512)
    roles: list[str] = Field(min_length=1)


class UserPatch(BaseModel):
    enabled: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    roles: list[str] | None = None


class SourceCreate(BaseModel):
    source_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    source_type: str = Field(min_length=1, max_length=64)
    allowed_event_types: list[str] = Field(min_length=1)
    token: str | None = Field(default=None, min_length=24, max_length=512)

    @field_validator("allowed_event_types")
    @classmethod
    def _known(cls, values: list[str]) -> list[str]:
        unknown = set(values) - SUPPORTED_EVENT_TYPES
        if unknown:
            raise ValueError(f"unsupported event types: {', '.join(sorted(unknown))}")
        return values



class SourcePatch(BaseModel):
    enabled: bool | None = None
    allowed_event_types: list[str] | None = Field(default=None, min_length=1)

    @field_validator("allowed_event_types")
    @classmethod
    def _known(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        unknown = set(values) - SUPPORTED_EVENT_TYPES
        if unknown:
            raise ValueError(f"unsupported event types: {', '.join(sorted(unknown))}")
        return values


@router.get("/users")
def list_users(
    _: Principal = Depends(require_permission("MANAGE_USERS")),
    db: Session = Depends(get_db),
):
    return [
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "enabled": user.enabled,
            "roles": [role.name for role in user.roles],
            "effective_permissions": sorted(
                set().union(*(ROLE_PERMISSIONS.get(role.name, set()) for role in user.roles))
            ),
        }
        for user in db.scalars(select(User).order_by(User.username)).all()
    ]


@router.post("/users")
def create_user(
    body: UserCreate,
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_USERS")),
    db: Session = Depends(get_db),
):
    if db.scalar(select(User).where(User.username == body.username)):
        raise TraceQError("USERNAME_EXISTS", "Username already exists", 409)
    roles = db.scalars(select(Role).where(Role.name.in_(body.roles))).all()
    if len(roles) != len(set(body.roles)):
        raise TraceQError("UNKNOWN_ROLE", "One or more roles are unknown", 422)
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        roles=list(roles),
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        action="user_create",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="user",
        target_id=str(user.id),
        request_id=request.state.request_id,
        safe_details={"username": body.username, "roles": body.roles},
    )
    db.commit()
    return {"id": user.id, "username": user.username}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_USERS")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError("User")
    if body.enabled is not None:
        if user.id == principal.user_id and not body.enabled:
            raise TraceQError("CANNOT_DISABLE_SELF", "You cannot disable your own account", 409)
        user.enabled = body.enabled
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.roles is not None:
        roles = db.scalars(select(Role).where(Role.name.in_(body.roles))).all()
        if len(roles) != len(set(body.roles)):
            raise TraceQError("UNKNOWN_ROLE", "One or more roles are unknown", 422)
        user.roles = list(roles)
    write_audit(
        db,
        action="user_update",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="user",
        target_id=str(user.id),
        request_id=request.state.request_id,
        safe_details=body.model_dump(exclude_none=True),
    )
    db.commit()
    return {"id": user.id, "enabled": user.enabled, "roles": [role.name for role in user.roles]}


@router.get("/sources")
def list_sources(
    _: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    return [
        {
            "source_id": source.source_id,
            "source_type": source.source_type,
            "enabled": source.enabled,
            "allowed_event_types": source.allowed_event_types,
            "created_at": source.created_at,
        }
        for source in db.scalars(select(EventSource).order_by(EventSource.source_id)).all()
    ]


@router.post("/sources")
def create_source(
    body: SourceCreate,
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    if db.get(EventSource, body.source_id):
        raise TraceQError("SOURCE_EXISTS", "Source ID already exists", 409)
    token = body.token or secrets.token_urlsafe(36)
    source = EventSource(
        source_id=body.source_id,
        source_type=body.source_type,
        enabled=True,
        token_hash=token_hash(token),
        allowed_event_types=sorted(set(body.allowed_event_types)),
    )
    db.add(source)
    write_audit(
        db,
        action="source_create",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="event_source",
        target_id=source.source_id,
        request_id=request.state.request_id,
        safe_details={
            "source_type": source.source_type,
            "allowed_event_types": source.allowed_event_types,
        },
    )
    db.commit()
    return {"source_id": source.source_id, "token": token, "warning": "Token is shown only once"}


@router.patch("/sources/{source_id}")
def patch_source(
    source_id: str,
    body: SourcePatch,
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    source = db.get(EventSource, source_id)
    if not source:
        raise NotFoundError("Source")
    if body.enabled is not None:
        source.enabled = body.enabled
    if body.allowed_event_types is not None:
        source.allowed_event_types = sorted(set(body.allowed_event_types))
    write_audit(
        db,
        action="source_update",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="event_source",
        target_id=source.source_id,
        request_id=request.state.request_id,
        safe_details=body.model_dump(exclude_none=True),
    )
    db.commit()
    return {"source_id": source.source_id, "enabled": source.enabled, "allowed_event_types": source.allowed_event_types}


@router.get("/audit")
def audit_log(
    limit: int = 200,
    _: Principal = Depends(require_permission("VIEW_AUDIT")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(AuditEntry).order_by(AuditEntry.timestamp.desc()).limit(min(limit, 1000))).all()
    return [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "session_id": row.session_id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "outcome": row.outcome,
            "request_id": row.request_id,
            "timestamp": row.timestamp,
            "safe_details": row.safe_details,
        }
        for row in rows
    ]


@router.post("/integrity/verify")
def integrity_check(
    request: Request,
    principal: Principal = Depends(require_permission("VERIFY_INTEGRITY")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    failures = verify_integrity(db, settings)
    write_audit(
        db,
        action="integrity_verification",
        outcome="failure" if failures else "success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="system",
        target_id="raw_event_integrity",
        request_id=request.state.request_id,
        safe_details={"failure_count": len(failures)},
    )
    db.commit()
    return {
        "status": "FAILED" if failures else "OK",
        "failures": [failure.__dict__ for failure in failures],
    }


@router.post("/rebuild/{item_id}")
def admin_rebuild(
    item_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("REPLAY_REBUILD")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        rebuild_item(db, item_id, settings)
    except Exception as exc:
        db.rollback()
        mark_projection_failed(db, item_id, f"{type(exc).__name__}: {exc}")
        raise TraceQError("PROJECTION_REBUILD_FAILED", "Projection rebuild failed", 500) from exc
    write_audit(
        db,
        action="replay_rebuild",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="item",
        target_id=item_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"item_id": item_id, "status": "up_to_date"}


def register_demo_routes(app, settings: Settings) -> None:
    if not settings.demo_mode:
        return

    @app.post("/api/v1/demo/tamper", tags=["demo"])
    def demo_tamper(
        event_id: str,
        request: Request,
        principal: Principal = Depends(require_permission("VERIFY_INTEGRITY")),
    ):
        if not settings.demo_privileged_database_url:
            raise TraceQError("DEMO_TAMPER_UNAVAILABLE", "Demo tamper connection is not configured", 503)
        engine = create_engine(settings.demo_privileged_database_url)
        with engine.begin() as connection:
            exists = connection.scalar(text("SELECT 1 FROM raw_events WHERE event_id=:event_id"), {"event_id": event_id})
            if not exists:
                raise NotFoundError("Event")
            connection.execute(text("ALTER TABLE raw_events DISABLE TRIGGER trg_raw_events_append_only"))
            try:
                connection.execute(
                    text(
                        "UPDATE raw_events SET payload_ciphertext = "
                        "set_byte(payload_ciphertext, 0, get_byte(payload_ciphertext, 0) # 1) "
                        "WHERE event_id=:event_id"
                    ),
                    {"event_id": event_id},
                )
            finally:
                connection.execute(text("ALTER TABLE raw_events ENABLE TRIGGER trg_raw_events_append_only"))
        audit_db = SessionLocal()
        try:
            write_audit(
                audit_db,
                action="demo_tamper",
                outcome="success",
                actor_user_id=principal.user_id,
                session_id=principal.session_id,
                target_type="raw_event",
                target_id=event_id,
                request_id=request.state.request_id,
            )
            audit_db.commit()
        finally:
            audit_db.close()
        return {"event_id": event_id, "status": "tampered", "next": "run integrity verification"}
