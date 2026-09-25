from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.ingestion.service import ingest_event, record_rejected_attempt
from backend.app.persistence.database import SessionLocal, get_db
from backend.app.persistence.models import RawEvent
from backend.app.projections.rebuild import mark_projection_failed, rebuild_item
from backend.app.security.auth import Principal, require_permission
from backend.app.security.crypto import build_aad, decrypt_event
from backend.app.settings import Settings, get_settings


router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("")
async def receive_event(
    request: Request,
    x_source_id: str | None = Header(default=None, alias="X-Source-Id"),
    x_source_token: str | None = Header(default=None, alias="X-Source-Token"),
    x_source_timestamp: str | None = Header(default=None, alias="X-Source-Timestamp"),
    x_source_nonce: str | None = Header(default=None, alias="X-Source-Nonce"),
    x_source_signature: str | None = Header(default=None, alias="X-Source-Signature"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        error = TraceQError("INVALID_JSON", "Request body must contain valid JSON", 400)
        record_rejected_attempt(
            db, source_id=x_source_id, claimed_event_id=None, error=error
        )
        raise error
    result = ingest_event(
        db,
        value,
        header_source_id=x_source_id,
        source_token=x_source_token,
        source_timestamp=x_source_timestamp,
        source_nonce=x_source_nonce,
        source_signature=x_source_signature,
        settings=settings,
    )
    projection_status = result.projection_status
    item_id = value.get("item_id") or (value.get("payload") or {}).get("item_id")
    if result.ingestion_status == "accepted" and item_id:
        projection_db = SessionLocal()
        try:
            rebuild_item(projection_db, item_id, settings)
            projection_status = "updated"
        except Exception as exc:
            projection_db.rollback()
            mark_projection_failed(
                projection_db, item_id, f"{type(exc).__name__}: {exc}"
            )
            projection_status = "failed"
        finally:
            projection_db.close()
    for affected_item in result.affected_items:
        projection_db = SessionLocal()
        try:
            rebuild_item(projection_db, affected_item, settings)
        except Exception as exc:
            projection_db.rollback()
            mark_projection_failed(projection_db, affected_item, f"{type(exc).__name__}: {exc}")
        finally:
            projection_db.close()
    return {
        "event_id": result.event_id,
        "ingestion_status": result.ingestion_status,
        "projection_status": projection_status,
        "content_hash": result.content_hash,
        "warnings": result.warnings,
        "affected_items": result.affected_items,
    }


@router.get("/{event_id}")
def get_event(
    event_id: str,
    _: Principal = Depends(require_permission("VIEW_RAW_EVENT")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    raw = db.get(RawEvent, event_id)
    if not raw:
        raise NotFoundError("Event")
    aad = build_aad(
        event_id=raw.event_id,
        event_type=raw.event_type,
        source_id=raw.source_id,
        schema_version=raw.schema_version,
        received_at=raw.received_at,
        occurred_at=raw.occurred_at,
        item_id=raw.item_id,
        crypto_key_id=raw.crypto_key_id,
        profile=raw.crypto_profile_id,
    )
    plaintext = decrypt_event(raw.payload_ciphertext, raw.nonce, settings.aes_key(), aad)
    return {
        "event": json.loads(plaintext),
        "received_at": raw.received_at,
        "ingest_seq": raw.ingest_seq,
        "content_hash": raw.content_hash,
        "integrity_stream_id": raw.integrity_stream_id,
        "integrity_seq": raw.integrity_seq,
    }
