from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    ControllerDecision,
    ContainmentProposal,
    DefectOccurrence,
    IntegrityStreamState,
    Item,
    InvestigationNote,
    Nonconformance,
    OutboxMessage,
    Observation,
    OperationRun,
    QualityResult,
    RawEvent,
)
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_critical_permission, require_permission
from backend.app.security.crypto import utcnow
from backend.app.quality.release import OutboundReleasePolicy
from backend.app.quality.rework import repeat_good_covers_nonconformance


router = APIRouter(prefix="/api/v1/nonconformances", tags=["nonconformances"])


class ReviewRequest(BaseModel):
    verdict: str = Field(pattern="^(pending_review|needs_extra_check)$")
    reason: str = Field(min_length=3, max_length=2000)


class DecisionRequest(BaseModel):
    verdict: str = Field(pattern="^(confirmed|rejected)$")
    disposition: str = Field(
        pattern="^(IN_PROCESS|REWORK_REQUIRED|RELEASED|SCRAPPED|USE_AS_IS)$"
    )
    containment: str = Field(pattern="^(NONE|HOLD|REINSPECTION_REQUIRED|REVIEW_REQUIRED)$")
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def valid_combination(self) -> "DecisionRequest":
        if self.verdict == "rejected" and self.disposition == "REWORK_REQUIRED":
            raise ValueError("A rejected NCR cannot require rework")
        return self


class InspectionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    control_point_id: str | None = Field(default=None, max_length=128)


class NoteRequest(BaseModel):
    body: str = Field(min_length=3, max_length=5000)


class ContainmentProposalRequest(BaseModel):
    containment: str = Field(pattern="^(HOLD|REINSPECTION_REQUIRED|REVIEW_REQUIRED)$")
    rationale: str = Field(min_length=3, max_length=3000)


class ContainmentReviewRequest(BaseModel):
    approve: bool
    reason: str = Field(min_length=3, max_length=3000)


class ReworkVerificationRequest(BaseModel):
    passed: bool
    reason: str = Field(min_length=3, max_length=3000)


def _ncr_or_404(db: Session, ncr_id: uuid.UUID) -> Nonconformance:
    ncr = db.get(Nonconformance, ncr_id)
    if not ncr:
        raise NotFoundError("Nonconformance")
    return ncr


def _ensure_evidence_integrity(db: Session, item_id: str) -> None:
    failed = db.scalar(
        select(IntegrityStreamState.stream_id)
        .join(RawEvent, RawEvent.integrity_stream_id == IntegrityStreamState.stream_id)
        .where(RawEvent.item_id == item_id, IntegrityStreamState.status == "INTEGRITY_FAILED")
        .limit(1)
    )
    if failed:
        raise TraceQError(
            "EVIDENCE_INTEGRITY_FAILED",
            "A decision is blocked because supporting evidence failed integrity verification",
            409,
        )


@router.get("")
def list_nonconformances(
    verdict: str | None = None,
    _: Principal = Depends(require_permission("VIEW_NONCONFORMANCE")),
    db: Session = Depends(get_db),
):
    query = select(Nonconformance).order_by(Nonconformance.opened_at.desc())
    if verdict:
        query = query.where(Nonconformance.verdict == verdict)
    rows = db.scalars(query).all()
    return [
        {
            "id": row.id,
            "item_id": row.item_id,
            "defect_type": row.defect_type,
            "component_instance_id": row.component_instance_id,
            "verdict": row.verdict,
            "cause_status": row.cause_status,
            "disposition": row.disposition,
            "containment": row.containment,
            "opened_at": row.opened_at,
            "closed_at": row.closed_at,
            "current_analysis_version": row.current_analysis_version,
            "resolution_type": row.resolution_type,
            "resolved_at": row.resolved_at,
            "verification_status": row.verification_status,
        }
        for row in rows
    ]


