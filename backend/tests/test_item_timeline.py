from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from backend.app.read_models.timeline import build_business_activity


def test_business_activity_combines_events_decisions_rework_and_invalidation() -> None:
    now = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    ncr_id = uuid.uuid4()
    verification_id = uuid.uuid4()
    raw_events = [
        SimpleNamespace(
            event_id="REGISTER-1",
            event_type="item.registered",
            occurred_at=now,
            source_id="MES-1",
            operation_run_id=None,
        ),
        SimpleNamespace(
            event_id="REWORK-START",
            event_type="operation.started",
            occurred_at=now + timedelta(minutes=10),
            source_id="MES-1",
            operation_run_id="RUN-R2",
        ),
        SimpleNamespace(
            event_id="REWORK-END",
            event_type="operation.finished",
            occurred_at=now + timedelta(minutes=20),
            source_id="MES-1",
            operation_run_id="RUN-R2",
        ),
        SimpleNamespace(
            event_id="INSPECTION-1",
            event_type="inspection.result",
            occurred_at=now + timedelta(minutes=22),
            source_id="VISION-1",
            operation_run_id="RUN-R2",
        ),
    ]
    observation = SimpleNamespace(
        event_id="INSPECTION-1",
        operation_run_id="RUN-R2",
        occurred_at=now + timedelta(minutes=22),
        inspection_result="no_defect",
        control_point_id="CP-1",
        control_device_id="CAM-1",
        trust_status="INVALIDATED",
        trust_reasons=["DEVICE_INVALIDATED"],
        inspection_scope={"components": ["COMP-1"], "defect_types": ["surface_crack"]},
    )
    ncr = SimpleNamespace(
        id=ncr_id,
        defect_type="surface_crack",
        component_instance_id="COMP-1",
        opened_at=now + timedelta(minutes=5),
        verification_decision_id=verification_id,
        verification_status="PASSED",
    )
    decision = SimpleNamespace(
        id=verification_id,
        nonconformance_id=ncr_id,
        user_id=uuid.uuid4(),
        verdict="confirmed",
        disposition="RELEASED",
        containment="NONE",
        reason="Repeat inspection passed",
        analysis_version=2,
        created_at=now + timedelta(minutes=25),
    )
    run = SimpleNamespace(
        operation_run_id="RUN-R2",
        operation_id="OP-REWORK",
        completion_status="completed",
        run_reason="rework",
        rework_for_nonconformance_id=ncr_id,
    )
    invalidation = SimpleNamespace(
        source_event_id="INVALIDATE-1",
        device_id="CAM-1",
        affected_from=now,
        affected_to=now + timedelta(hours=1),
        reason="Calibration failed",
        created_at=now + timedelta(minutes=30),
    )

    activity = build_business_activity(
        raw_events=raw_events,
        observations=[observation],
        nonconformances=[ncr],
        decisions=[decision],
        operation_runs=[run],
        invalidations=[invalidation],
    )

    activity_types = [row["type"] for row in activity]
    assert activity_types == [
        "item_registered",
        "nonconformance_opened",
        "rework_started",
        "rework_finished",
        "inspection_result",
        "rework_verification",
        "final_disposition",
        "control_device_invalidated",
    ]
    inspection = next(row for row in activity if row["type"] == "inspection_result")
    assert inspection["details"]["coverage"] == [
        {
            "defect_type": "surface_crack",
            "component_instance_id": "COMP-1",
            "coverage": "FULL",
        }
    ]
    assert inspection["details"]["trust_status"] == "INVALIDATED"
