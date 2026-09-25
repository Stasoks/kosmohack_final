from __future__ import annotations

import argparse
import importlib
import json
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/events/canonical-event.schema.json"
REGISTRY_PATH = ROOT / "shared_contracts/generated/registry.json"

MODEL_NAMES = {
    "item.registered": "ItemRegisteredPayload",
    "operation.started": "OperationStartedPayload",
    "operation.finished": "OperationFinishedPayload",
    "inspection.result": "InspectionResultPayload",
    "machine.state": "MachineStatePayload",
    "operator.action": "OperatorActionPayload",
    "control_device.invalidated": "ControlDeviceInvalidatedPayload",
}
DEF_NAMES = {
    "item.registered": "itemRegistered", "operation.started": "operationStarted",
    "operation.finished": "operationFinished", "inspection.result": "inspectionResult",
    "machine.state": "machineState", "operator.action": "operatorAction",
    "control_device.invalidated": "controlDeviceInvalidated",
}


def registry_text(schema: dict) -> str:
    keys = sorted((kind, version) for kind, versions in schema["x-event-types"].items() for version in versions)
    return json.dumps({"contracts": [{"event_type": k, "schema_version": v} for k, v in keys],
                       "source": str(SCHEMA_PATH.relative_to(ROOT)).replace("\\", "/")},
                      ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_generated_models(schema: dict) -> None:
    module = importlib.import_module("shared_contracts.generated.events")
    expected_registry = frozenset((kind, version) for kind, versions in schema["x-event-types"].items() for version in versions)
    if module.SCHEMA_REGISTRY != expected_registry:
        raise SystemExit("Generated SCHEMA_REGISTRY is stale")
    for event_type, class_name in MODEL_NAMES.items():
        model = getattr(module, class_name, None)
        if model is None:
            raise SystemExit(f"Generated model missing: {class_name}")
        expected_fields = set(schema["$defs"][DEF_NAMES[event_type]]["properties"])
        if set(model.model_fields) != expected_fields:
            raise SystemExit(f"Generated model fields are stale for {event_type}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    rendered = registry_text(schema)
    validate_generated_models(schema)
    if args.check:
        with tempfile.TemporaryDirectory(prefix="traceq-contracts-") as directory:
            regenerated = Path(directory) / "registry.json"
            regenerated.write_text(rendered, encoding="utf-8")
            if not REGISTRY_PATH.exists() or REGISTRY_PATH.read_bytes() != regenerated.read_bytes():
                raise SystemExit("Generated contract registry is stale")
        return
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
