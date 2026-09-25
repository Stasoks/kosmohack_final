from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.persistence.models import AuditEntry


SENSITIVE_KEYS = {
    "authorization",
    "password",
    "refresh_token",
    "source_token",
    "jwt",
    "aes_key",
    "hmac_key",
    "raw_payload",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    text = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    if isinstance(text, str) and len(text) > 1000:
        return text[:1000] + "…"
    return text


def write_audit(
    db: Session,
    *,
    action: str,
    outcome: str,
    actor_user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    safe_details: dict[str, Any] | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        session_id=session_id,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        safe_details=_sanitize(safe_details) if safe_details else None,
    )
    db.add(entry)
    return entry
