from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_contracts import _check_or_write, events_text, typescript_text
from scripts.check_contract_evolution import (
    expected_demo_schema,
    validate_inspection_fixture_compatibility,
)


ROOT = Path(__file__).resolve().parents[2]


def test_codegen_is_deterministic_and_includes_typescript() -> None:
    schema = json.loads(
        (ROOT / "contracts/events/canonical-event.schema.json").read_text(encoding="utf-8")
    )
    assert events_text(schema) == events_text(schema)
    rendered = typescript_text(schema)
    assert rendered == typescript_text(schema)
    assert "export interface InspectionResultPayload" in rendered
    assert '"inspection.result"' in rendered


def test_check_detects_stale_generated_typescript(tmp_path: Path) -> None:
    target = tmp_path / "events.ts"
    target.write_text("// stale\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Generated file is stale"):
        _check_or_write(target, "// current\n", check=True)


def test_evolution_field_is_not_in_current_p0_schema() -> None:
    current = json.loads(
        (ROOT / "contracts/events/canonical-event.schema.json").read_text(encoding="utf-8")
    )
    future = json.loads(
        (
            ROOT
            / "contracts/events/evolution/canonical-event-1.1-demo.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert "analyzer_version" not in current["$defs"]["inspectionResult"]["properties"]
    assert "analyzer_version" in future["$defs"]["inspectionResult"]["properties"]
    assert {
        version for versions in current["x-event-types"].values() for version in versions
    } == {"1.0"}


def test_demo_1_1_is_backward_compatible_with_inspection_fixtures() -> None:
    current = json.loads(
        (ROOT / "contracts/events/canonical-event.schema.json").read_text(encoding="utf-8")
    )
    future = json.loads(
        (
            ROOT
            / "contracts/events/evolution/canonical-event-1.1-demo.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert future == expected_demo_schema(current)
    assert validate_inspection_fixture_compatibility(current, future) > 0
