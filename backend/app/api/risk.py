from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    ApprovalRequest, BlastRadiusExposure, BlastRadiusQuery, ContainmentProposal,
    ControlDeviceInvalidation, Observation, OperationRun,
)
from backend.app.projections.rebuild import rebuild_item
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_critical_permission, require_permission
from backend.app.security.crypto import utcnow
from backend.app.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


class BlastRadiusRequest(BaseModel):
    factor_type: str = Field(pattern="^(equipment|tool|material_lot|control_device|component|time_interval)$")
    factor_value: str = Field(min_length=1, max_length=256)
    affected_from: datetime
    affected_to: datetime
    proposed_action: str = Field(default="REVIEW_REQUIRED", pattern="^(REVIEW_REQUIRED|REINSPECTION_REQUIRED|HOLD)$")
    rationale: str = Field(min_length=3, max_length=3000)

    @model_validator(mode="after")
    def period(self):
        if self.affected_to < self.affected_from:
            raise ValueError("affected_to must not be before affected_from")
        return self


class ApprovalInput(BaseModel):
    reason: str = Field(min_length=3, max_length=3000)


class InvalidationInput(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    affected_from: datetime
    affected_to: datetime
    reason: str = Field(min_length=3, max_length=2000)
    invalidation_type: str | None = Field(default=None, max_length=64)
    supporting_evidence_refs: list[str] = Field(default_factory=list, max_length=100)


def _matches(run: OperationRun, body: BlastRadiusRequest) -> bool:
    if body.factor_type == "time_interval":
        return True
    if body.factor_type == "equipment":
        return run.equipment_id == body.factor_value
    params = run.parameters or {}
    key = {"tool": "tool_id", "material_lot": "material_lot_id", "component": "component_instance_id"}.get(body.factor_type)
    return bool(key and params.get(key) == body.factor_value)


@router.post("/blast-radius")
def blast_radius(
    body: BlastRadiusRequest, request: Request,
    principal: Principal = Depends(require_permission("RUN_BLAST_RADIUS")),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
):
    query = BlastRadiusQuery(factor_type=body.factor_type, factor_value=body.factor_value,
                             affected_from=body.affected_from, affected_to=body.affected_to,
                             requested_by=principal.user_id)
    db.add(query); db.flush()
    candidates: dict[str, tuple[str | None, str | None, list[str]]] = {}
    if body.factor_type == "control_device":
        for obs in db.scalars(select(Observation).where(
            Observation.control_device_id == body.factor_value,
            Observation.occurred_at >= body.affected_from,
            Observation.occurred_at <= body.affected_to,
        )).all():
            candidates[obs.item_id] = (obs.event_id, obs.operation_run_id, ["control_device", body.factor_value])
    else:
        for run in db.scalars(select(OperationRun).where(
            OperationRun.started_at <= body.affected_to,
            (OperationRun.finished_at.is_(None) | (OperationRun.finished_at >= body.affected_from)),
        )).all():
            if _matches(run, body):
                candidates[run.item_id] = (None, run.operation_run_id, [body.factor_type, body.factor_value])
    result = []
    for item_id, (event_id, run_id, path) in sorted(candidates.items()):
        last = db.scalar(select(Observation).where(Observation.item_id == item_id).order_by(Observation.occurred_at.desc()).limit(1))
        exposure = BlastRadiusExposure(query_id=query.id, item_id=item_id, relationship_path=path,
            exposure_event_id=event_id, operation_run_id=run_id,
            last_inspection_event_id=last.event_id if last else None, proposed_action=body.proposed_action)
        db.add(exposure)
        result.append({"item_id": item_id, "relationship_path": path, "exposure_event_id": event_id,
                       "operation_run_id": run_id, "last_relevant_inspection": last.event_id if last else None,
                       "proposed_action": body.proposed_action})
    proposal = ContainmentProposal(nonconformance_id=None, blast_radius_query_id=query.id,
        proposed_by=principal.user_id, containment=body.proposed_action, rationale=body.rationale)
    db.add(proposal); db.flush()
    approvals_required = 2 if len(result) >= settings.mass_containment_threshold else 1
    approval = ApprovalRequest(action_type="MASS_CONTAINMENT" if approvals_required == 2 else "CONTAINMENT",
        target_type="containment_proposal", target_id=str(proposal.id), requester_id=principal.user_id,
        required_approvals=approvals_required, reason=body.rationale)
    db.add(approval)
    write_audit(db, action="containment_proposal", outcome="pending", actor_user_id=principal.user_id,
        session_id=principal.session_id, target_type="blast_radius", target_id=str(query.id),
        request_id=request.state.request_id, safe_details={"affected_items": len(result), "required_approvals": approvals_required})
    db.commit()
    return {"query_id": query.id, "proposal_id": proposal.id, "approval_request_id": approval.id,
            "affected_items": result, "required_approvals": approvals_required,
            "note": "No defect or HOLD is applied until controller approval."}


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: uuid.UUID, body: ApprovalInput, request: Request,
    principal: Principal = Depends(require_critical_permission("APPROVE_CONTAINMENT")),
    db: Session = Depends(get_db),
):
    approval = db.get(ApprovalRequest, approval_id)
    if not approval:
        raise NotFoundError("Approval request")
    if approval.status != "PENDING":
        raise TraceQError("APPROVAL_ALREADY_COMPLETE", "Approval request is not pending", 409)
    if approval.requester_id == principal.user_id:
        raise TraceQError("SEPARATION_OF_DUTIES", "Requester cannot approve this action", 403)
    approvals = list(approval.approvals or [])
    if any(row["user_id"] == str(principal.user_id) for row in approvals):
        raise TraceQError("DUPLICATE_APPROVAL", "This user already approved", 409)
    approvals.append({"user_id": str(principal.user_id), "reason": body.reason, "at": utcnow().isoformat()})
    approval.approvals = approvals
    if len(approvals) >= approval.required_approvals:
        approval.status, approval.completed_at = "APPROVED", utcnow()
        proposal = db.get(ContainmentProposal, uuid.UUID(approval.target_id))
        if proposal:
            proposal.status, proposal.reviewed_by, proposal.review_reason, proposal.reviewed_at = "approved", principal.user_id, body.reason, utcnow()
    write_audit(db, action="containment_approval", outcome=approval.status.lower(), actor_user_id=principal.user_id,
        session_id=principal.session_id, target_type="approval_request", target_id=str(approval.id), request_id=request.state.request_id)
    db.commit()
    return {"status": approval.status, "approvals": len(approvals), "required": approval.required_approvals}


@router.post("/control-devices/invalidate")
def invalidate_device(
    body: InvalidationInput, request: Request,
    principal: Principal = Depends(require_critical_permission("INVALIDATE_CONTROL_DEVICE")),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
):
    record = ControlDeviceInvalidation(device_id=body.device_id, affected_from=body.affected_from,
        affected_to=body.affected_to, reason=body.reason, invalidation_type=body.invalidation_type,
        supporting_evidence_refs=body.supporting_evidence_refs, created_by_user_id=principal.user_id)
    db.add(record); db.flush()
    item_ids = sorted(set(db.scalars(select(Observation.item_id).where(
        Observation.control_device_id == body.device_id,
        Observation.occurred_at >= body.affected_from,
        Observation.occurred_at <= body.affected_to,
    )).all()))
    for item_id in item_ids:
        rebuild_item(db, item_id, settings)
    write_audit(db, action="control_device_invalidation", outcome="success", actor_user_id=principal.user_id,
        session_id=principal.session_id, target_type="control_device", target_id=body.device_id,
        request_id=request.state.request_id, safe_details={"affected_items": item_ids, "reason": body.reason})
    db.commit()
    return {"invalidation_id": record.id, "affected_items": item_ids}