@router.get("/{ncr_id}")
def get_nonconformance(
    ncr_id: uuid.UUID,
    _: Principal = Depends(require_permission("VIEW_NONCONFORMANCE")),
    db: Session = Depends(get_db),
):
    row = _ncr_or_404(db, ncr_id)
    versions = db.scalars(
        select(AnalysisVersion)
        .where(AnalysisVersion.nonconformance_id == row.id)
        .order_by(AnalysisVersion.version)
    ).all()
    decisions = db.scalars(
        select(ControllerDecision)
        .where(ControllerDecision.nonconformance_id == row.id)
        .order_by(ControllerDecision.created_at)
    ).all()
    notes = db.scalars(
        select(InvestigationNote)
        .where(InvestigationNote.nonconformance_id == row.id)
        .order_by(InvestigationNote.created_at)
    ).all()
    proposals = db.scalars(
        select(ContainmentProposal)
        .where(ContainmentProposal.nonconformance_id == row.id)
        .order_by(ContainmentProposal.created_at)
    ).all()
    return {
        "id": row.id,
        "item_id": row.item_id,
        "defect_type": row.defect_type,
        "component_instance_id": row.component_instance_id,
        "verdict": row.verdict,
        "cause_status": row.cause_status,
        "disposition": row.disposition,
        "containment": row.containment,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
        "resolution_type": row.resolution_type,
        "resolved_at": row.resolved_at,
        "verification_status": row.verification_status,
        "current_analysis_version": row.current_analysis_version,
        "analysis_versions": [
            {
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "left_boundary_at": version.left_boundary_at,
                "right_boundary_at": version.right_boundary_at,
                "reason": version.reason,
            }
            for version in versions
        ],
        "decisions": [
            {
                "id": decision.id,
                "user_id": decision.user_id,
                "verdict": decision.verdict,
                "disposition": decision.disposition,
                "containment": decision.containment,
                "reason": decision.reason,
                "analysis_version": decision.analysis_version,
                "created_at": decision.created_at,
            }
            for decision in decisions
        ],
        "investigation_notes": [
            {
                "id": note.id,
                "author_user_id": note.author_user_id,
                "body": note.body,
                "created_at": note.created_at,
            }
            for note in notes
        ],
        "containment_proposals": [
            {
                "id": proposal.id,
                "proposed_by": proposal.proposed_by,
                "containment": proposal.containment,
                "rationale": proposal.rationale,
                "status": proposal.status,
                "reviewed_by": proposal.reviewed_by,
                "review_reason": proposal.review_reason,
                "created_at": proposal.created_at,
                "reviewed_at": proposal.reviewed_at,
            }
            for proposal in proposals
        ],
    }


