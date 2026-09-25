from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.quality.birth_window import EvidenceValue, calculate_birth_window
from backend.app.quality.occurrence import can_link_occurrence, defect_key
from backend.app.quality.trust import TrustPolicyValue, evaluate_trust, scope_covers


NOW = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def test_impossible_to_assess_is_unassessable() -> None:
    result = evaluate_trust(
        {"inspection_result": "impossible_to_assess", "observation_quality": "good"},
        TrustPolicyValue(),
    )
    assert result.status == "UNASSESSABLE"


def test_poor_observation_cannot_be_trusted_good() -> None:
    result = evaluate_trust(
        {"inspection_result": "no_defect", "observation_quality": "poor"},
        TrustPolicyValue(),
    )
    assert result.status == "UNTRUSTED"
    assert "OBSERVATION_QUALITY_NOT_ALLOWED" in result.reasons


def test_confidence_policy_is_explicit() -> None:
    policy = TrustPolicyValue(confidence_required=True, min_confidence=0.9)
    assert evaluate_trust(
        {"inspection_result": "defect_detected", "observation_quality": "good"}, policy
    ).status == "UNTRUSTED"
    assert evaluate_trust(
        {
            "inspection_result": "defect_detected",
            "observation_quality": "good",
            "confidence": 0.95,
        },
        policy,
    ).status == "TRUSTED"


def test_birth_window_is_bounded_by_last_capable_good() -> None:
    observations = [
        {
            "event_id": "GOOD-OLD",
            "occurred_at": NOW,
            "inspection_result": "no_defect",
            "trust_status": "TRUSTED",
            "inspection_scope": {"defect_types": ["burr"], "component_instance_ids": ["C1"]},
            "component_instance_id": "C1",
            "control_point_id": "CP1",
        },
        {
            "event_id": "POOR",
            "occurred_at": NOW + timedelta(minutes=5),
            "inspection_result": "no_defect",
            "trust_status": "UNTRUSTED",
            "trust_reasons": ["OBSERVATION_QUALITY_NOT_ALLOWED"],
            "inspection_scope": None,
            "component_instance_id": "C1",
        },
    ]
    defect = {
        "event_id": "DEFECT",
        "occurred_at": NOW + timedelta(minutes=20),
        "defect_type": "burr",
        "component_instance_id": "C1",
    }
    result = calculate_birth_window(
        defect_observation=defect,
        observations=observations,
        operations=[
            {
                "operation_run_id": "R1",
                "operation_id": "OP1",
                "finished_at": NOW + timedelta(minutes=15),
            }
        ],
        machine_events=[
            {
                "event_id": "M1",
                "occurred_at": NOW + timedelta(minutes=10),
                "equipment_id": "EQ1",
                "state": "warning",
            }
        ],
        operator_actions=[],
        limitations=[EvidenceValue("MISSING_CHECK", "LIMITATION", None, None)],
    )
    assert result.status == "BOUNDED"
    assert result.left_boundary_at == NOW
    types = {value.evidence_type for value in result.evidence}
    assert {"LAST_TRUSTED_GOOD", "FIRST_TRUSTED_DEFECT", "OPERATION_IN_WINDOW", "MACHINE_WARNING", "POOR_OBSERVATION", "MISSING_CHECK"} <= types


def test_scope_must_cover_defect_and_component() -> None:
    assert scope_covers({"defect_types": ["burr"], "component_instance_ids": ["C1"]}, "burr", "C1")
    assert not scope_covers({"defect_types": ["scratch"]}, "burr", "C1")


def test_defect_occurrence_linking_rule() -> None:
    occurrence = SimpleNamespace(
        status="OPEN", item_id="ITEM-1", defect_type="burr", component_instance_id="C1"
    )
    assert can_link_occurrence(
        occurrence, item_id="ITEM-1", defect_type="burr", component_instance_id="C1"
    )
    occurrence.status = "CLOSED"
    assert not can_link_occurrence(
        occurrence, item_id="ITEM-1", defect_type="burr", component_instance_id="C1"
    )
    assert defect_key("ITEM-1", "scratch", None) == ("ITEM-1", "scratch")
