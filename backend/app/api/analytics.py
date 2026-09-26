from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.persistence.database import get_db
from backend.app.persistence.models import (
    AnalysisVersion,
    DefectObservation,
    DefectOccurrence,
    IngestAttempt,
    IntegrationHealth,
    Item,
    Nonconformance,
    Observation,
    OperationRun,
    OutboxMessage,
    ProjectionState,
    WorkerHeartbeat,
)
from backend.app.security.auth import Principal, require_any_permission, require_permission


router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/kpi")
def quality_kpi(
    _: Principal = Depends(require_permission("VIEW_ANALYTICS")),
    db: Session = Depends(get_db),
):
    calculated_at = datetime.now(timezone.utc)
    inspected = db.scalar(select(func.count(func.distinct(Observation.item_id)))) or 0
    assessable = db.scalar(
        select(func.count(func.distinct(Observation.item_id))).where(
            Observation.trust_status == "TRUSTED"
        )
    ) or 0
    confirmed_items = db.scalar(
        select(func.count(func.distinct(Nonconformance.item_id))).where(
            Nonconformance.verdict == "confirmed"
        )
    ) or 0
    unique_defects = db.scalar(select(func.count(DefectOccurrence.id))) or 0
    observed_defects = db.scalar(select(func.count(DefectObservation.id))) or 0
    confirmed_physical_defects = db.scalar(
        select(func.count(func.distinct(DefectOccurrence.id)))
        .join(
            Nonconformance,
            Nonconformance.occurrence_id == DefectOccurrence.id,
        )
        .where(Nonconformance.verdict == "confirmed")
    ) or 0
    defect_groups = db.execute(
        select(DefectOccurrence.defect_type, func.count(DefectOccurrence.id))
        .group_by(DefectOccurrence.defect_type)
        .order_by(func.count(DefectOccurrence.id).desc())
    ).all()
    detection_groups = db.execute(
        select(Item.line_id, OperationRun.station_id, func.count(DefectObservation.id))
        .join(Observation, Observation.id == DefectObservation.observation_id)
        .join(Item, Item.item_id == Observation.item_id)
        .outerjoin(OperationRun, OperationRun.operation_run_id == Observation.operation_run_id)
        .group_by(Item.line_id, OperationRun.station_id)
    ).all()
    durations = []
    for run in db.scalars(select(OperationRun).where(OperationRun.duration_value.is_not(None))).all():
        factor = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}.get(run.duration_unit or "s", 1.0)
        durations.append((run.duration_value or 0) * factor)
    durations.sort()

    def percentile(values: list[float], ratio: float) -> float | None:
        if not values:
            return None
        position = (len(values) - 1) * ratio
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        fraction = position - lower
        return values[lower] * (1 - fraction) + values[upper] * fraction

    rework_count = db.scalar(
        select(func.count(OperationRun.operation_run_id)).where(OperationRun.run_reason == "rework")
    ) or 0
    total_items = db.scalar(select(func.count(Item.item_id))) or 0
    rework_items = db.scalar(
        select(func.count(func.distinct(OperationRun.item_id))).where(OperationRun.run_reason == "rework")
    ) or 0
    widths = [
        (row.right_boundary_at - row.left_boundary_at).total_seconds()
        for row in db.scalars(
            select(AnalysisVersion).where(
                AnalysisVersion.left_boundary_at.is_not(None),
                AnalysisVersion.right_boundary_at.is_not(None),
            )
        ).all()
    ]
    detection_delays = [
        (observation.occurred_at - run.finished_at).total_seconds()
        for observation, run in db.execute(
            select(Observation, OperationRun)
            .join(OperationRun, OperationRun.operation_run_id == Observation.operation_run_id)
            .where(
                Observation.inspection_result == "defect_detected",
                Observation.trust_status == "TRUSTED",
                OperationRun.finished_at.is_not(None),
                Observation.occurred_at >= OperationRun.finished_at,
            )
        ).all()
    ]
    return {
        "calculated_at": calculated_at,
        "recalculated_at": calculated_at,
        "inspected_items": inspected,
        "assessable_inspected_items": assessable,
        "items_with_confirmed_nc": confirmed_items,
        "number_of_unique_defects": unique_defects,
        "observed_defect_signals": observed_defects,
        "confirmed_physical_defects": confirmed_physical_defects,
        "defects_by_type": {name: count for name, count in defect_groups},
        "detected_defects_by_line_station": [
            {"line_id": line_id, "station_id": station_id, "count": count}
            for line_id, station_id, count in detection_groups
        ],
        "established_causes": db.scalar(
            select(func.count(Nonconformance.id)).where(
                Nonconformance.cause_status == "confirmed_by_human"
            )
        )
        or 0,
        "unknown_causes": db.scalar(
            select(func.count(Nonconformance.id)).where(
                Nonconformance.cause_status == "not_established"
            )
        )
        or 0,
        "operation_duration_avg_seconds": sum(durations) / len(durations) if durations else None,
        "operation_duration_median_seconds": percentile(durations, 0.5),
        "operation_duration_p95_seconds": percentile(durations, 0.95),
        "rework_count": rework_count,
        "rework_items": rework_items,
        "rework_item_rate": rework_items / total_items if total_items else None,
        "first_pass_yield": (assessable - confirmed_items) / assessable if assessable else None,
        "birth_window_width_avg_seconds": sum(widths) / len(widths) if widths else None,
        "birth_window_width_p95_seconds": percentile(sorted(widths), 0.95),
        "post_operation_detection_delay_avg_seconds": (
            sum(detection_delays) / len(detection_delays) if detection_delays else None
        ),
        "notes": {
            "defects_by_station": "Detection/context grouping; it is not a root-cause statement.",
            "late_events": "Historical KPI can change after deterministic replay.",
        },
    }