@router.post("/{ncr_id}/review")
def review_nonconformance(
    ncr_id: uuid.UUID,
    body: ReviewRequest,
    request: Request,
    principal: Principal = Depends(require_permission("REVIEW_NONCONFORMANCE")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    _ensure_evidence_integrity(db, ncr.item_id)
    ncr.verdict = body.verdict
    write_audit(
        db,
        action="nonconformance_review",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="nonconformance",
        target_id=str(ncr.id),
        request_id=request.state.request_id,
        safe_details={"verdict": body.verdict, "reason": body.reason},
    )
    db.commit()
    return {"status": "updated", "verdict": ncr.verdict}


@router.post("/{ncr_id}/decision")
def decide_nonconformance(
    ncr_id: uuid.UUID,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(require_critical_permission("ISSUE_QC_DECISION")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    _ensure_evidence_integrity(db, ncr.item_id)
    latest = db.scalar(
        select(ControllerDecision)
        .where(ControllerDecision.nonconformance_id == ncr.id)
        .order_by(ControllerDecision.created_at.desc())
        .limit(1)
    )
    decision = ControllerDecision(
        nonconformance_id=ncr.id,
        user_id=principal.user_id,
        verdict=body.verdict,
        disposition=body.disposition,
        containment=body.containment,
        reason=body.reason,
        analysis_version=ncr.current_analysis_version,
        previous_decision_id=latest.id if latest else None,
    )
    db.add(decision)
    db.flush()
    ncr.verdict = body.verdict
    ncr.disposition = body.disposition
    ncr.containment = body.containment
    item = db.get(Item, ncr.item_id)
    if item:
        item.status = body.disposition
    if body.disposition == "REWORK_REQUIRED":
        ncr.resolution_type = "rework"
        ncr.verification_status = "PENDING"
    message_id = None
    if body.disposition in {"RELEASED", "SCRAPPED", "USE_AS_IS"}:
        message_id, _ = OutboundReleasePolicy.create_result(db, ncr, decision)
    write_audit(
        db,
        action="controller_decision",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="nonconformance",
        target_id=str(ncr.id),
        request_id=request.state.request_id,
        safe_details={
            "verdict": body.verdict,
            "disposition": body.disposition,
            "containment": body.containment,
            "analysis_version": ncr.current_analysis_version,
        },
    )
    db.commit()
    return {"decision_id": decision.id, "message_id": message_id, "outbox_state": "PENDING" if message_id else None}


@router.post("/{ncr_id}/verify-rework")
def verify_rework(
    ncr_id: uuid.UUID, body: ReworkVerificationRequest, request: Request,
    principal: Principal = Depends(require_critical_permission("ISSUE_QC_DECISION")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    _ensure_evidence_integrity(db, ncr.item_id)
    run = db.scalar(select(OperationRun).where(
        OperationRun.item_id == ncr.item_id,
        OperationRun.run_reason == "rework",
        OperationRun.rework_for_nonconformance_id == ncr.id,
        OperationRun.completion_status == "completed",
    ).order_by(OperationRun.finished_at.desc()).limit(1))
    if not run or not run.finished_at:
        raise TraceQError("REWORK_NOT_COMPLETED", "A completed rework operation is required", 409)
    repeat_goods = db.scalars(select(Observation).where(
        Observation.item_id == ncr.item_id,
        Observation.occurred_at >= run.finished_at,
        Observation.inspection_result == "no_defect",
        Observation.trust_status == "TRUSTED",
    ).order_by(Observation.occurred_at.desc())).all()
    trusted_good = next(
        (
            observation
            for observation in repeat_goods
            if repeat_good_covers_nonconformance(
                observation,
                defect_type=ncr.defect_type,
                component_instance_id=ncr.component_instance_id,
            )
        ),
        None,
    )
    effective_pass = body.passed and trusted_good is not None
    latest = db.scalar(select(ControllerDecision).where(ControllerDecision.nonconformance_id == ncr.id).order_by(ControllerDecision.created_at.desc()).limit(1))
    decision = ControllerDecision(
        nonconformance_id=ncr.id, user_id=principal.user_id,
        verdict="confirmed", disposition="RELEASED" if effective_pass else "REWORK_REQUIRED",
        containment="NONE" if effective_pass else "HOLD", reason=body.reason,
        analysis_version=ncr.current_analysis_version, previous_decision_id=latest.id if latest else None,
    )
    db.add(decision); db.flush()
    ncr.verification_decision_id = decision.id
    ncr.verification_status = "PASSED" if effective_pass else "FAILED"
    message_id = None
    if effective_pass:
        ncr.resolution_type, ncr.resolved_at = "rework", utcnow()
        ncr.disposition, ncr.containment = "RELEASED", "NONE"
        message_id, _ = OutboundReleasePolicy.create_result(db, ncr, decision)
    else:
        ncr.disposition, ncr.containment = "REWORK_REQUIRED", "HOLD"
    write_audit(db, action="rework_verification", outcome="passed" if effective_pass else "failed",
                actor_user_id=principal.user_id, session_id=principal.session_id,
                target_type="nonconformance", target_id=str(ncr.id), request_id=request.state.request_id,
                safe_details={"reason": body.reason, "repeat_inspection_event_id": trusted_good.event_id if trusted_good else None})
    db.commit()
    return {"verification_status": ncr.verification_status, "decision_id": decision.id, "message_id": message_id}


@router.post("/{ncr_id}/request-inspection")
def request_inspection(
    ncr_id: uuid.UUID,
    body: InspectionRequest,
    request: Request,
    principal: Principal = Depends(require_permission("REQUEST_EXTRA_INSPECTION")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    ncr.verdict = "needs_extra_check"
    latest = db.scalar(
        select(ControllerDecision)
        .where(ControllerDecision.nonconformance_id == ncr.id)
        .order_by(ControllerDecision.created_at.desc())
        .limit(1)
    )
    decision = ControllerDecision(
        nonconformance_id=ncr.id,
        user_id=principal.user_id,
        verdict="needs_extra_check",
        disposition=ncr.disposition,
        containment="REINSPECTION_REQUIRED",
        reason=body.reason,
        analysis_version=ncr.current_analysis_version,
        previous_decision_id=latest.id if latest else None,
    )
    db.add(decision)
    ncr.containment = "REINSPECTION_REQUIRED"
    write_audit(
        db,
        action="extra_inspection_request",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="nonconformance",
        target_id=str(ncr.id),
        request_id=request.state.request_id,
        safe_details={"control_point_id": body.control_point_id, "reason": body.reason},
    )
    db.commit()
    return {"status": "requested", "decision_id": decision.id}


@router.post("/{ncr_id}/notes")
def add_investigation_note(
    ncr_id: uuid.UUID,
    body: NoteRequest,
    request: Request,
    principal: Principal = Depends(require_permission("CREATE_INVESTIGATION_NOTE")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    note = InvestigationNote(
        nonconformance_id=ncr.id,
        author_user_id=principal.user_id,
        body=body.body,
    )
    db.add(note)
    write_audit(
        db,
        action="investigation_note_create",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="nonconformance",
        target_id=str(ncr.id),
        request_id=request.state.request_id,
    )
    db.commit()
    return {"id": note.id}


@router.post("/{ncr_id}/containment-proposals")
def propose_containment(
    ncr_id: uuid.UUID,
    body: ContainmentProposalRequest,
    request: Request,
    principal: Principal = Depends(require_permission("PROPOSE_CONTAINMENT")),
    db: Session = Depends(get_db),
):
    ncr = _ncr_or_404(db, ncr_id)
    proposal = ContainmentProposal(
        nonconformance_id=ncr.id,
        proposed_by=principal.user_id,
        containment=body.containment,
        rationale=body.rationale,
    )
    db.add(proposal)
    write_audit(
        db,
        action="containment_proposal",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="nonconformance",
        target_id=str(ncr.id),
        request_id=request.state.request_id,
        safe_details={"containment": body.containment},
    )
    db.commit()
    return {"proposal_id": proposal.id, "status": proposal.status}


@router.post("/containment-proposals/{proposal_id}/review")
def review_containment(
    proposal_id: uuid.UUID,
    body: ContainmentReviewRequest,
    request: Request,
    principal: Principal = Depends(require_permission("APPROVE_CONTAINMENT")),
    db: Session = Depends(get_db),
):
    proposal = db.get(ContainmentProposal, proposal_id)
    if not proposal:
        raise NotFoundError("Containment proposal")
    if proposal.status != "pending":
        raise TraceQError("PROPOSAL_ALREADY_REVIEWED", "Containment proposal was already reviewed", 409)
    ncr = _ncr_or_404(db, proposal.nonconformance_id)
    proposal.status = "approved" if body.approve else "rejected"
    proposal.reviewed_by = principal.user_id
    proposal.review_reason = body.reason
    proposal.reviewed_at = utcnow()
    if body.approve:
        ncr.containment = proposal.containment
    write_audit(
        db,
        action="containment_approval" if body.approve else "containment_rejection",
        outcome="success",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="containment_proposal",
        target_id=str(proposal.id),
        request_id=request.state.request_id,
        safe_details={"containment": proposal.containment, "reason": body.reason},
    )
    db.commit()
    return {"proposal_id": proposal.id, "status": proposal.status, "containment": ncr.containment}
