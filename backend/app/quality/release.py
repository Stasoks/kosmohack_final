from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import TraceQError
from backend.app.persistence.models import (
    ControllerDecision, DefectOccurrence, Item, Nonconformance, OutboxMessage, QualityResult,
)
from backend.app.security.crypto import utcnow


class OutboundReleasePolicy:
    """The only constructor path for outbound quality results."""

    @staticmethod
    def authorize(db: Session, ncr: Nonconformance, decision: ControllerDecision) -> None:
        if decision.nonconformance_id != ncr.id or decision.verdict not in {"confirmed", "rejected"}:
            raise TraceQError("ACTION_NOT_AUTHORIZED", "An authorized controller decision is required", 403)
        if decision.disposition not in {"RELEASED", "USE_AS_IS", "SCRAPPED"}:
            raise TraceQError("ACTION_NOT_AUTHORIZED", "This disposition is not exportable", 403)
        if ncr.resolution_type == "rework" and ncr.verification_status != "PASSED":
            raise TraceQError("REWORK_VERIFICATION_REQUIRED", "Successful controller verification is required", 409)

    @classmethod
    def create_result(cls, db: Session, ncr: Nonconformance, decision: ControllerDecision) -> tuple[str, dict]:
        cls.authorize(db, ncr, decision)
        message_id = f"QR-{decision.id}"
        existing = db.scalar(select(QualityResult).where(QualityResult.decision_id == decision.id))
        if existing:
            return existing.message_id, existing.payload
        payload = {
            "message_id": message_id, "item_id": ncr.item_id,
            "nonconformance_id": str(ncr.id), "decision_id": str(decision.id),
            "verdict": decision.verdict, "disposition": decision.disposition,
            "containment": decision.containment, "decided_at": utcnow().isoformat(),
        }
        db.add(QualityResult(message_id=message_id, decision_id=decision.id, item_id=ncr.item_id, payload=payload))
        db.add(OutboxMessage(message_id=message_id, destination="erp-emulator", message_type="quality.result", payload=payload))
        item = db.get(Item, ncr.item_id)
        if item:
            item.status = decision.disposition
        ncr.closed_at = utcnow()
        occurrence = db.get(DefectOccurrence, ncr.occurrence_id)
        if occurrence:
            occurrence.status, occurrence.closed_at = "CLOSED", utcnow()
        return message_id, payload