@router.get("/data-health")
def data_health(
    _: Principal = Depends(require_any_permission("VIEW_ANALYTICS", "MANAGE_INTEGRATIONS")),
    db: Session = Depends(get_db),
):
    statuses = dict(
        db.execute(
            select(IngestAttempt.status, func.count(IngestAttempt.id)).group_by(IngestAttempt.status)
        ).all()
    )
    errors = dict(
        db.execute(
            select(IngestAttempt.error_code, func.count(IngestAttempt.id))
            .where(IngestAttempt.error_code.is_not(None))
            .group_by(IngestAttempt.error_code)
        ).all()
    )
    projections = dict(
        db.execute(
            select(ProjectionState.status, func.count(ProjectionState.item_id)).group_by(
                ProjectionState.status
            )
        ).all()
    )
    outbox = dict(
        db.execute(
            select(OutboxMessage.state, func.count(OutboxMessage.id)).group_by(OutboxMessage.state)
        ).all()
    )
    latest_attempt = db.scalar(
        select(IngestAttempt).order_by(IngestAttempt.received_at.desc()).limit(1)
    )
    problem_items = db.scalars(
        select(ProjectionState)
        .where(ProjectionState.status != "up_to_date")
        .order_by(ProjectionState.item_id)
        .limit(100)
    ).all()
    return {
        "calculated_at": datetime.now(timezone.utc),
        "ingestion": statuses,
        "errors": errors,
        "last_ingest_at": latest_attempt.received_at if latest_attempt else None,
        "projections": projections,
        "outbox": outbox,
        "problem_items": [
            {
                "item_id": row.item_id,
                "status": row.status,
                "last_error": row.last_error,
                "last_rebuild_at": row.last_successful_rebuild_at,
            }
            for row in problem_items
        ],
        "integrations": [
            {
                "integration_id": row.integration_id,
                "status": row.status,
                "last_success_at": row.last_success_at,
                "last_error_at": row.last_error_at,
                "safe_error": row.safe_error,
            }
            for row in db.scalars(select(IntegrationHealth)).all()
        ],
        "worker_heartbeats": [
            {
                "worker_id": row.worker_id,
                "worker_type": row.worker_type,
                "heartbeat_at": row.heartbeat_at,
                "status": row.status,
            }
            for row in db.scalars(select(WorkerHeartbeat)).all()
        ],
    }
