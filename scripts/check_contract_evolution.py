from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

if __package__:
    from scripts.generate_contracts import (
        ROOT,
        _check_or_write,
        events_text,
        registry_text,
        typescript_text,
    )
else:
    from generate_contracts import (
        ROOT,
        _check_or_write,
        events_text,
        registry_text,
        typescript_text,
    )


CURRENT = ROOT / "contracts/events/canonical-event.schema.json"
NEXT = ROOT / "contracts/events/evolution/canonical-event-1.1-demo.schema.json"
NEXT_OUTPUT = ROOT / "contracts/events/evolution/generated"
SCENARIOS = ROOT / "scenarios"


def expected_demo_schema(current: dict) -> dict:
    """Describe the complete, intentionally small delta from production 1.0."""
    expected = copy.deepcopy(current)
    expected["$id"] = (
        "https://trace-q.local/contracts/events/evolution/"
        "canonical-event-1.1-demo.schema.json"
    )
    expected["title"] = "TRACE-Q canonical event 1.1 evolution demo"
    expected["properties"]["schema_version"]["const"] = "1.1"
    expected["$defs"]["inspectionResult"]["properties"]["analyzer_version"] = {
        "type": ["string", "null"],
        "maxLength": 128,
    }
    expected["x-event-types"] = {
        event_type: ["1.1"] for event_type in current["x-event-types"]
    }
    return expected


def validate_inspection_fixture_compatibility(
    current: dict, next_schema: dict
) -> int:
    """Prove every current inspection fixture remains valid after only the version bump."""
    current_validator = Draft202012Validator(current, format_checker=FormatChecker())
    next_validator = Draft202012Validator(next_schema, format_checker=FormatChecker())
    checked = 0
    analyzer_fixture: dict | None = None
    for fixture_path in sorted(SCENARIOS.glob("S*/events.jsonl")):
        for line_number, line in enumerate(
            fixture_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "inspection.result":
                continue
            current_errors = list(current_validator.iter_errors(event))
            if current_errors:
                raise AssertionError(
                    f"production fixture invalid at {fixture_path}:{line_number}: "
                    f"{current_errors[0].message}"
                )
            evolved = copy.deepcopy(event)
            evolved["schema_version"] = "1.1"
            next_errors = list(next_validator.iter_errors(evolved))
            if next_errors:
                raise AssertionError(
                    f"1.0 inspection fixture is not 1.1-compatible at "
                    f"{fixture_path}:{line_number}: {next_errors[0].message}"
                )
            analyzer_fixture = analyzer_fixture or evolved
            checked += 1

    if analyzer_fixture is None:
        raise AssertionError("no inspection.result fixtures found")
    analyzer_fixture["payload"]["analyzer_version"] = "vision-qc-demo-1.1"
    analyzer_errors = list(next_validator.iter_errors(analyzer_fixture))
    if analyzer_errors:
        raise AssertionError(
            f"optional analyzer_version fixture is invalid: {analyzer_errors[0].message}"
        )
    return checked


def main() -> None:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    next_schema = json.loads(NEXT.read_text(encoding="utf-8"))
    runtime_registry = json.loads(
        (ROOT / "shared_contracts/generated/registry.json").read_text(encoding="utf-8")
    )
    current_versions = {
        version
        for versions in current["x-event-types"].values()
        for version in versions
    }
    assert current_versions == {"1.0"}
    assert "analyzer_version" not in current["$defs"]["inspectionResult"]["properties"]
    assert "analyzer_version" in next_schema["$defs"]["inspectionResult"]["properties"]
    assert next_schema == expected_demo_schema(current), (
        "demo 1.1 must equal production 1.0 except for version metadata "
        "and optional analyzer_version"
    )
    assert {
        contract["schema_version"] for contract in runtime_registry["contracts"]
    } == {"1.0"}
    compatible_fixtures = validate_inspection_fixture_compatibility(current, next_schema)

    next_schema["x-codegen-source"] = str(NEXT.relative_to(ROOT))
    rendered = {
        "events.py": events_text(next_schema),
        "events.ts": typescript_text(next_schema),
        "registry.json": registry_text(next_schema, NEXT),
    }
    for name, value in rendered.items():
        _check_or_write(NEXT_OUTPUT / name, value, check=True)
    assert "analyzer_version" not in events_text(current)
    assert "analyzer_version" in rendered["events.py"]
    assert events_text(current) != rendered["events.py"]

    with tempfile.TemporaryDirectory(prefix="traceq-evolution-stale-") as directory:
        stale = Path(directory) / "events.ts"
        stale.write_text("// deliberately stale\n", encoding="utf-8")
        try:
            _check_or_write(stale, rendered["events.ts"], check=True)
        except SystemExit:
            pass
        else:
            raise AssertionError("stale generated output was not detected")

    print(
        "contract evolution proof: current=1.0, demo=1.1, "
        f"inspection fixtures={compatible_fixtures}, stale output detected"
    )


if __name__ == "__main__":
    main()
