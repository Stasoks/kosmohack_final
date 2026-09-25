from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.persistence.models import AuditEntry
from backend.app.security.crypto import canonical_json_bytes, utcnow
from backend.app.settings import get_settings


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
AUDIT_CHAIN_LOCK_ID = 0x545241434551


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    text_value = (
        str(value)
        if not isinstance(value, (str, int, float, bool, type(None)))
        else value
    )
    if isinstance(text_value, str) and len(text_value) > 1000:
        return text_value[:1000] + "…"
    return text_value


def audit_mac_payload(
    *,
    sequence: int,
    actor_user_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    outcome: str,
    request_id: str | None,
    timestamp,
    safe_details: dict[str, Any] | None,
) -> bytes:
    return canonical_json_bytes(
        {
            "sequence": sequence,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "session_id": str(session_id) if session_id else None,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "request_id": request_id,
            "timestamp": timestamp.isoformat(),
            "safe_details": safe_details,
        }
    )


def compute_audit_mac(secret: bytes, prev_mac: bytes, payload: bytes) -> bytes:
    return hmac.new(secret, prev_mac + b"\n" + payload, hashlib.sha256).digest()


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
    # One global chain is deliberately serialized. Critical actions are low volume,
    # and this keeps the proof simple and deterministic.
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": AUDIT_CHAIN_LOCK_ID})
    previous = db.scalar(
        select(AuditEntry)
        .where(AuditEntry.integrity_sequence.is_not(None))
        .order_by(AuditEntry.integrity_sequence.desc())
        .limit(1)
    )
    sequence = (previous.integrity_sequence if previous else 0) + 1
    prev_mac = previous.integrity_mac if previous and previous.integrity_mac else b""
    timestamp = utcnow()
    sanitized = _sanitize(safe_details) if safe_details else None
    payload = audit_mac_payload(
        sequence=sequence,
        actor_user_id=actor_user_id,
        session_id=session_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id,
        timestamp=timestamp,
        safe_details=sanitized,
    )
    mac = compute_audit_mac(get_settings().integrity_key(), prev_mac, payload)
    entry = AuditEntry(
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        session_id=session_id,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        timestamp=timestamp,
        safe_details=sanitized,
        integrity_sequence=sequence,
        prev_integrity_mac=prev_mac,
        integrity_mac=mac,
    )
    db.add(entry)
    return entry
