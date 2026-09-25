from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.integrations.adapters import EmulatorAdapter
from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    ExternalIdentity,
    IntegrationHealth,
    OutboxMessage,
)
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_permission
from backend.app.security.crypto import utcnow
from backend.app.settings import Settings, get_settings


router = APIRouter(prefix="/api/v1", tags=["integrations"])


@router.get("/integrations")
def list_integrations(
    _: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    health = db.scalars(select(IntegrationHealth).order_by(IntegrationHealth.integration_id)).all()
    return {
        "adapters": [
            {"id": "erp-emulator", "status": "implemented"},
            {"id": "1c", "status": "fixture_transport"},
            {"id": "galaktika", "status": "fixture_transport"},
            {"id": "mes", "status": "fixture_transport"},
            {"id": "kompas", "status": "json_structure_provider"},
        ],
        "health": [
            {
                "integration_id": item.integration_id,
                "status": item.status,
                "last_success_at": item.last_success_at,
                "last_error_at": item.last_error_at,
                "safe_error": item.safe_error,
            }
            for item in health
        ],
        "outbox": [
            {
                "message_id": message.message_id,
                "destination": message.destination,
                "state": message.state,
                "attempts": message.attempts,
                "next_attempt_at": message.next_attempt_at,
                "last_error": message.last_error,
                "created_at": message.created_at,
                "delivered_at": message.delivered_at,
            }
            for message in db.scalars(
                select(OutboxMessage).order_by(OutboxMessage.created_at.desc()).limit(100)
            ).all()
        ],
    }


@router.post("/integrations/erp/sync")
def sync_erp(
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    adapter = EmulatorAdapter(settings.erp_emulator_url, settings.erp_timeout_seconds)
    health = db.get(IntegrationHealth, "erp-emulator")
    if not health:
        health = IntegrationHealth(integration_id="erp-emulator", status="UNKNOWN")
        db.add(health)
    try:
        jobs = adapter.fetch_jobs()
        references = adapter.fetch_references()
        mapped = 0
        for job in jobs:
            external_id = str(job["job_id"])
            existing = db.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.external_system == "erp-emulator",
                    ExternalIdentity.external_entity_type == "job",
                    ExternalIdentity.external_id == external_id,
                )
            )
            if not existing:
                db.add(
                    ExternalIdentity(
                        internal_entity_type="production_job",
                        internal_id=f"JOB-{external_id}",
                        external_system="erp-emulator",
                        external_entity_type="job",
                        external_id=external_id,
                        external_revision=str(job.get("revision")) if job.get("revision") else None,
                    )
                )
                mapped += 1
        health.status = "HEALTHY"
        health.last_success_at = utcnow()
        health.safe_error = None
        write_audit(
            db,
            action="integration_sync",
            outcome="success",
            actor_user_id=principal.user_id,
            session_id=principal.session_id,
            target_type="integration",
            target_id="erp-emulator",
            request_id=request.state.request_id,
            safe_details={"jobs": len(jobs), "new_mappings": mapped},
        )
        db.commit()
        return {"jobs": jobs, "references": references, "new_mappings": mapped}
    except Exception as exc:
        health.status = "UNHEALTHY"
        health.last_error_at = utcnow()
        health.safe_error = f"{type(exc).__name__}: integration unavailable"[:1000]
        db.commit()
        raise TraceQError("ERP_SYNC_FAILED", "ERP emulator is unavailable", 502) from exc


@router.post("/outbox/{message_id}/retry")
def retry_outbox(
    message_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    message = db.scalar(select(OutboxMessage).where(OutboxMessage.message_id == message_id))
    if not message:
        raise NotFoundError("Outbox message")
    if message.state == "DELIVERED":
        raise TraceQError("OUTBOX_ALREADY_DELIVERED", "Delivered messages cannot be retried", 409)
    message.state = "PENDING"
    message.next_attempt_at = utcnow()
    message.last_error = None
    write_audit(
        db,
        action="manual_retry",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="outbox_message",
        target_id=message_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"message_id": message_id, "state": message.state}
