from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.quality.conflicts import observations_conflict


NOW = datetime(2026, 9, 25, 10, 0, 10, tzinfo=timezone.utc)


def _good(**overrides):
    value = {
        "event_id": "GOOD",
        "item_id": "ITEM-1",
        "control_point_id": "CP-1",
        "operation_run_id": "RUN-1",
        "capture_session_id": "CAP-1",
        "occurred_at": NOW,
        "inspection_result": "no_defect",
        "inspection_scope": {
            "component_instance_ids": ["C1"],
            "defect_types": ["surface_crack"],
        },
        "source_id": "VISION-01",
    }
    value.update(overrides)
    return value


def _defect(**overrides):
    value = {
        "event_id": "DEFECT",
        "item_id": "ITEM-1",
        "control_point_id": "CP-1",
        "operation_run_id": "RUN-1",
        "capture_session_id": "CAP-1",
        "occurred_at": NOW + timedelta(seconds=1),
        "inspection_result": "defect_detected",
        "inspection_scope": {
            "component_instance_ids": ["C1"],
            "defect_types": ["surface_crack"],
        },
        "defects": [
            {"defect_type": "surface_crack", "component_instance_id": "C1"}
        ],
        "source_id": "OPERATOR-01",
    }
    value.update(overrides)
    return value


def test_same_session_overlapping_claims_conflict() -> None:
    assert observations_conflict(_good(), _defect())


def test_different_defect_types_do_not_conflict() -> None:
    assert not observations_conflict(
        _good(),
        _defect(
            defects=[{"defect_type": "scratch_or_gouge", "component_instance_id": "C1"}],
            inspection_scope={
                "component_instance_ids": ["C1"],
                "defect_types": ["scratch_or_gouge"],
            },
        ),
    )


def test_different_component_scopes_do_not_conflict() -> None:
    assert not observations_conflict(
        _good(),
        _defect(
            defects=[{"defect_type": "surface_crack", "component_instance_id": "C2"}],
            inspection_scope={
                "component_instance_ids": ["C2"],
                "defect_types": ["surface_crack"],
            },
        ),
    )


def test_different_capture_sessions_do_not_conflict() -> None:
    assert not observations_conflict(_good(), _defect(capture_session_id="CAP-2"))


def test_different_source_priorities_do_not_conflict() -> None:
    assert not observations_conflict(
        _good(source_priority=10), _defect(source_priority=20)
    )


def test_fallback_session_uses_sixty_second_bucket_and_operation() -> None:
    good = _good(capture_session_id=None)
    same_bucket = _defect(capture_session_id=None, occurred_at=NOW + timedelta(seconds=20))
    next_bucket = _defect(capture_session_id=None, occurred_at=NOW + timedelta(seconds=60))
    other_run = _defect(
        capture_session_id=None,
        occurred_at=NOW + timedelta(seconds=20),
        operation_run_id="RUN-2",
    )
    assert observations_conflict(good, same_bucket)
    assert not observations_conflict(good, next_bucket)
    assert not observations_conflict(good, other_run)
