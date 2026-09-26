from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.quality.birth_window import EvidenceValue, calculate_birth_window
from backend.app.quality.occurrence import can_link_occurrence, defect_key
from backend.app.quality.rework import repeat_good_covers_nonconformance
from backend.app.quality.trust import (
    TrustPolicyValue,
    effective_scope_context,
    evaluate_trust,
    scope_covers,
    scope_coverage,
)


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


def test_rework_good_must_cover_original_defect_scope() -> None:
    broad_good = SimpleNamespace(
        inspection_result="no_defect",
        trust_status="TRUSTED",
        component_instance_id=None,
        inspection_scope={"defect_types": ["surface_crack"], "component_instance_ids": ["C1"]},
    )
    wrong_defect = SimpleNamespace(
        inspection_result="no_defect",
        trust_status="TRUSTED",
        component_instance_id="C1",
        inspection_scope={"defect_types": ["scratch_or_gouge"], "component_instance_ids": ["C1"]},
    )
    wrong_component = SimpleNamespace(
        inspection_result="no_defect",
        trust_status="TRUSTED",
        component_instance_id="C2",
        inspection_scope={"defect_types": ["surface_crack"], "component_instance_ids": ["C2"]},
    )
    assert repeat_good_covers_nonconformance(
        broad_good, defect_type="surface_crack", component_instance_id="C1"
    )
    assert not repeat_good_covers_nonconformance(
        wrong_defect, defect_type="surface_crack", component_instance_id="C1"
    )
    assert not repeat_good_covers_nonconformance(
        wrong_component, defect_type="surface_crack", component_instance_id="C1"
    )


def test_item_level_ncr_is_not_cleared_by_component_only_good() -> None:
    component_only = SimpleNamespace(
        inspection_result="no_defect",
        trust_status="TRUSTED",
        component_instance_id="C1",
        inspection_scope={"defect_types": ["surface_crack"], "component_instance_ids": ["C1"]},
    )
    assert not repeat_good_covers_nonconformance(
        component_only, defect_type="surface_crack", component_instance_id=None
    )


def test_left_open_birth_window_records_missing_prior_trusted_inspection() -> None:
    defect = {
        "event_id": "D1",
        "occurred_at": NOW + timedelta(minutes=30),
        "defect_type": "surface_crack",
        "component_instance_id": "C1",
    }
    result = calculate_birth_window(
        defect_observation=defect,
        observations=[],
        operations=[],
        machine_events=[],
        operator_actions=[],
    )
    assert result.status == "LEFT_OPEN"
    assert "NO_PREVIOUS_TRUSTED_INSPECTION" in {
        value.evidence_type for value in result.evidence
    }


def test_item_level_scope_requires_item_wide_component_coverage() -> None:
    restricted = {
        "defect_types": ["surface_crack"],
        "component_instance_ids": ["C1"],
    }
    assert not scope_covers(restricted, "surface_crack", None)
    assert scope_covers(
        {"defect_types": ["surface_crack"], "component_instance_ids": ["*"]},
        "surface_crack",
        None,
    )


def test_empty_component_scope_is_item_level_fallback() -> None:
    scope = {"defect_types": ["surface_crack"], "components": []}
    assert scope_covers(scope, "surface_crack", None)


def _configured_scope(**coverage: str) -> dict:
    return {
        "coverage": {"COMP-HOUSING-*": coverage},
        "default_coverage": "NONE",
    }


def test_full_good_is_eligible_birth_window_boundary() -> None:
    good = {
        "event_id": "FULL-GOOD",
        "occurred_at": NOW,
        "inspection_result": "no_defect",
        "trust_status": "TRUSTED",
        "inspection_scope": effective_scope_context(
            {"components": ["COMP-HOUSING-1"], "defect_types": ["scratch_or_gouge"]},
            _configured_scope(scratch_or_gouge="FULL"),
        ),
        "component_instance_id": "COMP-HOUSING-1",
        "control_point_id": "CP-POST-MILL",
    }
    result = calculate_birth_window(
        defect_observation={
            "event_id": "DEFECT",
            "occurred_at": NOW + timedelta(minutes=1),
            "defect_type": "scratch_or_gouge",
            "component_instance_id": "COMP-HOUSING-1",
        },
        observations=[good],
        operations=[],
        machine_events=[],
        operator_actions=[],
    )
    assert result.status == "BOUNDED"
    assert result.left_boundary_at == NOW


