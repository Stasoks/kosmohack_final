from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustPolicyValue:
    allowed_observation_quality: frozenset[str] = frozenset({"good"})
    confidence_required: bool = False
    min_confidence: float | None = None
    requires_valid_device: bool = False
    media_required: bool = False


@dataclass(frozen=True)
class TrustResult:
    status: str
    reasons: tuple[str, ...]


def evaluate_trust(
    observation: dict[str, Any],
    policy: TrustPolicyValue,
    *,
    device_valid: bool = True,
    invalidated: bool = False,
    conflicted: bool = False,
) -> TrustResult:
    if observation.get("inspection_result") == "impossible_to_assess":
        return TrustResult("UNASSESSABLE", ("INSPECTION_IMPOSSIBLE_TO_ASSESS",))
    if invalidated:
        return TrustResult("INVALIDATED", ("CONTROL_DEVICE_INVALIDATED",))
    if conflicted:
        return TrustResult("CONFLICTED", ("EQUIVALENT_OBSERVATIONS_CONFLICT",))

    reasons: list[str] = []
    if observation.get("observation_quality") not in policy.allowed_observation_quality:
        reasons.append("OBSERVATION_QUALITY_NOT_ALLOWED")
    confidence = observation.get("confidence")
    if policy.confidence_required and confidence is None:
        reasons.append("CONFIDENCE_REQUIRED")
    if policy.min_confidence is not None and (
        confidence is None or float(confidence) < policy.min_confidence
    ):
        reasons.append("CONFIDENCE_BELOW_THRESHOLD")
    if policy.requires_valid_device and not device_valid:
        reasons.append("DEVICE_VALIDITY_NOT_CONFIRMED")
    if policy.media_required and not observation.get("evidence_refs"):
        reasons.append("MEDIA_REQUIRED")
    if reasons:
        return TrustResult("UNTRUSTED", tuple(reasons))
    return TrustResult("TRUSTED", ())


def scope_covers(
    inspection_scope: dict[str, Any] | list[Any] | None,
    defect_type: str,
    component_instance_id: str | None,
) -> bool:
    if inspection_scope is None:
        return True
    if isinstance(inspection_scope, list):
        return defect_type in inspection_scope or "*" in inspection_scope
    defects = inspection_scope.get("defect_types", ["*"])
    components = inspection_scope.get("component_instance_ids", inspection_scope.get("components", ["*"]))
    defect_ok = "*" in defects or defect_type in defects
    component_ok = (
        component_instance_id is None
        or "*" in components
        or component_instance_id in components
    )
    return defect_ok and component_ok
