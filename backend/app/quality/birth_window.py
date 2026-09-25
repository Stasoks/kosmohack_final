from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.app.quality.trust import scope_covers


@dataclass(frozen=True)
class EvidenceValue:
    evidence_type: str
    evidence_role: str
    source_event_id: str | None
    occurred_at: datetime | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BirthWindowResult:
    status: str
    left_boundary_at: datetime | None
    right_boundary_at: datetime | None
    evidence: tuple[EvidenceValue, ...]


def calculate_birth_window(
    *,
    defect_observation: dict[str, Any],
    observations: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    machine_events: list[dict[str, Any]],
    operator_actions: list[dict[str, Any]],
    limitations: list[EvidenceValue] | None = None,
) -> BirthWindowResult:
    defect_time = defect_observation["occurred_at"]
    defect_type = defect_observation["defect_type"]
    component = defect_observation.get("component_instance_id")
    evidence: list[EvidenceValue] = [
        EvidenceValue(
            "FIRST_TRUSTED_DEFECT",
            "BOUNDARY",
            defect_observation.get("event_id"),
            defect_time,
            {"defect_type": defect_type, "component_instance_id": component},
        )
    ]

    candidates = [
        obs
        for obs in observations
        if obs["occurred_at"] < defect_time
        and obs.get("trust_status") == "TRUSTED"
        and obs.get("inspection_result") == "no_defect"
        and scope_covers(obs.get("inspection_scope"), defect_type, component)
        and (obs.get("component_instance_id") in (None, component) or component is None)
    ]
    last_good = max(candidates, key=lambda item: item["occurred_at"], default=None)
    left = last_good["occurred_at"] if last_good else None
    if last_good:
        evidence.insert(
            0,
            EvidenceValue(
                "LAST_TRUSTED_GOOD",
                "BOUNDARY",
                last_good.get("event_id"),
                last_good["occurred_at"],
                {"control_point_id": last_good.get("control_point_id")},
            ),
        )

    def inside(value: datetime) -> bool:
        return (left is None or value > left) and value <= defect_time

    for operation in operations:
        marker = operation.get("finished_at") or operation.get("started_at")
        if marker and inside(marker):
            evidence.append(
                EvidenceValue(
                    "OPERATION_IN_WINDOW",
                    "CONTEXT",
                    operation.get("source_event_id"),
                    marker,
                    {
                        "operation_run_id": operation.get("operation_run_id"),
                        "operation_id": operation.get("operation_id"),
                        "operator_id": operation.get("operator_id"),
                        "equipment_id": operation.get("equipment_id"),
                    },
                )
            )
    for machine in machine_events:
        if inside(machine["occurred_at"]) and machine.get("state") not in {"normal", "idle"}:
            evidence.append(
                EvidenceValue(
                    "MACHINE_WARNING",
                    "CONTEXT",
                    machine.get("event_id"),
                    machine["occurred_at"],
                    {"equipment_id": machine.get("equipment_id"), "state": machine.get("state")},
                )
            )
    for action in operator_actions:
        if inside(action["occurred_at"]):
            evidence.append(
                EvidenceValue(
                    "OPERATOR_ACTION",
                    "CONTEXT",
                    action.get("event_id"),
                    action["occurred_at"],
                    {"operator_id": action.get("operator_id"), "action_type": action.get("action_type")},
                )
            )
    for obs in observations:
        if inside(obs["occurred_at"]) and obs.get("trust_status") in {
            "UNTRUSTED",
            "UNASSESSABLE",
            "CONFLICTED",
            "INVALIDATED",
        }:
            kind = {
                "CONFLICTED": "CONFLICTING_OBSERVATION",
                "INVALIDATED": "DEVICE_VALIDITY",
            }.get(obs.get("trust_status"), "POOR_OBSERVATION")
            evidence.append(
                EvidenceValue(
                    kind,
                    "LIMITATION",
                    obs.get("event_id"),
                    obs["occurred_at"],
                    {"trust_status": obs.get("trust_status"), "reasons": obs.get("trust_reasons", [])},
                )
            )
    evidence.extend(limitations or [])
    return BirthWindowResult(
        status="BOUNDED" if left else "LEFT_OPEN",
        left_boundary_at=left,
        right_boundary_at=defect_time,
        evidence=tuple(evidence),
    )