def test_partial_good_stays_trusted_but_is_not_boundary() -> None:
    scope = effective_scope_context(
        {"components": ["COMP-HOUSING-1"], "defect_types": ["surface_crack"]},
        _configured_scope(surface_crack="PARTIAL"),
    )
    good = {
        "event_id": "PARTIAL-GOOD",
        "occurred_at": NOW,
        "inspection_result": "no_defect",
        "trust_status": "TRUSTED",
        "inspection_scope": scope,
        "component_instance_id": "COMP-HOUSING-1",
    }
    result = calculate_birth_window(
        defect_observation={
            "event_id": "DEFECT",
            "occurred_at": NOW + timedelta(minutes=1),
            "defect_type": "surface_crack",
            "component_instance_id": "COMP-HOUSING-1",
        },
        observations=[good],
        operations=[],
        machine_events=[],
        operator_actions=[],
    )
    assert good["trust_status"] == "TRUSTED"
    assert scope_coverage(scope, "surface_crack", "COMP-HOUSING-1") == "PARTIAL"
    assert result.status == "LEFT_OPEN"


def test_none_coverage_is_irrelevant() -> None:
    scope = effective_scope_context(
        {"components": ["COMP-HOUSING-1"], "defect_types": ["missing_component"]},
        _configured_scope(missing_component="NONE"),
    )
    assert scope_coverage(scope, "missing_component", "COMP-HOUSING-1") == "NONE"
    assert not scope_covers(scope, "missing_component", "COMP-HOUSING-1")


def test_one_inspection_can_be_full_for_scratch_and_partial_for_crack() -> None:
    scope = effective_scope_context(
        {
            "components": ["COMP-HOUSING-1"],
            "defect_types": ["surface_crack", "scratch_or_gouge"],
        },
        _configured_scope(surface_crack="PARTIAL", scratch_or_gouge="FULL"),
    )
    assert scope_coverage(scope, "scratch_or_gouge", "COMP-HOUSING-1") == "FULL"
    assert scope_coverage(scope, "surface_crack", "COMP-HOUSING-1") == "PARTIAL"


def test_target_only_good_closes_only_linked_defect_key() -> None:
    scope = effective_scope_context(
        {
            "components": ["COMP-HOUSING-1"],
            "defect_types": ["surface_crack", "scratch_or_gouge"],
        },
        {
            "mode": "TARGET_ONLY",
            "coverage": {"*": {"*": "TARGET_ONLY"}},
        },
        {
            "component_instance_ids": ["COMP-HOUSING-1"],
            "defect_types": ["surface_crack"],
        },
    )
    observation = SimpleNamespace(
        inspection_result="no_defect",
        trust_status="TRUSTED",
        component_instance_id="COMP-HOUSING-1",
        inspection_scope=scope,
    )
    assert scope_coverage(scope, "surface_crack", "COMP-HOUSING-1") == "TARGET_ONLY"
    assert not scope_covers(scope, "surface_crack", "COMP-HOUSING-1")
    assert repeat_good_covers_nonconformance(
        observation, defect_type="surface_crack", component_instance_id="COMP-HOUSING-1"
    )
    assert not repeat_good_covers_nonconformance(
        observation, defect_type="scratch_or_gouge", component_instance_id="COMP-HOUSING-1"
    )


def test_component_none_uses_item_level_fallback_in_effective_scope() -> None:
    scope = effective_scope_context(
        {"components": [], "defect_types": ["surface_crack"]},
        {
            "coverage": {"COMP-HOUSING-*": {"surface_crack": "FULL"}},
            "item_level_fallback": "COMP-HOUSING-*",
        },
    )
    assert scope_coverage(scope, "surface_crack", None) == "FULL"
