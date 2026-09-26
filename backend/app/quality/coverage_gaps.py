from __future__ import annotations

from typing import Any, Iterable

from backend.app.quality.trust import scope_coverage


COVERAGE_VALUES = {"FULL", "PARTIAL", "NONE", "TARGET_ONLY"}


def _step_value(step: Any, name: str) -> Any:
    if isinstance(step, dict):
        return step.get(name)
    return getattr(step, name, None)


def _valid_scope(scope: Any) -> bool:
    if scope is None:
        return True
    if isinstance(scope, list):
        return all(isinstance(value, str) for value in scope)
    if not isinstance(scope, dict):
        return False
    if "coverage" in scope:
        matrix = scope.get("coverage")
        if not isinstance(matrix, dict):
            return False
        for selector, defect_map in matrix.items():
            if not isinstance(selector, str):
                return False
            if isinstance(defect_map, str):
                if defect_map not in COVERAGE_VALUES:
                    return False
            elif isinstance(defect_map, dict):
                if not all(
                    isinstance(defect, str) and value in COVERAGE_VALUES
                    for defect, value in defect_map.items()
                ):
                    return False
            else:
                return False
        return scope.get("default_coverage", "NONE") in COVERAGE_VALUES
    for key in ("defect_types", "component_instance_ids", "components"):
        if key in scope and not (
            isinstance(scope[key], list)
            and all(isinstance(value, str) for value in scope[key])
        ):
            return False
    return True


def _scope_keys(scope: Any) -> tuple[set[str], set[str]]:
    if scope is None:
        return {"*"}, {"*"}
    if isinstance(scope, list):
        return {"*"}, {str(value) for value in scope} or {"*"}
    matrix = scope.get("coverage")
    if isinstance(matrix, dict):
        selectors = {str(selector) for selector in matrix} or {"*"}
        defects: set[str] = set()
        for defect_map in matrix.values():
            if isinstance(defect_map, dict):
                defects.update(str(defect) for defect in defect_map)
            elif isinstance(defect_map, str):
                defects.add("*")
        return selectors, defects or {"*"}
    components = scope.get(
        "component_instance_ids", scope.get("components", ["*"])
    )
    defects = scope.get("defect_types", ["*"])
    return set(components or ["*"]), set(defects or ["*"])


def _representative_component(selector: str) -> str | None:
    if selector == "ITEM":
        return None
    if selector == "*":
        return "COMPONENT"
    return selector.replace("*", "SAMPLE").replace("?", "X")


def _status(capabilities: list[str], *, unscoped_legacy: bool) -> str:
    if "FULL" in capabilities:
        return "FULL_AVAILABLE"
    if "PARTIAL" in capabilities:
        return "PARTIAL_ONLY"
    if "TARGET_ONLY" in capabilities:
        return "TARGET_ONLY_ONLY"
    if unscoped_legacy:
        return "UNSCOPED_LEGACY"
    return "NO_GENERAL_COVERAGE"


def analyze_route_coverage(steps: Iterable[Any]) -> dict[str, Any]:
    """Analyze configured route capability without mutating route or trust state."""
    usable_steps: list[tuple[str, Any]] = []
    selectors: set[str] = set()
    defects: set[str] = set()
    limitations: list[dict[str, str]] = []
    has_unscoped_legacy = False

    for index, step in enumerate(steps, start=1):
        control_point = str(_step_value(step, "control_point_id") or "")
        scope = _step_value(step, "inspection_scope")
        if not control_point:
            continue
        if not _valid_scope(scope):
            limitations.append(
                {
                    "control_point_id": control_point,
                    "code": "MALFORMED_INSPECTION_SCOPE",
                    "message": "Inspection scope is malformed and was excluded from coverage claims.",
                }
            )
            continue
        if scope is None:
            has_unscoped_legacy = True
        step_selectors, step_defects = _scope_keys(scope)
        selectors.update(step_selectors)
        defects.update(step_defects)
        usable_steps.append((control_point or f"step-{index}", scope))

    if not selectors:
        selectors.add("*")
    if not defects:
        defects.add("*")

    explicit_selectors = sorted(value for value in selectors if value != "*")
    explicit_defects = sorted(value for value in defects if value != "*")
    analysis_selectors = explicit_selectors or ["*"]
    analysis_defects = explicit_defects or ["*"]

    rows: list[dict[str, Any]] = []
    for selector in analysis_selectors:
        component = _representative_component(selector)
        for defect_type in analysis_defects:
            capabilities: list[str] = []
            control_points: list[str] = []
            for control_point, scope in usable_steps:
                if scope is None:
                    continue
                coverage = scope_coverage(scope, defect_type, component)
                capabilities.append(coverage)
                if coverage != "NONE":
                    control_points.append(control_point)
            row_status = _status(
                capabilities,
                unscoped_legacy=has_unscoped_legacy and not control_points,
            )
            rows.append(
                {
                    "component_selector": selector,
                    "defect_type": defect_type,
                    "status": row_status,
                    "control_points": control_points,
                    "capabilities": capabilities,
                }
            )

    counts = {
        "FULL_AVAILABLE": 0,
        "PARTIAL_ONLY": 0,
        "NO_GENERAL_COVERAGE": 0,
        "TARGET_ONLY_ONLY": 0,
        "UNSCOPED_LEGACY": 0,
    }
    for row in rows:
        counts[row["status"]] += 1
    return {
        "summary": {
            "keys_analyzed": len(rows),
            "full_available": counts["FULL_AVAILABLE"],
            "partial_only": counts["PARTIAL_ONLY"],
            "no_general_coverage": counts["NO_GENERAL_COVERAGE"],
            "target_only_only": counts["TARGET_ONLY_ONLY"],
            "unscoped_legacy": counts["UNSCOPED_LEGACY"],
        },
        "rows": rows,
        "limitations": limitations,
    }
