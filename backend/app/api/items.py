from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError
from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    Item,
    MachineEvent,
    Nonconformance,
    Observation,
    OperationRun,
    OperatorAction,
    ProjectionState,
    RawEvent,
)
from backend.app.security.auth import Principal, require_permission


router = APIRouter(prefix="/api/v1/items", tags=["items"])


@router.get("")
def list_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_permission("VIEW_PRODUCT")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Item).order_by(Item.registered_at.desc()).offset(offset).limit(limit)).all()
    return [
        {
            "item_id": item.item_id,
            "product_definition_id": item.product_definition_id,
            "revision": item.revision,
            "line_id": item.line_id,
            "status": item.status,
            "structure_status": item.structure_status,
            "registered_at": item.registered_at,
        }
        for item in rows
    ]


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
    ncrs = db.scalars(
        select(Nonconformance).where(Nonconformance.item_id == item_id).order_by(Nonconformance.opened_at)
    ).all()
    return {
        "item_id": item.item_id,
        "product_definition_id": item.product_definition_id,
        "revision": item.revision,
        "line_id": item.line_id,
        "route_revision_id": item.route_revision_id,
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
    events: list[dict] = []
    for raw in db.scalars(
        select(RawEvent).where(RawEvent.item_id == item_id).order_by(
            RawEvent.occurred_at,
            RawEvent.source_id,
            RawEvent.source_sequence.asc().nullslast(),
            RawEvent.received_at,
            RawEvent.event_id,
        )
    ).all():
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
    trust = {
        row.event_id: {"trust_status": row.trust_status, "trust_reasons": row.trust_reasons}
        for row in db.scalars(select(Observation).where(Observation.item_id == item_id)).all()
    }
    for event in events:
        event.update(trust.get(event["event_id"], {}))
    return {"item_id": item_id, "events": events}


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
