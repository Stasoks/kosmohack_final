from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
schema = json.loads((ROOT / "contracts/events/canonical-event.schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(schema, format_checker=FormatChecker())


def main() -> None:
    checked = 0
    for fixture in sorted((ROOT / "scenarios").glob("*/events.jsonl")):
        for line_number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            errors = sorted(validator.iter_errors(event), key=lambda error: list(error.path))
            if errors:
                details = "; ".join(error.message for error in errors[:3])
                raise SystemExit(f"{fixture}:{line_number}: {details}")
            checked += 1
    if not checked:
        raise SystemExit("No contract fixtures found")
    print(f"validated {checked} contract fixtures")


if __name__ == "__main__":
    main()
