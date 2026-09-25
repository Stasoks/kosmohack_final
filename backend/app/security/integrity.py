from __future__ import annotations

import hmac
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.persistence.models import IntegrityStreamState, RawEvent, SecurityAlert
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
