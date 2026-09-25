from __future__ import annotations

from datetime import datetime
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.app.errors import TraceQError
from shared_contracts.generated.events import (
    SCHEMA_REGISTRY, PAYLOAD_MODELS, ControlDeviceInvalidatedPayload,
    InspectionResultPayload, ItemRegisteredPayload, MachineStatePayload,
    OperationFinishedPayload, OperationStartedPayload, OperatorActionPayload, SourceRef,
)

SUPPORTED_EVENT_TYPES = {event_type for event_type, _ in SCHEMA_REGISTRY}
Payload = Union[ItemRegisteredPayload, OperationStartedPayload, OperationFinishedPayload,
                InspectionResultPayload, MachineStatePayload, OperatorActionPayload,
                ControlDeviceInvalidatedPayload]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(min_length=1, max_length=16)
    occurred_at: datetime
    source: SourceRef
    item_id: str | None = Field(default=None, max_length=128)
    operation_run_id: str | None = Field(default=None, max_length=128)
    payload: Payload

    @model_validator(mode="after")
    def required_envelope_ids(self):
        item_events = {"item.registered", "operation.started", "operation.finished", "inspection.result"}
        if self.event_type in item_events and not self.item_id:
            raise ValueError("item_id is required in the event envelope")
        if self.event_type in {"operation.started", "operation.finished"} and not self.operation_run_id:
            raise ValueError("operation_run_id is required in the event envelope")
        return self


def _normalize_legacy(value: dict[str, Any]) -> dict[str, Any]:
    """Temporary boundary adapter; internal models always use envelope IDs."""
    candidate = dict(value)
    payload = dict(candidate.get("payload") or {})
    for key in ("item_id", "operation_run_id"):
        legacy = payload.pop(key, None)
        if candidate.get(key) is None and legacy is not None:
            candidate[key] = legacy
        elif legacy is not None and candidate.get(key) != legacy:
            raise TraceQError("EVENT_SCHEMA_VALIDATION_ERROR", f"{key} differs between envelope and legacy payload", 422)
    if "duration_seconds" in payload and "duration" not in payload:
        payload["duration"] = {"value": payload.pop("duration_seconds"), "unit": "s", "meaning": "active_processing"}
    candidate["payload"] = payload
    return candidate


def validate_event(value: Any) -> EventEnvelope:
    if not isinstance(value, dict):
        raise TraceQError("INVALID_EVENT", "Event must be a JSON object", 422)
    event_type, version = value.get("event_type"), value.get("schema_version")
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise TraceQError("UNSUPPORTED_EVENT_TYPE", "Unsupported event type", 422)
    if (event_type, version) not in SCHEMA_REGISTRY:
        raise TraceQError("UNSUPPORTED_SCHEMA_VERSION", "Unsupported event schema version", 422)
    candidate = _normalize_legacy(value)
    duration = candidate.get("payload", {}).get("duration")
    if event_type == "operation.finished" and isinstance(duration, dict):
        duration_value = duration.get("value")
        if isinstance(duration_value, (int, float)) and not isinstance(duration_value, bool) and duration_value < 0:
            raise TraceQError(
                "SEMANTIC_VALIDATION_ERROR",
                "Operation duration cannot be negative",
                422,
            )
    try:
        candidate["payload"] = PAYLOAD_MODELS[event_type].model_validate(candidate.get("payload"))
        return EventEnvelope.model_validate(candidate)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        raise TraceQError("EVENT_SCHEMA_VALIDATION_ERROR", f"Event validation failed: {details}", 422) from exc


def canonical_event_dict(event: EventEnvelope) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude_none=False)


def data_quality_warnings(event: EventEnvelope) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if isinstance(event.payload, OperationFinishedPayload) and event.payload.duration:
        factor = {"ms": .001, "s": 1, "min": 60, "h": 3600}[event.payload.duration.unit]
        if event.payload.duration.value * factor > 4 * 3600:
            warnings.append({"code": "SUSPICIOUS_DURATION", "message": "Reported operation duration exceeds four hours"})
    return warnings
