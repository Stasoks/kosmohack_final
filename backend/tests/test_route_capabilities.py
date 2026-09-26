from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


EXPECTED = {
    "CP-INCOMING": {
        "COMP-HOUSING-*": {
            "surface_crack": "FULL",
            "scratch_or_gouge": "FULL",
            "dent_or_deformation": "FULL",
            "contamination": "FULL",
            "missing_component": "NONE",
            "misplaced_component": "NONE",
        },
        "COMP-BRACKET-*": {
            "surface_crack": "PARTIAL",
            "scratch_or_gouge": "PARTIAL",
            "dent_or_deformation": "FULL",
            "contamination": "FULL",
            "missing_component": "FULL",
            "misplaced_component": "PARTIAL",
        },
    },
    "CP-POST-MILL": {
        "COMP-HOUSING-*": {
            "surface_crack": "PARTIAL",
            "scratch_or_gouge": "FULL",
            "dent_or_deformation": "FULL",
            "contamination": "FULL",
            "missing_component": "NONE",
            "misplaced_component": "NONE",
        },
        "COMP-BRACKET-*": {"*": "NONE"},
    },
    "CP-POST-GRIND": {
        "COMP-HOUSING-*": {
            "surface_crack": "FULL",
            "scratch_or_gouge": "FULL",
            "dent_or_deformation": "PARTIAL",
            "contamination": "FULL",
            "missing_component": "NONE",
            "misplaced_component": "NONE",
        },
        "COMP-BRACKET-*": {"*": "NONE"},
    },
    "CP-FINAL": {
        "COMP-HOUSING-*": {
            "surface_crack": "FULL",
            "scratch_or_gouge": "FULL",
            "dent_or_deformation": "FULL",
            "contamination": "FULL",
            "missing_component": "NONE",
            "misplaced_component": "NONE",
        },
        "COMP-BRACKET-*": {
            "surface_crack": "PARTIAL",
            "scratch_or_gouge": "FULL",
            "dent_or_deformation": "FULL",
            "contamination": "FULL",
            "missing_component": "FULL",
            "misplaced_component": "FULL",
        },
    },
}


def test_demo_route_capability_matrix_is_explicit_in_every_revision() -> None:
    config = json.loads((ROOT / "Test_bundle/config/routes.json").read_text(encoding="utf-8"))
    for route in config["routes"]:
        controls = {
            step["control_point"]["control_point_id"]: step["control_point"][
                "inspection_scope"
            ]
            for step in route["steps"]
            if step.get("control_point")
        }
        for control_point, expected in EXPECTED.items():
            assert controls[control_point]["coverage"] == expected
            assert controls[control_point]["default_coverage"] == "NONE"
            assert controls[control_point]["item_level_fallback"] == "COMP-HOUSING-*"
        assert controls["CP-POST-REWORK"]["mode"] == "TARGET_ONLY"
