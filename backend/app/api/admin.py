from __future__ import annotations

import json
import secrets
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.domain.events import SUPPORTED_EVENT_TYPES
from backend.app.persistence.database import SessionLocal, get_db
from backend.app.persistence.models import (
    AuditEntry,
    CryptoProfile,
    EventSource,
    RawEvent,
    Role,
    SecurityAlert,
    User,
)
from backend.app.security.key_provider import CRYPTO_PROFILES
from backend.app.projections.rebuild import mark_projection_failed, rebuild_item
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_critical_permission, require_permission
from backend.app.security.integrity import verify_audit_integrity, verify_integrity
from backend.app.security.checkpoints import create_classic_checkpoint
from backend.app.security.passwords import hash_password
from backend.app.security.crypto import token_hash, utcnow
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
    auth_method: str = Field(default="shared_secret_legacy", pattern="^(shared_secret_legacy|HMAC_V1)$")
    key_id: str | None = Field(default=None, min_length=1, max_length=128)
    allowed_line_ids: list[str] = Field(default_factory=list)
    allowed_station_ids: list[str] = Field(default_factory=list)

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
    status: str | None = Field(default=None, pattern="^(ACTIVE|SUSPENDED|REVOKED|EXPIRED)$")
    allowed_line_ids: list[str] | None = None
    allowed_station_ids: list[str] | None = None

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
            "status": source.status,
            "auth_method": source.auth_method,
            "allowed_event_types": source.allowed_event_types,
            "allowed_line_ids": source.allowed_line_ids,
            "allowed_station_ids": source.allowed_station_ids,
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
    settings: Settings = Depends(get_settings),
):
    if db.get(EventSource, body.source_id):
        raise TraceQError("SOURCE_EXISTS", "Source ID already exists", 409)
    token: str | None = None
    key_id: str | None = None
    token_hash_value: str | None = None
    if body.auth_method == "HMAC_V1":
        key_id = body.key_id or body.source_id
        configured = {}
        if settings.source_hmac_secrets_json:
            configured = json.loads(settings.source_hmac_secrets_json.get_secret_value())
        if not isinstance(configured, dict) or key_id not in configured:
            raise TraceQError(
                "HMAC_KEY_NOT_PROVISIONED",
                "HMAC key_id must already exist in SOURCE_HMAC_SECRETS_JSON",
                422,
            )
    else:
        token = body.token or secrets.token_urlsafe(36)
        token_hash_value = token_hash(token)

    source = EventSource(
        source_id=body.source_id,
        source_type=body.source_type,
        enabled=True,
        token_hash=token_hash_value,
        status="ACTIVE",
        auth_method=body.auth_method,
        key_id=key_id,
        secret_env_name="SOURCE_HMAC_SECRETS_JSON" if key_id else None,
        allowed_event_types=sorted(set(body.allowed_event_types)),
        allowed_line_ids=sorted(set(body.allowed_line_ids)),
        allowed_station_ids=sorted(set(body.allowed_station_ids)),
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
    response = {"source_id": source.source_id, "auth_method": source.auth_method}
    if token is not None:
        response.update({"token": token, "warning": "Token is shown only once"})
    else:
        response.update({"key_id": source.key_id, "warning": "HMAC secret remains in the external secret store"})
    return response


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
    if body.status is not None:
        source.status = body.status
    if body.allowed_line_ids is not None:
        source.allowed_line_ids = sorted(set(body.allowed_line_ids))
    if body.allowed_station_ids is not None:
        source.allowed_station_ids = sorted(set(body.allowed_station_ids))
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


@router.get("/security-alerts")
def security_alerts(
    limit: int = 200,
    _: Principal = Depends(require_permission("VERIFY_INTEGRITY")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(SecurityAlert).order_by(SecurityAlert.created_at.desc()).limit(min(limit, 1000))).all()
    return [{"id": row.id, "alert_type": row.alert_type, "severity": row.severity,
             "source_id": row.source_id, "target_type": row.target_type, "target_id": row.target_id,
             "details": row.details, "created_at": row.created_at, "resolved_at": row.resolved_at} for row in rows]


@router.get("/crypto-profile")
def crypto_profile(_: Principal = Depends(require_permission("VERIFY_INTEGRITY")), db: Session = Depends(get_db)):
    active = db.scalar(select(CryptoProfile).where(CryptoProfile.status == "ACTIVE"))
    profile_id = active.profile_id if active else "CLASSIC_V1"
    return {"profile_id": profile_id, "algorithms": CRYPTO_PROFILES[profile_id],
            "pq_available": False, "keys_stored_in_database": False}


@router.post("/integrity/checkpoints/{stream_id}")
def checkpoint(stream_id: str, request: Request,
               principal: Principal = Depends(require_critical_permission("ROTATE_KEYS")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    row = create_classic_checkpoint(db, stream_id, settings)
    write_audit(db, action="integrity_checkpoint", outcome="success", actor_user_id=principal.user_id,
                session_id=principal.session_id, target_type="integrity_stream", target_id=stream_id,
                request_id=request.state.request_id, safe_details={"profile": row.crypto_profile_id, "sequence": row.sequence})
    db.commit()
    return {"checkpoint_id": row.id, "profile": row.crypto_profile_id, "sequence": row.sequence}


@router.post("/integrity/verify")
def integrity_check(
    request: Request,
    principal: Principal = Depends(require_permission("VERIFY_INTEGRITY")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    checked_at = utcnow()
    raw_events_checked = db.scalar(select(func.count(RawEvent.event_id))) or 0
    audit_entries_checked = db.scalar(select(func.count(AuditEntry.id))) or 0
    raw_failures = verify_integrity(db, settings)
    audit_failures = verify_audit_integrity(db, settings)
    failed = bool(raw_failures or audit_failures)
    write_audit(
        db,
        action="integrity_verification",
        outcome="failure" if failed else "success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="system",
        target_id="raw_and_audit_integrity",
        request_id=request.state.request_id,
        safe_details={
            "raw_failure_count": len(raw_failures),
            "audit_failure_count": len(audit_failures),
        },
    )
    db.commit()
    return {
        "status": "FAILED" if failed else "OK",
        "checked_at": checked_at,
        "raw_events_checked": raw_events_checked,
        "audit_entries_checked": audit_entries_checked,
        "crypto_profile": (
            db.scalar(
                select(CryptoProfile.profile_id).where(CryptoProfile.status == "ACTIVE")
            )
            or "CLASSIC_V1"
        ),
        "raw_failures": [failure.__dict__ for failure in raw_failures],
        "audit_failures": [failure.__dict__ for failure in audit_failures],
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
