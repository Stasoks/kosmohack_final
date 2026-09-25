from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.domain.events import (
    canonical_event_dict,
    data_quality_warnings,
    validate_event,
)
from backend.app.errors import TraceQError
from backend.app.persistence.models import (
    AuditEntry,
    EventSource,
    IngestAttempt,
    IntegrityStreamState,
    ProjectionState,
    RawEvent,
)
from backend.app.security.crypto import (
    build_aad,
    canonical_json_bytes,
    compute_integrity_mac,
    encrypt_event,
    integrity_metadata,
    sha256_hex,
    token_hash,
    utcnow,
)
from backend.app.settings import Settings


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    ingestion_status: str
    projection_status: str
    content_hash: str
    warnings: tuple[dict[str, str], ...] = ()


def record_rejected_attempt(
    db: Session,
    *,
    source_id: str | None,
    claimed_event_id: str | None,
    error: TraceQError,
) -> None:
    db.add(
        IngestAttempt(
            source_id=source_id,
            claimed_event_id=claimed_event_id,
            status="rejected",
            error_code=error.code,
            safe_error_details={"message": error.message[:1000]},
        )
    )
    db.commit()


def _authenticate_source(
    db: Session, source_id: str | None, source_token: str | None
) -> EventSource:
    if not source_id or not source_token:
        raise TraceQError("SOURCE_AUTH_REQUIRED", "Source credentials are required", 401)
    source = db.scalar(
        select(EventSource).where(EventSource.source_id == source_id).with_for_update()
    )
    if (
        not source
        or not source.enabled
        or not hmac.compare_digest(source.token_hash, token_hash(source_token))
    ):
        raise TraceQError("INVALID_SOURCE_CREDENTIALS", "Source credentials are invalid", 401)
    return source


def ingest_event(
    db: Session,
    value: Any,
    *,
    header_source_id: str | None,
    source_token: str | None,
    settings: Settings,
) -> IngestionResult:
    claimed_id = value.get("event_id") if isinstance(value, dict) else None
    try:
        source = _authenticate_source(db, header_source_id, source_token)
        event = validate_event(value)
        if event.source.source_id != source.source_id or event.source.source_type != source.source_type:
            raise TraceQError(
                "SOURCE_IDENTITY_MISMATCH",
                "Authenticated source does not match the event source",
                403,
            )
        if event.event_type not in source.allowed_event_types:
            raise TraceQError(
                "EVENT_TYPE_NOT_ALLOWED",
                "Source is not allowed to submit this event type",
                403,
            )
    except TraceQError as error:
        db.rollback()
        record_rejected_attempt(
            db,
            source_id=header_source_id,
            claimed_event_id=str(claimed_id)[:128] if claimed_id else None,
            error=error,
        )
        raise

    canonical = canonical_event_dict(event)
    plaintext = canonical_json_bytes(canonical)
    content_hash = sha256_hex(plaintext)
    existing = db.get(RawEvent, event.event_id)
    if existing:
        status = "duplicate" if existing.content_hash == content_hash else "conflict"
        db.add(
            IngestAttempt(
                source_id=source.source_id,
                claimed_event_id=event.event_id,
                status=status,
                error_code=None if status == "duplicate" else "EVENT_ID_CONFLICT",
                raw_event_id=existing.event_id,
                payload_hash=content_hash,
                safe_error_details=None,
            )
        )
        if status == "conflict":
            db.add(
                AuditEntry(
                    action="event_id_conflict",
                    outcome="detected",
                    target_type="raw_event",
                    target_id=event.event_id,
                    safe_details={"source_id": source.source_id},
                )
            )
        db.commit()
        if status == "conflict":
            raise TraceQError(
                "EVENT_ID_CONFLICT", "The event ID already exists with different content", 409
            )
        return IngestionResult(event.event_id, "duplicate", "unchanged", content_hash)

    received_at = utcnow()
    aad = build_aad(
        event_id=event.event_id,
        event_type=event.event_type,
        source_id=event.source.source_id,
        schema_version=event.schema_version,
        received_at=received_at,
    )
    ciphertext, nonce = encrypt_event(plaintext, settings.aes_key(), aad)
    stream_id = f"source:{source.source_id}"
    stream = db.get(IntegrityStreamState, stream_id)
    if stream is None:
        stream = IntegrityStreamState(stream_id=stream_id, last_seq=0, last_mac=b"")
        db.add(stream)
        db.flush()
    next_seq = stream.last_seq + 1
    metadata = integrity_metadata(
        event_id=event.event_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        source_id=event.source.source_id,
        occurred_at=event.occurred_at,
        received_at=received_at,
        integrity_stream_id=stream_id,
        integrity_seq=next_seq,
    )
    mac = compute_integrity_mac(
        settings.integrity_key(),
        stream.last_mac,
        metadata,
        ciphertext,
        nonce,
        settings.aes_key_id,
    )
    raw = RawEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        source_id=event.source.source_id,
        source_type=event.source.source_type,
        source_sequence=event.source.sequence,
        item_id=event.item_id,
        operation_run_id=event.operation_run_id,
        occurred_at=event.occurred_at,
        received_at=received_at,
        payload_ciphertext=ciphertext,
        nonce=nonce,
        content_hash=content_hash,
        integrity_stream_id=stream_id,
        integrity_seq=next_seq,
        prev_integrity_mac=stream.last_mac,
        integrity_mac=mac,
        crypto_key_id=settings.aes_key_id,
        key_version="1",
        crypto_profile_id="classic-v1",
    )
    db.add(raw)
    db.flush()
    stream.last_seq = next_seq
    stream.last_mac = mac
    if event.item_id:
        projection = db.get(ProjectionState, event.item_id)
        if projection is None:
            projection = ProjectionState(item_id=event.item_id)
            db.add(projection)
        projection.latest_raw_ingest_seq = max(projection.latest_raw_ingest_seq, raw.ingest_seq)
        projection.status = "stale"
    db.add(
        IngestAttempt(
            source_id=source.source_id,
            claimed_event_id=event.event_id,
            status="accepted",
            raw_event_id=event.event_id,
            payload_hash=content_hash,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = db.get(RawEvent, event.event_id)
        if concurrent and concurrent.content_hash == content_hash:
            db.add(
                IngestAttempt(
                    source_id=source.source_id,
                    claimed_event_id=event.event_id,
                    status="duplicate",
                    raw_event_id=event.event_id,
                    payload_hash=content_hash,
                )
            )
            db.commit()
            return IngestionResult(event.event_id, "duplicate", "unchanged", content_hash)
        raise TraceQError("INGEST_CONCURRENCY_CONFLICT", "Concurrent ingest conflict", 409) from exc

    return IngestionResult(
        event.event_id,
        "accepted",
        "stale" if event.item_id else "not_applicable",
        content_hash,
        tuple(data_quality_warnings(event)),
    )
