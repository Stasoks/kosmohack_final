from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.generate_contracts import (
    ROOT,
    _check_or_write,
    events_text,
    registry_text,
    typescript_text,
)


CURRENT = ROOT / "contracts/events/canonical-event.schema.json"
NEXT = ROOT / "contracts/events/evolution/canonical-event-1.1-demo.schema.json"
NEXT_OUTPUT = ROOT / "contracts/events/evolution/generated"


def main() -> None:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    next_schema = json.loads(NEXT.read_text(encoding="utf-8"))
    current_versions = {
        version
        for versions in current["x-event-types"].values()
        for version in versions
    }
    assert current_versions == {"1.0"}
    assert "analyzer_version" not in current["$defs"]["inspectionResult"]["properties"]
    assert "analyzer_version" in next_schema["$defs"]["inspectionResult"]["properties"]

    next_schema["x-codegen-source"] = str(NEXT.relative_to(ROOT))
    rendered = {
        "events.py": events_text(next_schema),
        "events.ts": typescript_text(next_schema),
        "registry.json": registry_text(next_schema, NEXT),
    }
    for name, value in rendered.items():
        _check_or_write(NEXT_OUTPUT / name, value, check=True)

    with tempfile.TemporaryDirectory(prefix="traceq-evolution-stale-") as directory:
        stale = Path(directory) / "events.ts"
        stale.write_text("// deliberately stale\n", encoding="utf-8")
        try:
            _check_or_write(stale, rendered["events.ts"], check=True)
        except SystemExit:
            pass
        else:
            raise AssertionError("stale generated output was not detected")

    print("contract evolution proof: current=1.0, demo=1.1, stale output detected")


if __name__ == "__main__":
    main()
