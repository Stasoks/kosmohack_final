from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.quality.coverage_gaps import analyze_route_coverage


ROOT = Path(__file__).resolve().parents[2]


def _step(scope, control_point: str = "CP-1") -> dict:
    return {"control_point_id": control_point, "inspection_scope": scope}


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        ([{"coverage": {"*": {"surface_crack": "FULL"}}}], "FULL_AVAILABLE"),
        ([{"coverage": {"*": {"surface_crack": "PARTIAL"}}}], "PARTIAL_ONLY"),
        ([{"coverage": {"*": {"surface_crack": "NONE"}}}], "NO_GENERAL_COVERAGE"),
        ([{"coverage": {"*": {"surface_crack": "TARGET_ONLY"}}}], "TARGET_ONLY_ONLY"),
        (
            [
                {"coverage": {"*": {"surface_crack": "TARGET_ONLY"}}},
                {"coverage": {"*": {"surface_crack": "FULL"}}},
            ],
            "FULL_AVAILABLE",
        ),
    ],
)
def test_coverage_status_precedence(scopes: list[dict], expected: str) -> None:
    result = analyze_route_coverage(
        [_step(scope, f"CP-{index}") for index, scope in enumerate(scopes, start=1)]
    )

    assert result["rows"] == [
        {
            "component_selector": "*",
            "defect_type": "surface_crack",
            "status": expected,
            "control_points": [
                f"CP-{index}"
                for index, scope in enumerate(scopes, start=1)
                if scope["coverage"]["*"]["surface_crack"] != "NONE"
            ],
            "capabilities": [
                scope["coverage"]["*"]["surface_crack"] for scope in scopes
            ],
        }
    ]


def test_legacy_scope_remains_full_for_explicit_key() -> None:
    result = analyze_route_coverage(
        [
            _step(
                {
                    "components": ["COMP-1"],
                    "defect_types": ["surface_crack"],
                }
            )
        ]
    )

    assert result["rows"][0]["status"] == "FULL_AVAILABLE"


def test_unscoped_legacy_is_reported_without_claiming_explicit_full_coverage() -> None:
    result = analyze_route_coverage([_step(None)])

    assert result["rows"][0]["status"] == "UNSCOPED_LEGACY"
    assert result["summary"]["unscoped_legacy"] == 1


def test_wildcard_matrix_is_used_as_fallback() -> None:
    result = analyze_route_coverage(
        [
            _step(
                {
                    "coverage": {"*": {"surface_crack": "FULL"}},
                },
                "CP-WILDCARD",
            ),
            _step(
                {"coverage": {"COMP-B-*": {"surface_crack": "NONE"}}},
                "CP-SPECIFIC",
            ),
        ]
    )
    rows = {row["component_selector"]: row for row in result["rows"]}

    assert rows["COMP-B-*"]["status"] == "FULL_AVAILABLE"
    assert rows["COMP-B-*"]["control_points"] == ["CP-WILDCARD"]


def test_malformed_scope_is_a_safe_limitation() -> None:
    result = analyze_route_coverage(
        [_step({"coverage": ["not", "a", "matrix"]}, "CP-BROKEN")]
    )

    assert result["rows"][0]["status"] == "NO_GENERAL_COVERAGE"
    assert result["limitations"] == [
        {
            "control_point_id": "CP-BROKEN",
            "code": "MALFORMED_INSPECTION_SCOPE",
            "message": "Inspection scope is malformed and was excluded from coverage claims.",
        }
    ]


def test_current_demo_route_has_analyzable_capability_matrix() -> None:
    config = json.loads(
        (ROOT / "Test_bundle/config/routes.json").read_text(encoding="utf-8")
    )
    route = config["routes"][0]
    steps = [
        {
            "control_point_id": (step.get("control_point") or {}).get(
                "control_point_id"
            ),
            "inspection_scope": (step.get("control_point") or {}).get(
                "inspection_scope"
            ),
        }
        for step in route["steps"]
    ]

    result = analyze_route_coverage(steps)

    assert result["summary"]["keys_analyzed"] == 12
    assert result["summary"]["full_available"] > 0
    assert result["limitations"] == []
