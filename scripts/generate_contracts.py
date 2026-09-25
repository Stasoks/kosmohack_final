from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/events/canonical-event.schema.json"
OUTPUT_PATH = ROOT / "shared_contracts/generated/events.py"
REGISTRY_PATH = ROOT / "shared_contracts/generated/registry.json"


def render(schema: dict) -> tuple[str, str]:
    event_types = schema["x-event-types"]
    keys = sorted((event_type, version) for event_type, versions in event_types.items() for version in versions)
    python = (
        '"""Generated from contracts/events/canonical-event.schema.json. Do not edit."""\n\n'
        f"EVENT_TYPES = {tuple(sorted(event_types))!r}\n"
        f"SCHEMA_REGISTRY = frozenset({tuple(keys)!r})\n"
    )
    registry = json.dumps(
        {
            "source": str(SCHEMA_PATH.relative_to(ROOT)),
            "contracts": [
                {"event_type": event_type, "schema_version": version} for event_type, version in keys
            ],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    return python, registry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    python, registry = render(schema)
    if args.check:
        stale = []
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != python:
            stale.append(str(OUTPUT_PATH.relative_to(ROOT)))
        if not REGISTRY_PATH.exists() or REGISTRY_PATH.read_text(encoding="utf-8") != registry:
            stale.append(str(REGISTRY_PATH.relative_to(ROOT)))
        if stale:
            raise SystemExit("Generated contract artifacts are stale: " + ", ".join(stale))
        return
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(python, encoding="utf-8")
    REGISTRY_PATH.write_text(registry, encoding="utf-8")


if __name__ == "__main__":
    main()
