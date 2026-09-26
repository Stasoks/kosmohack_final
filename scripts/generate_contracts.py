from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/events/canonical-event.schema.json"
OUTPUT_DIR = ROOT / "shared_contracts/generated"

CLASS_NAMES = {
    "source": "SourceRef",
    "duration": "Duration",
    "defect": "Defect",
    "itemRegistered": "ItemRegisteredPayload",
    "operationStarted": "OperationStartedPayload",
    "operationFinished": "OperationFinishedPayload",
    "inspectionResult": "InspectionResultPayload",
    "machineState": "MachineStatePayload",
    "operatorAction": "OperatorActionPayload",
    "controlDeviceInvalidated": "ControlDeviceInvalidatedPayload",
}
PAYLOAD_DEFS = {
    "item.registered": "itemRegistered",
    "operation.started": "operationStarted",
    "operation.finished": "operationFinished",
    "inspection.result": "inspectionResult",
    "machine.state": "machineState",
    "operator.action": "operatorAction",
    "control_device.invalidated": "controlDeviceInvalidated",
}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def registry_text(schema: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> str:
    keys = sorted(
        (kind, version)
        for kind, versions in schema["x-event-types"].items()
        for version in versions
    )
    return (
        json.dumps(
            {
                "contracts": [
                    {"event_type": kind, "schema_version": version}
                    for kind, version in keys
                ],
                "source": _display_path(schema_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _literal(values: list[Any]) -> str:
    return "Literal[" + ", ".join(repr(value) for value in values) + "]"


def _type_expr(value: dict[str, Any]) -> str:
    if "$ref" in value:
        return CLASS_NAMES[value["$ref"].rsplit("/", 1)[-1]]
    if "enum" in value:
        return _literal(value["enum"])
    if "const" in value:
        return _literal([value["const"]])
    if "oneOf" in value:
        parts = [_type_expr(part) for part in value["oneOf"]]
        return " | ".join(dict.fromkeys(parts))
    kind = value.get("type")
    if isinstance(kind, list):
        parts = []
        for item in kind:
            if item == "null":
                parts.append("None")
            else:
                clone = dict(value)
                clone["type"] = item
                parts.append(_type_expr(clone))
        return " | ".join(dict.fromkeys(parts))
    if kind == "string":
        return "datetime" if value.get("format") == "date-time" else "str"
    if kind == "integer":
        return "int"
    if kind == "number":
        return "float"
    if kind == "boolean":
        return "bool"
    if kind == "object":
        return "dict[str, Any]"
    if kind == "array":
        return f"list[{_type_expr(value.get('items', {}))}]"
    if kind == "null":
        return "None"
    return "Any"


def _field_expr(prop: dict[str, Any], *, required: bool) -> str:
    args: list[str] = []
    if "minLength" in prop:
        args.append(f"min_length={prop['minLength']}")
    if "maxLength" in prop:
        args.append(f"max_length={prop['maxLength']}")
    if "minimum" in prop:
        args.append(f"ge={prop['minimum']!r}")
    if "maximum" in prop:
        args.append(f"le={prop['maximum']!r}")
    if "maxItems" in prop:
        args.append(f"max_length={prop['maxItems']}")

    if "default" in prop:
        default = prop["default"]
        if isinstance(default, list):
            args.insert(0, "default_factory=list")
        elif isinstance(default, dict):
            args.insert(0, "default_factory=dict")
        else:
            args.insert(0, f"default={default!r}")
        return "Field(" + ", ".join(args) + ")" if args else repr(default)

    if required:
        return "Field(" + ", ".join(args) + ")" if args else ""

    args.insert(0, "default=None")
    return "Field(" + ", ".join(args) + ")"


def events_text(schema: dict[str, Any]) -> str:
    source = schema.get("x-codegen-source", "contracts/events/canonical-event.schema.json")
    lines = [
        f'"""Generated from {source}. Do not edit."""',
        "from __future__ import annotations",
        "",
        "from datetime import datetime",
        "from typing import Any, Literal",
        "",
        "from pydantic import BaseModel, ConfigDict, Field",
        "",
        "",
        "class ContractModel(BaseModel):",
        '    model_config = ConfigDict(extra="forbid")',
        "",
    ]

    for def_name, definition in schema["$defs"].items():
        class_name = CLASS_NAMES.get(def_name)
        if not class_name:
            continue
        required = set(definition.get("required", []))
        lines.extend(["", f"class {class_name}(ContractModel):"])
        properties = definition.get("properties", {})
        if not properties:
            lines.append("    pass")
            continue
        for name, prop in properties.items():
            annotation = _type_expr(prop)
            field = _field_expr(prop, required=name in required)
            if field:
                lines.append(f"    {name}: {annotation} = {field}")
            else:
                lines.append(f"    {name}: {annotation}")

    event_types = tuple(sorted(schema["x-event-types"]))
    registry = tuple(
        sorted(
            (event_type, version)
            for event_type, versions in schema["x-event-types"].items()
            for version in versions
        )
    )
    lines.extend(
        [
            "",
            "",
            f"EVENT_TYPES = {event_types!r}",
            f"SCHEMA_REGISTRY = frozenset({registry!r})",
            "PAYLOAD_MODELS = {",
        ]
    )
    for event_type, def_name in PAYLOAD_DEFS.items():
        if event_type in schema["x-event-types"] and def_name in schema["$defs"]:
            lines.append(f'    "{event_type}": {CLASS_NAMES[def_name]},')
    lines.extend(["}", ""])
    return "\n".join(lines)


def _ts_literal(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _ts_type_expr(value: dict[str, Any]) -> str:
    if "$ref" in value:
        return CLASS_NAMES[value["$ref"].rsplit("/", 1)[-1]]
    if "enum" in value:
        return " | ".join(_ts_literal(item) for item in value["enum"])
    if "const" in value:
        return _ts_literal(value["const"])
    if "oneOf" in value:
        return " | ".join(dict.fromkeys(_ts_type_expr(part) for part in value["oneOf"]))
    kind = value.get("type")
    if isinstance(kind, list):
        parts = []
        for item in kind:
            clone = dict(value)
            clone["type"] = item
            parts.append(_ts_type_expr(clone))
        return " | ".join(dict.fromkeys(parts))
    if kind == "string":
        return "string"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "object":
        return "Record<string, unknown>"
    if kind == "array":
        item_type = _ts_type_expr(value.get("items", {}))
        return f"Array<{item_type}>"
    if kind == "null":
        return "null"
    return "unknown"


def typescript_text(schema: dict[str, Any]) -> str:
    source = schema.get("x-codegen-source", "contracts/events/canonical-event.schema.json")
    lines = [f"// Generated from {source}. Do not edit.", ""]
    for def_name, definition in schema["$defs"].items():
        class_name = CLASS_NAMES.get(def_name)
        if not class_name:
            continue
        required = set(definition.get("required", []))
        lines.append(f"export interface {class_name} {{")
        for name, prop in definition.get("properties", {}).items():
            optional = "" if name in required else "?"
            lines.append(f"  {name}{optional}: {_ts_type_expr(prop)};")
        lines.extend(["}", ""])

    event_types = sorted(schema["x-event-types"])
    registry = sorted(
        (event_type, version)
        for event_type, versions in schema["x-event-types"].items()
        for version in versions
    )
    lines.append(
        "export const EVENT_TYPES = ["
        + ", ".join(json.dumps(value) for value in event_types)
        + "] as const;"
    )
    lines.append("export type EventType = (typeof EVENT_TYPES)[number];")
    lines.append("export const SCHEMA_REGISTRY = [")
    for event_type, version in registry:
        lines.append(
            "  { event_type: "
            + json.dumps(event_type)
            + ", schema_version: "
            + json.dumps(version)
            + " },"
        )
    lines.extend(["] as const;", "", "export interface PayloadModels {"])
    for event_type, def_name in PAYLOAD_DEFS.items():
        if event_type in schema["x-event-types"] and def_name in schema["$defs"]:
            lines.append(f'  "{event_type}": {CLASS_NAMES[def_name]};')
    lines.extend(["}", ""])
    return "\n".join(lines)


def _check_or_write(path: Path, rendered: str, *, check: bool) -> None:
    if check:
        with tempfile.TemporaryDirectory(prefix="traceq-codegen-") as directory:
            generated = Path(directory) / path.name
            generated.write_text(rendered, encoding="utf-8")
            if not path.exists() or path.read_bytes() != generated.read_bytes():
                raise SystemExit(f"Generated file is stale: {_display_path(path)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    schema_path = args.schema if args.schema.is_absolute() else ROOT / args.schema
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema.setdefault("x-codegen-source", _display_path(schema_path))
    Draft202012Validator.check_schema(schema)
    _check_or_write(output_dir / "events.py", events_text(schema), check=args.check)
    _check_or_write(output_dir / "events.ts", typescript_text(schema), check=args.check)
    _check_or_write(
        output_dir / "registry.json", registry_text(schema, schema_path), check=args.check
    )


if __name__ == "__main__":
    main()
