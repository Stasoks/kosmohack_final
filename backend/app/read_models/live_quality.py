from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.persistence.models import (
    ControllerDecision,
    DefectObservation,
    Item,
    MachineEvent,
    Nonconformance,
    Observation,
    OperationRun,
)


LiveWindow = Literal["15m", "1h", "24h", "all"]
WINDOW_DURATIONS: dict[str, timedelta | None] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "all": None,
}
WARNING_STATES = ("warning", "error", "fault", "alarm")


def first_pass_yield(assessable_items: int, confirmed_items: int) -> float | None:
    """Return the canonical TRACE-Q FPY formula for a supplied item scope."""
    if not assessable_items:
        return None
    return (assessable_items - confirmed_items) / assessable_items


def _boundary(window: LiveWindow, calculated_at: datetime) -> datetime | None:
    duration = WINDOW_DURATIONS[window]
    return calculated_at - duration if duration is not None else None


def _time_filters(column, boundary: datetime | None) -> list[Any]:
    return [column >= boundary] if boundary is not None else []


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def _floor_bucket(value: datetime, minutes: int) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(
        minute=(value.minute // minutes) * minutes,
        second=0,
        microsecond=0,
    )


def _timeline(
    db: Session,
    *,
    window: LiveWindow,
    boundary: datetime | None,
    calculated_at: datetime,
) -> list[dict[str, Any]]:
    if window == "all":
        bucket = func.date_trunc("day", Observation.occurred_at).label("bucket")
        rows = db.execute(
            select(
                bucket,
                Observation.inspection_result,
                func.count(func.distinct(Observation.item_id)).label("count"),
            )
            .where(
                Observation.trust_status == "TRUSTED",
                Observation.inspection_result.in_(("no_defect", "defect_detected")),
            )
            .group_by(bucket, Observation.inspection_result)
            .order_by(bucket.desc())
            .limit(180)
        ).all()
        values: dict[datetime, dict[str, Any]] = {}
        for row in rows:
            point = values.setdefault(row.bucket, {"bucket": row.bucket, "good": 0, "defect": 0})
            point["good" if row.inspection_result == "no_defect" else "defect"] += int(
                row.count
            )
        return sorted(values.values(), key=lambda value: value["bucket"])[-90:]

    bucket_minutes = {"15m": 1, "1h": 5, "24h": 60}[window]
    database_granularity = "hour" if bucket_minutes == 60 else "minute"
    database_bucket = func.date_trunc(
        database_granularity, Observation.occurred_at
    ).label("bucket")
    rows = db.execute(
        select(
            database_bucket,
            Observation.inspection_result,
            func.count(func.distinct(Observation.item_id)).label("count"),
        )
        .where(
            Observation.trust_status == "TRUSTED",
            Observation.inspection_result.in_(("no_defect", "defect_detected")),
            *_time_filters(Observation.occurred_at, boundary),
        )
        .group_by(database_bucket, Observation.inspection_result)
        .order_by(database_bucket)
    ).all()
    values: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        rounded = _floor_bucket(row.bucket, bucket_minutes)
        point = values.setdefault(rounded, {"bucket": rounded, "good": 0, "defect": 0})
        point["good" if row.inspection_result == "no_defect" else "defect"] += int(
            row.count
        )

    assert boundary is not None
    cursor = _floor_bucket(boundary, bucket_minutes)
    end = _floor_bucket(calculated_at, bucket_minutes)
    result: list[dict[str, Any]] = []
    while cursor <= end:
        result.append(values.get(cursor, {"bucket": cursor, "good": 0, "defect": 0}))
        cursor += timedelta(minutes=bucket_minutes)
    return result


def _recent_activity(
    db: Session, boundary: datetime | None
) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []
    observations = db.execute(
        select(
            Observation.occurred_at,
            Observation.item_id,
            Observation.inspection_result,
            OperationRun.run_reason,
        )
        .outerjoin(
            OperationRun,
            OperationRun.operation_run_id == Observation.operation_run_id,
        )
        .where(
            Observation.trust_status == "TRUSTED",
            Observation.inspection_result.in_(("no_defect", "defect_detected")),
            *_time_filters(Observation.occurred_at, boundary),
        )
        .order_by(Observation.occurred_at.desc())
        .limit(20)
    ).all()
    for row in observations:
        if row.inspection_result == "defect_detected":
            kind = "inspection_defect"
        elif row.run_reason == "rework":
            kind = "reinspection_good"
        else:
            kind = "inspection_good"
        activity.append({"at": row.occurred_at, "item_id": row.item_id, "kind": kind})

    decisions = db.execute(
        select(
            ControllerDecision.created_at,
            Nonconformance.item_id,
            ControllerDecision.verdict,
            ControllerDecision.disposition,
        )
        .join(
            Nonconformance,
            Nonconformance.id == ControllerDecision.nonconformance_id,
        )
        .where(*_time_filters(ControllerDecision.created_at, boundary))
        .order_by(ControllerDecision.created_at.desc())
        .limit(20)
    ).all()
    for row in decisions:
        if row.disposition == "RELEASED":
            kind = "release"
        elif row.verdict == "confirmed":
            kind = "ncr_confirmed"
        elif row.verdict == "rejected":
            kind = "ncr_rejected"
        else:
            continue
        activity.append({"at": row.created_at, "item_id": row.item_id, "kind": kind})

    rework_runs = db.execute(
        select(OperationRun.started_at, OperationRun.item_id)
        .where(
            OperationRun.run_reason == "rework",
            OperationRun.started_at.is_not(None),
            *_time_filters(OperationRun.started_at, boundary),
        )
        .order_by(OperationRun.started_at.desc())
        .limit(20)
    ).all()
    activity.extend(
        {"at": row.started_at, "item_id": row.item_id, "kind": "rework_started"}
        for row in rework_runs
    )

    warnings = db.execute(
        select(MachineEvent.occurred_at, MachineEvent.item_id, MachineEvent.equipment_id)
        .where(
            func.lower(MachineEvent.state).in_(WARNING_STATES),
            *_time_filters(MachineEvent.occurred_at, boundary),
        )
        .order_by(MachineEvent.occurred_at.desc())
        .limit(20)
    ).all()
    activity.extend(
        {
            "at": row.occurred_at,
            "item_id": row.item_id,
            "kind": "equipment_warning",
            "equipment_id": row.equipment_id,
        }
        for row in warnings
    )
    return sorted(activity, key=lambda row: row["at"], reverse=True)[:20]


def build_live_quality_snapshot(
    db: Session,
    *,
    window: LiveWindow,
    calculated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a read-only quality snapshot from existing projections."""
    calculated_at = calculated_at or datetime.now(timezone.utc)
    boundary = _boundary(window, calculated_at)
    observation_filters = _time_filters(Observation.occurred_at, boundary)

    inspected_items = (
        select(Observation.item_id)
        .where(*observation_filters)
        .distinct()
        .subquery()
    )
    trusted_items = (
        select(Observation.item_id)
        .where(Observation.trust_status == "TRUSTED", *observation_filters)
        .distinct()
        .subquery()
    )
    observed_item_ids = select(inspected_items.c.item_id)
    trusted_item_ids = select(trusted_items.c.item_id)

    inspected_total = _count(db, select(func.count()).select_from(inspected_items))
    trusted_good = _count(
        db,
        select(func.count(func.distinct(Observation.item_id))).where(
            Observation.trust_status == "TRUSTED",
            Observation.inspection_result == "no_defect",
            *observation_filters,
        ),
    )
    trusted_defect = _count(
        db,
        select(func.count(func.distinct(Observation.item_id))).where(
            Observation.trust_status == "TRUSTED",
            Observation.inspection_result == "defect_detected",
            *observation_filters,
        ),
    )
    assessable = _count(db, select(func.count()).select_from(trusted_items))
    confirmed_items = _count(
        db,
        select(func.count(func.distinct(Nonconformance.item_id))).where(
            Nonconformance.verdict == "confirmed",
            Nonconformance.item_id.in_(trusted_item_ids),
        ),
    )

    quality = {
        "confirmed_ncr": _count(
            db,
            select(func.count(Nonconformance.id)).where(
                Nonconformance.verdict == "confirmed",
                Nonconformance.item_id.in_(observed_item_ids),
            ),
        ),
        "pending_review": _count(
            db,
            select(func.count(Nonconformance.id)).where(
                Nonconformance.verdict == "pending_review",
                Nonconformance.item_id.in_(observed_item_ids),
            ),
        ),
        "rework_required": _count(
            db,
            select(func.count(func.distinct(Nonconformance.item_id))).where(
                Nonconformance.disposition == "REWORK_REQUIRED",
                Nonconformance.item_id.in_(observed_item_ids),
            ),
        ),
        "released": _count(
            db,
            select(func.count(func.distinct(Item.item_id))).where(
                Item.status == "RELEASED",
                Item.item_id.in_(observed_item_ids),
            ),
        ),
        "first_pass_yield": first_pass_yield(assessable, confirmed_items),
    }

    good_condition = (
        (Observation.trust_status == "TRUSTED")
        & (Observation.inspection_result == "no_defect")
    )
    defect_condition = (
        (Observation.trust_status == "TRUSTED")
        & (Observation.inspection_result == "defect_detected")
    )
    station_rows = db.execute(
        select(
            OperationRun.station_id,
            func.count(func.distinct(Observation.item_id)).label("inspected"),
            func.count(
                func.distinct(case((good_condition, Observation.item_id), else_=None))
            ).label("trusted_good"),
            func.count(
                func.distinct(case((defect_condition, Observation.item_id), else_=None))
            ).label("trusted_defect"),
        )
        .join(
            OperationRun,
            OperationRun.operation_run_id == Observation.operation_run_id,
        )
        .where(
            OperationRun.station_id.is_not(None),
            *observation_filters,
        )
        .group_by(OperationRun.station_id)
        .order_by(func.count(func.distinct(Observation.item_id)).desc(), OperationRun.station_id)
    ).all()
    stations = [
        {
            "station_id": row.station_id,
            "inspected": int(row.inspected),
            "trusted_good": int(row.trusted_good),
            "trusted_defect": int(row.trusted_defect),
            "defect_signal_rate": (
                int(row.trusted_defect) / int(row.inspected) if row.inspected else 0.0
            ),
        }
        for row in station_rows
    ]

    defect_rows = db.execute(
        select(
            DefectObservation.defect_type,
            func.count(DefectObservation.id).label("count"),
        )
        .join(Observation, Observation.id == DefectObservation.observation_id)
        .where(
            Observation.trust_status == "TRUSTED",
            Observation.inspection_result == "defect_detected",
            *observation_filters,
        )
        .group_by(DefectObservation.defect_type)
        .order_by(func.count(DefectObservation.id).desc(), DefectObservation.defect_type)
    ).all()

    warning_rows = db.execute(
        select(MachineEvent.equipment_id, func.count(MachineEvent.event_id).label("warnings"))
        .where(
            func.lower(MachineEvent.state).in_(WARNING_STATES),
            *_time_filters(MachineEvent.occurred_at, boundary),
        )
        .group_by(MachineEvent.equipment_id)
        .order_by(func.count(MachineEvent.event_id).desc(), MachineEvent.equipment_id)
        .limit(20)
    ).all()

    return {
        "calculated_at": calculated_at,
        "window": window,
        "inspections": {
            "total": inspected_total,
            "trusted_good": trusted_good,
            "trusted_defect": trusted_defect,
        },
        "quality": quality,
        "stations": stations,
        "defects_by_type": [
            {"defect_type": row.defect_type, "count": int(row.count)}
            for row in defect_rows
        ],
        "timeline": _timeline(
            db,
            window=window,
            boundary=boundary,
            calculated_at=calculated_at,
        ),
        "equipment_context": [
            {"equipment_id": row.equipment_id, "warnings": int(row.warnings)}
            for row in warning_rows
        ],
        "recent_activity": _recent_activity(db, boundary),
    }
