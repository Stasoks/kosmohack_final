from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    ControlDeviceInvalidation,
    ControllerDecision,
    Item,
    Nonconformance,
    Observation,
    OperationRun,
    ProjectionState,
    RawEvent,
    RouteDefinition,
    RouteRevision,
)
from backend.app.quality.trust import scope_coverage
from backend.app.read_models.timeline import build_business_activity
from backend.app.security.auth import Principal, require_permission


router = APIRouter(prefix="/api/v1/items", tags=["items"])


def _route_identity(db: Session, route_revision_id) -> tuple[str | None, int | None]:
    if not route_revision_id:
        return None, None
    revision = db.get(RouteRevision, route_revision_id)
    if not revision:
        return None, None
    route = db.get(RouteDefinition, revision.route_id)
    return (route.code if route else None), revision.revision


@router.get("")
def list_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_permission("VIEW_PRODUCT")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Item).order_by(Item.registered_at.desc()).offset(offset).limit(limit)).all()
    result = []
    for item in rows:
        route_code, route_revision = _route_identity(db, item.route_revision_id)
        result.append({
            "item_id": item.item_id,
            "product_definition_id": item.product_definition_id,
            "revision": item.revision,
            "line_id": item.line_id,
            "status": item.status,
            "structure_status": item.structure_status,
            "registered_at": item.registered_at,
            "route_code": route_code,
            "route_revision": route_revision,
        })
    return result


@router.get("/{item_id}")
def get_item(
    item_id: str,
    _: Principal = Depends(require_permission("VIEW_PRODUCT")),
    db: Session = Depends(get_db),
):
    item = db.get(Item, item_id)
    if not item:
        raise NotFoundError("Item")
    projection = db.get(ProjectionState, item_id)
    route_code, route_revision = _route_identity(db, item.route_revision_id)
    ncrs = db.scalars(
        select(Nonconformance).where(Nonconformance.item_id == item_id).order_by(Nonconformance.opened_at)
    ).all()
    return {
        "item_id": item.item_id,
        "product_definition_id": item.product_definition_id,
        "revision": item.revision,
        "line_id": item.line_id,
        "route_revision_id": item.route_revision_id,
        "route_code": route_code,
        "route_revision": route_revision,
        "status": item.status,
        "structure_status": item.structure_status,
        "registered_at": item.registered_at,
        "projection": {
            "status": projection.status,
            "version": projection.projection_version,
            "last_rebuild": projection.last_successful_rebuild_at,
            "last_error": projection.last_error,
        }
        if projection
        else None,
        "nonconformances": [
            {
                "id": ncr.id,
                "defect_type": ncr.defect_type,
                "verdict": ncr.verdict,
                "cause_status": ncr.cause_status,
                "disposition": ncr.disposition,
                "containment": ncr.containment,
                "analysis_version": ncr.current_analysis_version,
            }
            for ncr in ncrs
        ],
    }


@router.get("/{item_id}/timeline")
def timeline(
    item_id: str,
    _: Principal = Depends(require_permission("VIEW_TIMELINE")),
    db: Session = Depends(get_db),
):
    if not db.get(Item, item_id):
        raise NotFoundError("Item")
    raw_events = db.scalars(
        select(RawEvent).where(RawEvent.item_id == item_id).order_by(
            RawEvent.occurred_at,
            RawEvent.source_id,
            RawEvent.source_sequence.asc().nullslast(),
            RawEvent.received_at,
            RawEvent.event_id,
        )
    ).all()
    events: list[dict] = []
    for raw in raw_events:
        events.append(
            {
                "event_id": raw.event_id,
                "event_type": raw.event_type,
                "occurred_at": raw.occurred_at,
                "received_at": raw.received_at,
                "source_id": raw.source_id,
                "source_sequence": raw.source_sequence,
            }
        )
    observations = db.scalars(
        select(Observation).where(Observation.item_id == item_id)
    ).all()
    trust = {
        row.event_id: {"trust_status": row.trust_status, "trust_reasons": row.trust_reasons}
        for row in observations
    }
    for event in events:
        event.update(trust.get(event["event_id"], {}))
    nonconformances = db.scalars(
        select(Nonconformance)
        .where(Nonconformance.item_id == item_id)
        .order_by(Nonconformance.opened_at, Nonconformance.id)
    ).all()
    ncr_ids = [row.id for row in nonconformances]
    decisions = (
        db.scalars(
            select(ControllerDecision)
            .where(ControllerDecision.nonconformance_id.in_(ncr_ids))
            .order_by(ControllerDecision.created_at, ControllerDecision.id)
        ).all()
        if ncr_ids
        else []
    )
    operation_runs = db.scalars(
        select(OperationRun).where(OperationRun.item_id == item_id)
    ).all()
    device_ids = [row.control_device_id for row in observations if row.control_device_id]
    invalidations = (
        db.scalars(
            select(ControlDeviceInvalidation).where(
                ControlDeviceInvalidation.device_id.in_(device_ids)
            )
        ).all()
        if device_ids
        else []
    )
    activity = build_business_activity(
        raw_events=list(raw_events),
        observations=list(observations),
        nonconformances=list(nonconformances),
        decisions=list(decisions),
        operation_runs=list(operation_runs),
        invalidations=list(invalidations),
    )
    return {"item_id": item_id, "events": events, "activity": activity}


