from __future__ import annotations

from typing import Any

from backend.app.quality.trust import scope_coverage


ACTIVITY_ORDER = {
    "item_registered": 10,
    "operation_started": 20,
    "operation_finished": 30,
    "inspection_result": 40,
    "nonconformance_opened": 50,
    "controller_decision": 60,
    "extra_inspection_requested": 60,
    "rework_started": 70,
    "rework_finished": 80,
    "rework_verification": 90,
    "final_disposition": 100,
    "control_device_invalidated": 110,
}


def _activity_timestamp(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_business_activity(
    *,
    raw_events: list[Any],
    observations: list[Any],
    nonconformances: list[Any],
    decisions: list[Any],
    operation_runs: list[Any],
    invalidations: list[Any],
) -> list[dict]:
    """Build a UI read-model exclusively from persisted facts."""
    activity: list[dict] = []
    raw_by_event = {row.event_id: row for row in raw_events}
    run_by_id = {row.operation_run_id: row for row in operation_runs}
    ncr_by_id = {row.id: row for row in nonconformances}

    for raw in raw_events:
        activity_type = None
        details: dict = {}
        if raw.event_type == "item.registered":
            activity_type = "item_registered"
        elif raw.event_type in {"operation.started", "operation.finished"}:
            run = run_by_id.get(raw.operation_run_id)
            rework = bool(run and run.run_reason == "rework")
            activity_type = (
                "rework_started"
                if rework and raw.event_type == "operation.started"
                else "rework_finished"
                if rework
                else "operation_started"
                if raw.event_type == "operation.started"
                else "operation_finished"
            )
            if run:
                details = {
                    "operation_run_id": run.operation_run_id,
                    "operation_id": run.operation_id,
                    "completion_status": run.completion_status,
                    "rework_for_nonconformance_id": run.rework_for_nonconformance_id,
                }
        if activity_type:
            activity.append(
                {
                    "type": activity_type,
                    "occurred_at": raw.occurred_at,
                    "event_id": raw.event_id,
                    "source_id": raw.source_id,
                    "nonconformance_id": details.get("rework_for_nonconformance_id"),
                    "details": details,
                }
            )

    defect_keys = {
        (row.defect_type, row.component_instance_id) for row in nonconformances
    }
    for observation in observations:
        raw = raw_by_event.get(observation.event_id)
        run = run_by_id.get(observation.operation_run_id)
        is_rework_check = bool(run and run.run_reason == "rework")
        coverage = [
            {
                "defect_type": defect_type,
                "component_instance_id": component,
                "coverage": scope_coverage(
                    observation.inspection_scope, defect_type, component
                ),
            }
            for defect_type, component in sorted(
                defect_keys, key=lambda value: (value[0], value[1] or "")
            )
        ]
        activity.append(
            {
                "type": "inspection_result",
                "occurred_at": observation.occurred_at,
                "event_id": observation.event_id,
                "source_id": raw.source_id if raw else None,
                "nonconformance_id": (
                    run.rework_for_nonconformance_id if is_rework_check else None
                ),
                "details": {
                    "inspection_result": observation.inspection_result,
                    "operation_run_id": observation.operation_run_id,
                    "is_rework_check": is_rework_check,
                    "control_point_id": observation.control_point_id,
                    "control_device_id": observation.control_device_id,
                    "trust_status": observation.trust_status,
                    "trust_reasons": observation.trust_reasons,
                    "coverage": coverage,
                },
            }
        )

    for ncr in nonconformances:
        activity.append(
            {
                "type": "nonconformance_opened",
                "occurred_at": ncr.opened_at,
                "event_id": None,
                "source_id": None,
                "nonconformance_id": ncr.id,
                "details": {
                    "defect_type": ncr.defect_type,
                    "component_instance_id": ncr.component_instance_id,
                },
            }
        )

    for decision in decisions:
        ncr = ncr_by_id.get(decision.nonconformance_id)
        is_verification = bool(ncr and ncr.verification_decision_id == decision.id)
        if is_verification:
            activity_type = "rework_verification"
        elif decision.verdict == "needs_extra_check":
            activity_type = "extra_inspection_requested"
        else:
            activity_type = "controller_decision"
        activity.append(
            {
                "type": activity_type,
                "occurred_at": decision.created_at,
                "event_id": None,
                "source_id": None,
                "nonconformance_id": decision.nonconformance_id,
                "details": {
                    "decision_id": decision.id,
                    "user_id": decision.user_id,
                    "verdict": decision.verdict,
                    "disposition": decision.disposition,
                    "containment": decision.containment,
                    "reason": decision.reason,
                    "analysis_version": decision.analysis_version,
                    "verification_status": ncr.verification_status if is_verification else None,
                },
            }
        )
        if decision.disposition in {"RELEASED", "USE_AS_IS", "SCRAPPED"}:
            activity.append(
                {
                    "type": "final_disposition",
                    "occurred_at": decision.created_at,
                    "event_id": None,
                    "source_id": None,
                    "nonconformance_id": decision.nonconformance_id,
                    "details": {
                        "decision_id": decision.id,
                        "disposition": decision.disposition,
                    },
                }
            )

    for invalidation in invalidations:
        affected_observations = [
            row
            for row in observations
            if row.control_device_id == invalidation.device_id
            and invalidation.affected_from <= row.occurred_at <= invalidation.affected_to
        ]
        if not affected_observations:
            continue
        activity.append(
            {
                "type": "control_device_invalidated",
                "occurred_at": invalidation.created_at,
                "event_id": invalidation.source_event_id,
                "source_id": None,
                "nonconformance_id": None,
                "details": {
                    "device_id": invalidation.device_id,
                    "reason": invalidation.reason,
                    "affected_from": invalidation.affected_from,
                    "affected_to": invalidation.affected_to,
                },
            }
        )

    activity.sort(
        key=lambda row: (
            _activity_timestamp(row.get("occurred_at")),
            ACTIVITY_ORDER.get(str(row.get("type") or ""), 999),
            str(row.get("event_id") or row.get("nonconformance_id") or ""),
        )
    )
    return activity
