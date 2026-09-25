from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
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
    ControlDeviceInvalidation,
    EventSource,
    IngestAttempt,
    IntegrityStreamState,
    ProjectionState,
    RawEvent,
    Observation,
    SecurityAlert,
    TransportNonce,
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
    affected_items: tuple[str, ...] = ()


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
    alert_map = {
        "REPLAY_ATTEMPT": "REPLAY_ATTEMPT",
        "SOURCE_AUTH_FAILED": "SOURCE_AUTH_FAILED",
        "INVALID_SOURCE_CREDENTIALS": "SOURCE_AUTH_FAILED",
        "SOURCE_SCOPE_VIOLATION": "SOURCE_SCOPE_VIOLATION",
        "EVENT_ID_CONFLICT": "EVENT_ID_CONFLICT",
        "KEY_UNAVAILABLE": "KEY_UNAVAILABLE",
    }
    if error.code in alert_map:
        _alert(db, alert_map[error.code], source_id, claimed_event_id)
    db.commit()


def _alert(db: Session, alert_type: str, source_id: str | None, target_id: str | None = None, **details) -> None:
    db.add(SecurityAlert(alert_type=alert_type, source_id=source_id, target_type="event", target_id=target_id, details=details or None))


def _parse_transport_time(value: str) -> datetime:
    try:
        parsed = datetime.fromtimestamp(float(value), timezone.utc) if value.replace(".", "", 1).isdigit() else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise TraceQError("SOURCE_AUTH_FAILED", "Invalid source timestamp", 401) from exc


def _hmac_secret(settings: Settings, source_id: str) -> str | None:
    if settings.source_hmac_secrets_json:
        values = json.loads(settings.source_hmac_secrets_json.get_secret_value())
        if isinstance(values, dict) and source_id in values:
            return str(values[source_id])
    return settings.source_demo_token.get_secret_value() if settings.demo_mode and settings.source_demo_token else None


def _authenticate_source(
    db: Session, source_id: str | None, source_token: str | None,
    source_timestamp: str | None, source_nonce: str | None, source_signature: str | None,
    body: Any, settings: Settings,
) -> EventSource:
    if not source_id:
        raise TraceQError("SOURCE_AUTH_REQUIRED", "Source credentials are required", 401)
    source = db.scalar(
        select(EventSource).where(EventSource.source_id == source_id).with_for_update()
    )
    if (
        not source or not source.enabled or source.status != "ACTIVE"
        or source.revoked_at is not None
        or (source.valid_from is not None and source.valid_from > utcnow())
        or (source.valid_to is not None and source.valid_to <= utcnow())
    ):
        raise TraceQError("INVALID_SOURCE_CREDENTIALS", "Source credentials are invalid", 401)
    if source.auth_method == "HMAC_V1":
        if not all((source_timestamp, source_nonce, source_signature)):
            raise TraceQError("SOURCE_AUTH_REQUIRED", "HMAC source headers are required", 401)
        transport_time = _parse_transport_time(source_timestamp)
        if abs((utcnow() - transport_time).total_seconds()) > settings.source_timestamp_tolerance_seconds:
            raise TraceQError("SOURCE_AUTH_FAILED", "Source timestamp is outside the accepted window", 401)
        if db.get(TransportNonce, {"source_id": source_id, "nonce": source_nonce}):
            _alert(db, "REPLAY_ATTEMPT", source_id)
            db.commit()
            raise TraceQError("REPLAY_ATTEMPT", "Transport nonce has already been used", 409)
        secret = _hmac_secret(settings, source_id)
        if not secret:
            raise TraceQError("KEY_UNAVAILABLE", "Source authentication key is unavailable", 503)
        signed = source_timestamp.encode() + b"\n" + source_nonce.encode() + b"\n" + canonical_json_bytes(body)
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, source_signature.lower()):
            raise TraceQError("SOURCE_AUTH_FAILED", "Source signature is invalid", 401)
        db.add(TransportNonce(source_id=source_id, nonce=source_nonce, timestamp=transport_time))
        db.commit()
    elif not source_token or not source.token_hash or not hmac.compare_digest(source.token_hash, token_hash(source_token)):
        raise TraceQError("INVALID_SOURCE_CREDENTIALS", "Source credentials are invalid", 401)
    return source


def ingest_event(
    db: Session,
    value: Any,
    *,
    header_source_id: str | None,
    source_token: str | None,
    source_timestamp: str | None = None,
    source_nonce: str | None = None,
    source_signature: str | None = None,
    settings: Settings,
) -> IngestionResult:
    claimed_id = value.get("event_id") if isinstance(value, dict) else None
    try:
        source = _authenticate_source(db, header_source_id, source_token, source_timestamp, source_nonce, source_signature, value, settings)
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
        payload = event.payload.model_dump(mode="json")
        if source.allowed_line_ids and payload.get("line_id") not in (None, *source.allowed_line_ids):
            raise TraceQError("SOURCE_SCOPE_VIOLATION", "Source is outside its allowed line scope", 403)
        if source.allowed_station_ids and payload.get("station_id") not in (None, *source.allowed_station_ids):
            raise TraceQError("SOURCE_SCOPE_VIOLATION", "Source is outside its allowed station scope", 403)
        if event.event_type == "control_device.invalidated" and source.source_type != "calibration_system":
            raise TraceQError("SOURCE_SCOPE_VIOLATION", "Only a calibration source may invalidate a control device", 403)
        if event.source.sequence is not None and source.last_source_sequence is not None and event.source.sequence <= source.last_source_sequence:
            _alert(db, "SOURCE_SEQUENCE_ANOMALY", source.source_id, event.event_id, previous=source.last_source_sequence, received=event.source.sequence)
        if event.source.sequence is not None:
            source.last_source_sequence = max(source.last_source_sequence or -1, event.source.sequence)
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
            _alert(db, "EVENT_ID_CONFLICT", source.source_id, event.event_id)
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
        occurred_at=event.occurred_at,
        item_id=event.item_id,
        crypto_key_id=settings.aes_key_id,
        profile="CLASSIC_V2",
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
        crypto_profile_id="CLASSIC_V2",
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
    affected_items: set[str] = set()
    if event.event_type == "control_device.invalidated":
        payload = event.payload.model_dump()
        db.add(ControlDeviceInvalidation(
            source_event_id=event.event_id,
            device_id=payload["device_id"], affected_from=payload["affected_from"],
            affected_to=payload["affected_to"], reason=payload["reason"],
            invalidation_type=payload.get("invalidation_type"),
            supporting_evidence_refs=payload.get("supporting_evidence_refs", []),
        ))
        affected_items.update(db.scalars(select(Observation.item_id).where(
            Observation.control_device_id == payload["device_id"],
            Observation.occurred_at >= payload["affected_from"],
            Observation.occurred_at <= payload["affected_to"],
        )).all())
        for affected_item in affected_items:
            state = db.get(ProjectionState, affected_item)
            if state:
                state.status = "stale"
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
        tuple(sorted(affected_items)),
    )
