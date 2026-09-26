from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Literal


InspectionCoverage = Literal["FULL", "PARTIAL", "NONE", "TARGET_ONLY"]
_COVERAGE_RANK: dict[InspectionCoverage, int] = {
    "NONE": 0,
    "PARTIAL": 1,
    "FULL": 2,
    # TARGET_ONLY is a mode, not broader coverage than FULL.
    "TARGET_ONLY": 2,
}


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


def _legacy_scope_coverage(
    inspection_scope: dict[str, Any] | list[Any] | None,
    defect_type: str,
    component_instance_id: str | None,
) -> InspectionCoverage:
    if inspection_scope is None:
        return "FULL"
    if isinstance(inspection_scope, list):
        return "FULL" if defect_type in inspection_scope or "*" in inspection_scope else "NONE"
    defects = inspection_scope.get("defect_types", ["*"])
    components = inspection_scope.get(
        "component_instance_ids", inspection_scope.get("components", ["*"])
    )
    defect_ok = "*" in defects or defect_type in defects
    if component_instance_id is None:
        # In degraded item-level mode an empty component list means that no
        # component structure is available, so the inspection applies at item level.
        # An explicit non-empty component list remains narrower than item level.
        component_ok = not components or "*" in components
    else:
        component_ok = "*" in components or component_instance_id in components
    return "FULL" if defect_ok and component_ok else "NONE"


def _matrix_scope_coverage(
    inspection_scope: dict[str, Any],
    defect_type: str,
    component_instance_id: str | None,
) -> InspectionCoverage:
    matrix = inspection_scope.get("coverage")
    if not isinstance(matrix, dict):
        return _legacy_scope_coverage(inspection_scope, defect_type, component_instance_id)

    component_key = component_instance_id or "ITEM"
    matches: list[tuple[int, str, Any]] = []
    fallback_selector = inspection_scope.get("item_level_fallback")
    if (
        component_instance_id is None
        and isinstance(fallback_selector, str)
        and fallback_selector in matrix
    ):
        matches.append(
            (
                len(fallback_selector.replace("*", "")),
                fallback_selector,
                matrix[fallback_selector],
            )
        )
    for selector, defect_map in matrix.items():
        if selector == "*" or fnmatchcase(component_key, selector):
            specificity = 0 if selector == "*" else len(selector.replace("*", ""))
            matches.append((specificity, selector, defect_map))
    for _, _, defect_map in sorted(matches, reverse=True):
        if isinstance(defect_map, str):
            value = defect_map
        elif isinstance(defect_map, dict):
            value = defect_map.get(defect_type, defect_map.get("*"))
        else:
            continue
        if value in _COVERAGE_RANK:
            return value
    default = inspection_scope.get("default_coverage", "NONE")
    return default if default in _COVERAGE_RANK else "NONE"


def _layer_coverage(
    inspection_scope: dict[str, Any] | list[Any] | None,
    defect_type: str,
    component_instance_id: str | None,
) -> InspectionCoverage:
    if isinstance(inspection_scope, dict) and "coverage" in inspection_scope:
        return _matrix_scope_coverage(inspection_scope, defect_type, component_instance_id)
    return _legacy_scope_coverage(inspection_scope, defect_type, component_instance_id)


def effective_scope_context(
    reported_scope: dict[str, Any] | list[Any] | None,
    configured_scope: dict[str, Any] | list[Any] | None,
    targeted_scope: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Keep source and route scopes distinct in the rebuildable projection."""
    return {
        "reported_scope": reported_scope,
        "configured_scope": configured_scope,
        "targeted_scope": targeted_scope,
    }


def reported_scope(
    inspection_scope: dict[str, Any] | list[Any] | None,
) -> dict[str, Any] | list[Any] | None:
    if isinstance(inspection_scope, dict) and "reported_scope" in inspection_scope:
        return inspection_scope.get("reported_scope")
    return inspection_scope


def scope_coverage(
    inspection_scope: dict[str, Any] | list[Any] | None,
    defect_type: str,
    component_instance_id: str | None,
) -> InspectionCoverage:
    """Return effective route/report/target coverage for one defect key.

    A projection context is the intersection of what the control point can see,
    what the source says it inspected, and (for rework) the NCR target. Legacy
    scopes remain valid and mean FULL for explicitly covered keys.
    """
    if isinstance(inspection_scope, dict) and "reported_scope" in inspection_scope:
        reported = _layer_coverage(
            inspection_scope.get("reported_scope"), defect_type, component_instance_id
        )
        configured_scope = inspection_scope.get("configured_scope")
        configured = _layer_coverage(configured_scope, defect_type, component_instance_id)
        targeted_scope = inspection_scope.get("targeted_scope")
        target_mode = (
            isinstance(configured_scope, dict)
            and configured_scope.get("mode") == "TARGET_ONLY"
        ) or configured == "TARGET_ONLY"
        if target_mode:
            targeted = _layer_coverage(targeted_scope, defect_type, component_instance_id)
            if reported == "NONE" or targeted == "NONE":
                return "NONE"
            if "PARTIAL" in {reported, configured, targeted}:
                return "PARTIAL"
            return "TARGET_ONLY"
        if reported == "NONE" or configured == "NONE":
            return "NONE"
        if reported == "PARTIAL" or configured == "PARTIAL":
            return "PARTIAL"
        return "FULL"
    return _layer_coverage(inspection_scope, defect_type, component_instance_id)


def scope_covers(
    inspection_scope: dict[str, Any] | list[Any] | None,
    defect_type: str,
    component_instance_id: str | None,
) -> bool:
    """Compatibility helper: only FULL coverage can form a GOOD boundary."""
    return scope_coverage(inspection_scope, defect_type, component_instance_id) == "FULL"
