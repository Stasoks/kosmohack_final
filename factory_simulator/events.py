from __future__ import annotations

from datetime import datetime
from typing import Any

from shared_contracts.generated.events import PAYLOAD_MODELS, SCHEMA_REGISTRY


SOURCE_BY_EVENT = {
    "item.registered": ("MES-01", "mes"),
    "operation.started": ("MES-01", "mes"),
    "operation.finished": ("MES-01", "mes"),
    "inspection.result": ("VISION-01", "vision_qc"),
    "machine.state": ("EQUIP-GW-01", "equipment_gateway"),
    "operator.action": ("OPTERM-01", "operator_terminal"),
}


def canonical_event(
    *,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    item_id: str | None,
    operation_run_id: str | None = None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build and validate a P0 canonical event without source sequencing."""
    if (event_type, "1.0") not in SCHEMA_REGISTRY:
        raise ValueError(f"Unsupported canonical event: {event_type}@1.0")
    source_id, source_type = SOURCE_BY_EVENT[event_type]
    validated_payload = PAYLOAD_MODELS[event_type](**payload).model_dump(
        mode="json", exclude_none=True
    )
    value: dict[str, Any] = {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": "1.0",
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "source": {"source_id": source_id, "source_type": source_type},
        "payload": validated_payload,
    }
    if item_id:
        value["item_id"] = item_id
    if operation_run_id:
        value["operation_run_id"] = operation_run_id
    return value
