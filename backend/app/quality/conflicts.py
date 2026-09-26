from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from itertools import combinations
from typing import Any

from backend.app.quality.trust import reported_scope, scope_coverage


FALLBACK_SESSION_BUCKET_SECONDS = 60


def source_priority(
    observation: Mapping[str, Any],
    priorities: Mapping[str, int] | None = None,
) -> int:
    """Resolve source priority; all current P0 sources intentionally tie at zero."""
    explicit = observation.get("source_priority")
    if explicit is not None:
        return int(explicit)
    return int((priorities or {}).get(str(observation.get("source_id") or ""), 0))


def logical_session_key(observation: Mapping[str, Any]) -> tuple[Any, ...]:
    capture_session_id = observation.get("capture_session_id")
    if capture_session_id:
        return ("capture", capture_session_id)
    occurred_at = observation.get("occurred_at")
    if not isinstance(occurred_at, datetime):
        raise ValueError("occurred_at is required for conflict fallback sessions")
    return (
        "fallback",
        observation.get("item_id"),
        observation.get("control_point_id"),
        observation.get("operation_run_id"),
        int(occurred_at.timestamp() // FALLBACK_SESSION_BUCKET_SECONDS),
    )


def _scope_values(observation: Mapping[str, Any], key: str) -> set[str]:
    scope = reported_scope(observation.get("inspection_scope"))
    if isinstance(scope, list):
        return {str(value) for value in scope} if key == "defect_types" else {"*"}
    if not isinstance(scope, dict):
        return {"*"}
    if key == "component_instance_ids":
        values = scope.get(key, scope.get("components", ["*"]))
        # Empty components is the documented item-level fallback.
        return {"*"} if not values else {str(value) for value in values}
    values = scope.get(key, ["*"])
    return {str(value) for value in values} if values else {"*"}


def _defect_claims(observation: Mapping[str, Any]) -> set[str]:
    if observation.get("inspection_result") == "defect_detected":
        claims = {
            str(defect["defect_type"])
            for defect in observation.get("defects", [])
            if defect.get("defect_type")
            and scope_coverage(
                observation.get("inspection_scope"),
                str(defect["defect_type"]),
                defect.get("component_instance_id")
                or observation.get("component_instance_id"),
            )
            != "NONE"
        }
        if claims:
            return claims
        return set()
    claims = _scope_values(observation, "defect_types")
    component_claims = _scope_values(observation, "component_instance_ids")
    return {
        defect_type
        for defect_type in claims
        if defect_type == "*"
        or any(
            scope_coverage(
                observation.get("inspection_scope"),
                defect_type,
                None if component == "*" else component,
            )
            != "NONE"
            for component in component_claims
        )
    }


def _component_claims(observation: Mapping[str, Any]) -> set[str]:
    if observation.get("inspection_result") == "defect_detected":
        claims = {
            str(defect.get("component_instance_id") or observation.get("component_instance_id"))
            for defect in observation.get("defects", [])
            if defect.get("component_instance_id") or observation.get("component_instance_id")
        }
        if claims:
            return claims
    component = observation.get("component_instance_id")
    if component:
        return {str(component)}
    return _scope_values(observation, "component_instance_ids")


def _overlaps(left: set[str], right: set[str]) -> bool:
    return "*" in left or "*" in right or bool(left & right)


def observations_conflict(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    priorities: Mapping[str, int] | None = None,
) -> bool:
    results = {left.get("inspection_result"), right.get("inspection_result")}
    if results != {"no_defect", "defect_detected"}:
        return False
    if left.get("item_id") != right.get("item_id"):
        return False
    if left.get("control_point_id") != right.get("control_point_id"):
        return False
    if logical_session_key(left) != logical_session_key(right):
        return False
    if source_priority(left, priorities) != source_priority(right, priorities):
        return False
    return _overlaps(_component_claims(left), _component_claims(right)) and _overlaps(
        _defect_claims(left), _defect_claims(right)
    )


def conflicting_event_ids(
    observations: list[dict[str, Any]],
    *,
    priorities: Mapping[str, int] | None = None,
) -> set[str]:
    result: set[str] = set()
    for left, right in combinations(observations, 2):
        if observations_conflict(left, right, priorities=priorities):
            if left.get("event_id"):
                result.add(str(left["event_id"]))
            if right.get("event_id"):
                result.add(str(right["event_id"]))
    return result