@router.get("/{item_id}/analysis")
def analyses(
    item_id: str,
    _: Principal = Depends(require_permission("VIEW_NONCONFORMANCE")),
    db: Session = Depends(get_db),
):
    ncrs = db.scalars(select(Nonconformance).where(Nonconformance.item_id == item_id)).all()
    result = []
    for ncr in ncrs:
        versions = db.scalars(
            select(AnalysisVersion)
            .where(AnalysisVersion.nonconformance_id == ncr.id)
            .order_by(AnalysisVersion.version)
        ).all()
        version_values = []
        for version in versions:
            evidence = db.scalars(
                select(AnalysisEvidence)
                .where(AnalysisEvidence.analysis_version_id == version.id)
                .order_by(AnalysisEvidence.occurred_at.asc().nullsfirst(), AnalysisEvidence.id)
            ).all()
            evidence_event_ids = [row.source_event_id for row in evidence if row.source_event_id]
            observations = (
                db.scalars(
                    select(Observation).where(Observation.event_id.in_(evidence_event_ids))
                ).all()
                if evidence_event_ids
                else []
            )
            observations_by_event = {row.event_id: row for row in observations}
            raw_sources = (
                {
                    row.event_id: row.source_id
                    for row in db.scalars(
                        select(RawEvent).where(RawEvent.event_id.in_(evidence_event_ids))
                    ).all()
                }
                if evidence_event_ids
                else {}
            )
            version_values.append(
                {
                    "version": version.version,
                    "status": version.status,
                    "left_boundary_at": version.left_boundary_at,
                    "right_boundary_at": version.right_boundary_at,
                    "algorithm_version": version.algorithm_version,
                    "reason": version.reason,
                    "created_at": version.created_at,
                    "evidence": [
                        {
                            "type": item.evidence_type,
                            "role": item.evidence_role,
                            "source_event_id": item.source_event_id,
                            "occurred_at": item.occurred_at,
                            "details": item.details,
                            "coverage": (
                                scope_coverage(
                                    observations_by_event[item.source_event_id].inspection_scope,
                                    ncr.defect_type,
                                    ncr.component_instance_id,
                                )
                                if item.source_event_id in observations_by_event
                                else None
                            ),
                            "observation": (
                                {
                                    "source_id": raw_sources.get(item.source_event_id),
                                    "inspection_result": observations_by_event[
                                        item.source_event_id
                                    ].inspection_result,
                                    "control_point_id": observations_by_event[
                                        item.source_event_id
                                    ].control_point_id,
                                    "control_device_id": observations_by_event[
                                        item.source_event_id
                                    ].control_device_id,
                                    "trust_status": observations_by_event[
                                        item.source_event_id
                                    ].trust_status,
                                    "trust_reasons": observations_by_event[
                                        item.source_event_id
                                    ].trust_reasons,
                                }
                                if item.source_event_id in observations_by_event
                                else None
                            ),
                        }
                        for item in evidence
                    ],
                }
            )
        result.append(
            {
                "nonconformance_id": ncr.id,
                "defect_type": ncr.defect_type,
                "component_instance_id": ncr.component_instance_id,
                "cause_status": ncr.cause_status,
                "versions": version_values,
            }
        )
    return result
