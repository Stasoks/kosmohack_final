from __future__ import annotations

import hmac
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.persistence.models import AuditEntry, IntegrityStreamState, RawEvent, SecurityAlert
from backend.app.security.audit import audit_mac_payload, compute_audit_mac
from backend.app.security.crypto import compute_integrity_mac, integrity_metadata
from backend.app.settings import Settings


@dataclass(frozen=True)
class IntegrityFailure:
    stream_id: str
    event_id: str
    sequence: int
    reason: str


def verify_integrity(db: Session, settings: Settings) -> list[IntegrityFailure]:
    failures: list[IntegrityFailure] = []
    stream_ids = db.scalars(select(IntegrityStreamState.stream_id).order_by(IntegrityStreamState.stream_id)).all()
    for stream_id in stream_ids:
        previous = b""
        events = db.scalars(
            select(RawEvent)
            .where(RawEvent.integrity_stream_id == stream_id)
            .order_by(RawEvent.integrity_seq)
        ).all()
        expected_seq = 1
        for event in events:
            if event.integrity_seq != expected_seq:
                failures.append(
                    IntegrityFailure(stream_id, event.event_id, event.integrity_seq, "SEQUENCE_GAP")
                )
            if not hmac.compare_digest(event.prev_integrity_mac, previous):
                failures.append(
                    IntegrityFailure(stream_id, event.event_id, event.integrity_seq, "PREVIOUS_MAC_MISMATCH")
                )
            metadata = integrity_metadata(
                event_id=event.event_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                source_id=event.source_id,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                integrity_stream_id=event.integrity_stream_id,
                integrity_seq=event.integrity_seq,
            )
            calculated = compute_integrity_mac(
                settings.integrity_key(),
                event.prev_integrity_mac,
                metadata,
                event.payload_ciphertext,
                event.nonce,
                event.crypto_key_id,
            )
            if not hmac.compare_digest(calculated, event.integrity_mac):
                failures.append(
                    IntegrityFailure(stream_id, event.event_id, event.integrity_seq, "MAC_MISMATCH")
                )
            previous = event.integrity_mac
            expected_seq += 1
        state = db.get(IntegrityStreamState, stream_id)
        if state:
            state.status = "INTEGRITY_FAILED" if any(f.stream_id == stream_id for f in failures) else "OK"
    for failure in failures:
        exists = db.scalar(select(SecurityAlert.id).where(
            SecurityAlert.alert_type == "RAW_LOG_INTEGRITY_FAILED",
            SecurityAlert.target_id == failure.event_id,
        ).limit(1))
        if not exists:
            db.add(SecurityAlert(alert_type="RAW_LOG_INTEGRITY_FAILED", severity="CRITICAL",
                                 target_type="raw_event", target_id=failure.event_id,
                                 details={"stream_id": failure.stream_id, "sequence": failure.sequence,
                                          "reason": failure.reason}))
    db.commit()
    return failures


@dataclass(frozen=True)
class AuditIntegrityFailure:
    sequence: int
    entry_id: int
    reason: str


def verify_audit_integrity(db: Session, settings: Settings) -> list[AuditIntegrityFailure]:
    failures: list[AuditIntegrityFailure] = []
    entries = db.scalars(
        select(AuditEntry)
        .where(AuditEntry.integrity_sequence.is_not(None))
        .order_by(AuditEntry.integrity_sequence)
    ).all()
    previous = b""
    expected_sequence = 1
    for entry in entries:
        sequence = int(entry.integrity_sequence or 0)
        if sequence != expected_sequence:
            failures.append(AuditIntegrityFailure(sequence, entry.id, "SEQUENCE_GAP"))
        if entry.prev_integrity_mac is None or not hmac.compare_digest(entry.prev_integrity_mac, previous):
            failures.append(AuditIntegrityFailure(sequence, entry.id, "PREVIOUS_MAC_MISMATCH"))
        if entry.integrity_mac is None:
            failures.append(AuditIntegrityFailure(sequence, entry.id, "MISSING_MAC"))
        else:
            payload = audit_mac_payload(
                sequence=sequence,
                actor_user_id=entry.actor_user_id,
                session_id=entry.session_id,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                outcome=entry.outcome,
                request_id=entry.request_id,
                timestamp=entry.timestamp,
                safe_details=entry.safe_details,
            )
            calculated = compute_audit_mac(settings.integrity_key(), entry.prev_integrity_mac or b"", payload)
            if not hmac.compare_digest(calculated, entry.integrity_mac):
                failures.append(AuditIntegrityFailure(sequence, entry.id, "MAC_MISMATCH"))
            previous = entry.integrity_mac
        expected_sequence += 1

    for failure in failures:
        target_id = str(failure.entry_id)
        exists = db.scalar(
            select(SecurityAlert.id)
            .where(
                SecurityAlert.alert_type == "AUDIT_LOG_INTEGRITY_FAILED",
                SecurityAlert.target_id == target_id,
            )
            .limit(1)
        )
        if not exists:
            db.add(
                SecurityAlert(
                    alert_type="AUDIT_LOG_INTEGRITY_FAILED",
                    severity="CRITICAL",
                    target_type="audit_entry",
                    target_id=target_id,
                    details={"sequence": failure.sequence, "reason": failure.reason},
                )
            )
    db.commit()
    return failures
