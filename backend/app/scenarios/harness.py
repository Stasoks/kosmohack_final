from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


JSON_FILES = (
    "scenario.json", "expected.json", "actions.json", "requests.json",
    "erp_behavior.json", "tamper_actions.json", "analysis_request.json", "route_change.json",
)


@dataclass(frozen=True)
class ScenarioBundle:
    root: Path
    scenario: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    expected: dict[str, Any]
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "ScenarioBundle":
        if not root.is_dir():
            raise ValueError(f"Scenario directory does not exist: {root}")
        documents: dict[str, Any] = {}
        for name in JSON_FILES:
            path = root / name
            if path.exists():
                documents[name] = json.loads(path.read_text(encoding="utf-8"))
        events_path = root / "events.jsonl"
        events = tuple(json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()) if events_path.exists() else ()
        return cls(root, documents.get("scenario.json", {"id": root.name}), events,
                   documents.get("expected.json", {}),
                   {name: value for name, value in documents.items() if name not in {"scenario.json", "expected.json"}})


def compare_invariants(actual: Any, expected: Any, path: str = "$") -> list[str]:
    """Subset comparison: expected describes business invariants, not DB snapshots."""
    failures: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        for key, value in expected.items():
            if key not in actual:
                failures.append(f"{path}.{key}: missing")
            else:
                failures.extend(compare_invariants(actual[key], value, f"{path}.{key}"))
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            failures.append(f"{path}: expected list")
        else:
            for value in expected:
                if value not in actual:
                    failures.append(f"{path}: missing member {value!r}")
    elif actual != expected:
        failures.append(f"{path}: expected {expected!r}, got {actual!r}")
    return failures


class ScenarioHarness:
    """V2 orchestration. Event list order is delivery order and is never sorted."""

    def __init__(self, *, reset: Callable[[], None], setup: Callable[[dict], None],
                 deliver: Callable[[dict], Any], action: Callable[[dict], Any],
                 request: Callable[[dict], Any], erp: Callable[[dict], Any],
                 route_change: Callable[[dict], Any], analysis: Callable[[dict], Any],
                 tamper: Callable[[dict], Any], normalize: Callable[[], dict]):
        self.reset, self.setup, self.deliver, self.action = reset, setup, deliver, action
        self.request, self.erp, self.route_change, self.analysis = request, erp, route_change, analysis
        self.tamper, self.normalize = tamper, normalize

    @staticmethod
    def _rows(value: Any) -> list[dict]:
        if value is None: return []
        if isinstance(value, list): return value
        if isinstance(value, dict) and isinstance(value.get("actions"), list): return value["actions"]
        return [value]

    def run(self, bundle: ScenarioBundle) -> dict[str, Any]:
        self.reset()
        self.setup(bundle.scenario.get("setup", {}))
        actions = self._rows(bundle.extras.get("actions.json"))
        by_point: dict[int, list[dict]] = {}
        for action in actions:
            by_point.setdefault(int(action.get("after_event", 0)), []).append(action)
        for index, event in enumerate(bundle.events, start=1):
            self.deliver(event)  # file order is transport delivery order
            for action in by_point.get(index, []): self.action(action)
        for row in by_point.get(0, []): self.action(row)
        for name, handler in (
            ("requests.json", self.request), ("erp_behavior.json", self.erp),
            ("route_change.json", self.route_change), ("analysis_request.json", self.analysis),
            ("tamper_actions.json", self.tamper),
        ):
            for row in self._rows(bundle.extras.get(name)): handler(row)
        actual = self.normalize()
        failures = compare_invariants(actual, bundle.expected)
        return {"scenario": bundle.scenario.get("id", bundle.root.name), "passed": not failures,
                "failures": failures, "actual": actual, "expected": bundle.expected}
