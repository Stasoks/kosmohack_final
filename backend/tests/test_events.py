from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.events import canonical_event_dict, validate_event
from backend.app.errors import TraceQError
from backend.app.security.crypto import canonical_json_bytes, sha256_hex


ROOT = Path(__file__).resolve().parents[2]


def fixture_event(scenario: str, line: int = 0) -> dict:
    rows = (ROOT / f"scenarios/{scenario}/events.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(rows[line])


def test_all_scenario_events_validate() -> None:
    for path in ROOT.glob("scenarios/*/events.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            validate_event(json.loads(line))


def test_canonical_hash_does_not_depend_on_key_order() -> None:
    value = fixture_event("S03")
    reordered = dict(reversed(list(value.items())))
    left = canonical_json_bytes(canonical_event_dict(validate_event(value)))
    right = canonical_json_bytes(canonical_event_dict(validate_event(reordered)))
    assert sha256_hex(left) == sha256_hex(right)


def test_negative_duration_is_semantic_error() -> None:
    value = fixture_event("S03", 2)
    value["payload"].pop("duration_seconds", None)
    value["payload"]["duration"] = {
        "value": -1,
        "unit": "s",
        "meaning": "active_processing",
    }
    with pytest.raises(TraceQError) as caught:
        validate_event(value)
    assert caught.value.code == "SEMANTIC_VALIDATION_ERROR"


def test_unknown_version_is_rejected() -> None:
    value = fixture_event("S01")
    value["schema_version"] = "9.9"
    with pytest.raises(TraceQError) as caught:
        validate_event(value)
    assert caught.value.code == "UNSUPPORTED_SCHEMA_VERSION"


def test_optional_values_are_not_invented() -> None:
    value = fixture_event("S02")
    event = validate_event(value)
    assert event.operation_run_id is None


def test_load_generator_emits_canonical_item_registration() -> None:
    from scripts.generate_events import event_stream

    event = next(event_stream(1, 1, 0.0, 0.0, 0.0, 42))
    assert "item_id" not in event["payload"]
    validate_event(event)
