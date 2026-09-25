from __future__ import annotations

import logging
import socket
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from backend.app.integrations.adapters import EmulatorAdapter
from backend.app.persistence.database import SessionLocal
from backend.app.persistence.models import (
    IntegrationHealth,
    IntegrationMessage,
    OutboxMessage,
    SecurityAlert,
    WorkerHeartbeat,
)
from backend.app.security.crypto import utcnow
from backend.app.settings import get_settings


logger = logging.getLogger("traceq.worker")
settings = get_settings()
worker_id = f"outbox:{socket.gethostname()}"


def _heartbeat(db) -> None:
    row = db.get(WorkerHeartbeat, worker_id)
    if row is None:
        row = WorkerHeartbeat(worker_id=worker_id, worker_type="outbox")
        db.add(row)
    row.heartbeat_at = utcnow()
    row.status = "healthy"


def _integration_health(db, integration_id: str) -> IntegrationHealth:
    row = db.get(IntegrationHealth, integration_id)
    if row is None:
        row = IntegrationHealth(integration_id=integration_id, status="UNKNOWN")
        db.add(row)
    return row


def _mark_healthy(db, integration_id: str) -> None:
    row = _integration_health(db, integration_id)
    row.status = "HEALTHY"
    row.last_success_at = utcnow()
    row.safe_error = None


def _mark_unhealthy(db, integration_id: str, error: str) -> None:
    row = _integration_health(db, integration_id)
    row.status = "UNHEALTHY"
    row.last_error_at = utcnow()
    row.safe_error = error[:1000]


def process_one() -> bool:
    db = SessionLocal()
    try:
        now = utcnow()
        message = db.scalar(
            select(OutboxMessage)
            .where(
                OutboxMessage.state.in_(["PENDING", "RETRYING"]),
                OutboxMessage.next_attempt_at <= now,
            )
            .order_by(OutboxMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        _heartbeat(db)
        if message is None:
            db.commit()
            return False
        message.attempts += 1
        adapter = EmulatorAdapter(settings.erp_emulator_url, settings.erp_timeout_seconds)
        try:
            ack = adapter.send_quality_result(message.payload)
            if ack.get("message_id") != message.message_id or ack.get("status") != "ACK":
                db.add(SecurityAlert(alert_type="INVALID_ACK", severity="HIGH", target_type="outbox_message",
                                     target_id=message.message_id, details={"ack_message_id": ack.get("message_id")}))
                raise ValueError("ERP acknowledgement correlation mismatch")
            message.state = "DELIVERED"
            message.delivered_at = utcnow()
            message.last_error = None
            db.add(
                IntegrationMessage(
                    message_id=message.message_id,
                    direction="outbound",
                    external_system=message.destination,
                    status="DELIVERED",
                    safe_payload={"ack": ack},
                )
            )
            _mark_healthy(db, message.destination)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in {408, 429} or status >= 500
            message.state = (
                "RETRYING" if retryable and message.attempts < settings.outbox_max_attempts else "FAILED"
            )
            message.last_error = f"HTTP {status}"
            if message.state == "RETRYING":
                message.next_attempt_at = utcnow() + timedelta(
                    seconds=min(2 ** message.attempts, 300)
                )
            db.add(
                IntegrationMessage(
                    message_id=message.message_id,
                    direction="outbound",
                    external_system=message.destination,
                    status=message.state,
                    safe_payload={"http_status": status, "attempt": message.attempts},
                )
            )
            _mark_unhealthy(db, message.destination, f"HTTP {status}")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            message.state = "RETRYING" if message.attempts < settings.outbox_max_attempts else "FAILED"
            message.last_error = type(exc).__name__
            message.next_attempt_at = utcnow() + timedelta(seconds=min(2 ** message.attempts, 300))
            db.add(
                IntegrationMessage(
                    message_id=message.message_id,
                    direction="outbound",
                    external_system=message.destination,
                    status=message.state,
                    safe_payload={"error_type": type(exc).__name__, "attempt": message.attempts},
                )
            )
            _mark_unhealthy(db, message.destination, type(exc).__name__)
        except ValueError as exc:
            message.state = "FAILED"
            message.last_error = str(exc)
            db.add(IntegrationMessage(message_id=message.message_id, direction="outbound",
                                      external_system=message.destination, status="FAILED",
                                      safe_payload={"error_type": "INVALID_ACK"}))
            _mark_unhealthy(db, message.destination, "INVALID_ACK")
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("outbox processing failed")
        return False
    finally:
        db.close()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        processed = process_one()
        if not processed:
            time.sleep(settings.outbox_poll_seconds)


if __name__ == "__main__":
    run()
