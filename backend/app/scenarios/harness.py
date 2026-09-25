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
        events = (
            tuple(
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            if events_path.exists()
            else ()
        )
        return cls(
            root,
            documents.get("scenario.json", {"scenario_id": root.name}),
            events,
            documents.get("expected.json", {}),
            {
                name: value
                for name, value in documents.items()
                if name not in {"scenario.json", "expected.json"}
            },
        )

    @property
    def scenario_id(self) -> str:
        return str(self.scenario.get("scenario_id") or self.scenario.get("id") or self.root.name)


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

    def __init__(
        self,
        *,
        reset: Callable[[], None],
        setup: Callable[[dict], None],
        deliver: Callable[[dict], Any],
        action: Callable[[dict], Any],
        request: Callable[[dict], Any],
        erp: Callable[[dict], Any],
        route_change: Callable[[dict], Any],
        analysis: Callable[[dict], Any],
        tamper: Callable[[dict], Any],
        normalize: Callable[[], dict],
    ):
        self.reset = reset
        self.setup = setup
        self.deliver = deliver
        self.action = action
        self.request = request
        self.erp = erp
        self.route_change = route_change
        self.analysis = analysis
        self.tamper = tamper
        self.normalize = normalize

    @staticmethod
    def _rows(value: Any) -> list[dict]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("actions", "requests", "steps"):
                if isinstance(value.get(key), list):
                    return value[key]
            return [value]
        raise TypeError(f"Scenario extension must be object/list, got {type(value).__name__}")

    def _execute_action(
        self,
        row: dict,
        *,
        after_action: dict[str, list[dict]],
        executed: set[int],
    ) -> None:
        marker = id(row)
        if marker in executed:
            return
        self.action(row)
        executed.add(marker)
        action_name = row.get("action")
        if action_name:
            for dependent in after_action.get(str(action_name), []):
                self._execute_action(
                    dependent,
                    after_action=after_action,
                    executed=executed,
                )

    def run(self, bundle: ScenarioBundle) -> dict[str, Any]:
        self.reset()
        self.setup(bundle.scenario.get("setup", {}))

        actions = self._rows(bundle.extras.get("actions.json"))
        by_index: dict[int, list[dict]] = {}
        by_event_id: dict[str, list[dict]] = {}
        after_action: dict[str, list[dict]] = {}
        untriggered: list[dict] = []
        for row in actions:
            if row.get("after_event") is not None:
                by_index.setdefault(int(row["after_event"]), []).append(row)
            elif row.get("after_event_id"):
                by_event_id.setdefault(str(row["after_event_id"]), []).append(row)
            elif row.get("after_action"):
                after_action.setdefault(str(row["after_action"]), []).append(row)
            else:
                untriggered.append(row)

        executed: set[int] = set()
        for index, event in enumerate(bundle.events, start=1):
            self.deliver(event)
            for row in by_index.get(index, []):
                self._execute_action(row, after_action=after_action, executed=executed)
            for row in by_event_id.get(str(event.get("event_id")), []):
                self._execute_action(row, after_action=after_action, executed=executed)

        # Historical bundles used after_event=0 for pre/post-independent actions.
        for row in by_index.get(0, []):
            self._execute_action(row, after_action=after_action, executed=executed)
        for row in untriggered:
            self._execute_action(row, after_action=after_action, executed=executed)

        for name, handler in (
            ("requests.json", self.request),
            ("erp_behavior.json", self.erp),
            ("route_change.json", self.route_change),
            ("analysis_request.json", self.analysis),
            ("tamper_actions.json", self.tamper),
        ):
            for row in self._rows(bundle.extras.get(name)):
                handler(row)

        actual = self.normalize()
        failures = compare_invariants(actual, bundle.expected)
        return {
            "scenario": bundle.scenario_id,
            "passed": not failures,
            "failures": failures,
            "actual": actual,
            "expected": bundle.expected,
        }
