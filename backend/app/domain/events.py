from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.app.errors import TraceQError
from shared_contracts.generated.events import SCHEMA_REGISTRY


SUPPORTED_SCHEMA_VERSIONS = {version for _, version in SCHEMA_REGISTRY}
SUPPORTED_EVENT_TYPES = {event_type for event_type, _ in SCHEMA_REGISTRY}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(StrictModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=64)
    sequence: int | None = Field(default=None, ge=0)


class Duration(StrictModel):
    value: float
    unit: Literal["ms", "s", "min", "h"]
    meaning: str = Field(min_length=1, max_length=64)

    @field_validator("value")
    @classmethod
    def non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("SEMANTIC_VALIDATION_ERROR: duration must be non-negative")
        return value


class Defect(StrictModel):
    defect_type: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    severity: Literal["minor", "major", "critical"] | None = None
    component_instance_id: str | None = Field(default=None, max_length=128)


class ItemRegisteredPayload(StrictModel):
    item_id: str = Field(min_length=1, max_length=128)
    product_definition_id: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=64)
    line_id: str | None = Field(default=None, max_length=128)
    route_id: str | None = Field(default=None, max_length=128)


class OperationStartedPayload(StrictModel):
    item_id: str = Field(min_length=1, max_length=128)
    operation_run_id: str = Field(min_length=1, max_length=128)
    operation_id: str = Field(min_length=1, max_length=128)
    operator_id: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    station_id: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] | None = None
    previous_operation_run_id: str | None = Field(default=None, max_length=128)
    run_reason: Literal["production", "rework"] = "production"
    rework_for_nonconformance_id: str | None = None


class OperationFinishedPayload(StrictModel):
    item_id: str = Field(min_length=1, max_length=128)
    operation_run_id: str = Field(min_length=1, max_length=128)
    completion_status: Literal["completed", "failed", "aborted", "interrupted"]
    duration: Duration | None = None
    stop_reason: str | None = Field(default=None, max_length=1000)
    parameters: dict[str, Any] | None = None


class InspectionResultPayload(StrictModel):
    item_id: str = Field(min_length=1, max_length=128)
    inspection_result: Literal["no_defect", "defect_detected", "impossible_to_assess"]
    observation_quality: Literal["good", "poor", "unknown"]
    control_point_id: str = Field(min_length=1, max_length=128)
    operation_run_id: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    inspection_scope: dict[str, Any] | list[Any] | None = None
    defects: list[Defect] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    component_instance_id: str | None = Field(default=None, max_length=128)
    control_device_id: str | None = Field(default=None, max_length=128)
    capture_session_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def defects_match_result(self) -> "InspectionResultPayload":
        if self.inspection_result == "defect_detected" and not self.defects:
            raise ValueError("defects must not be empty for defect_detected")
        if self.inspection_result != "defect_detected" and self.defects:
            raise ValueError("defects are only allowed for defect_detected")
        return self


class MachineStatePayload(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=64)
    item_id: str | None = Field(default=None, max_length=128)
    operation_run_id: str | None = Field(default=None, max_length=128)
    code: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] | None = None


class OperatorActionPayload(StrictModel):
    operator_id: str = Field(min_length=1, max_length=128)
    action_type: str = Field(min_length=1, max_length=64)
    item_id: str | None = Field(default=None, max_length=128)
    operation_run_id: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Any] | None = None


Payload = Union[
    ItemRegisteredPayload,
    OperationStartedPayload,
    OperationFinishedPayload,
    InspectionResultPayload,
    MachineStatePayload,
    OperatorActionPayload,
]

PAYLOAD_MODELS: dict[str, type[StrictModel]] = {
    "item.registered": ItemRegisteredPayload,
    "operation.started": OperationStartedPayload,
    "operation.finished": OperationFinishedPayload,
    "inspection.result": InspectionResultPayload,
    "machine.state": MachineStatePayload,
    "operator.action": OperatorActionPayload,
}


class EventEnvelope(StrictModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(min_length=1, max_length=16)
    occurred_at: datetime
    source: SourceRef
    item_id: str | None = Field(default=None, max_length=128)
    operation_run_id: str | None = Field(default=None, max_length=128)
    payload: Payload

    @model_validator(mode="after")
    def consistent_ids(self) -> "EventEnvelope":
        payload_item = getattr(self.payload, "item_id", None)
        payload_run = getattr(self.payload, "operation_run_id", None)
        if payload_item and self.item_id and payload_item != self.item_id:
            raise ValueError("item_id differs between envelope and payload")
        if payload_run and self.operation_run_id and payload_run != self.operation_run_id:
            raise ValueError("operation_run_id differs between envelope and payload")
        if self.event_type in {
            "item.registered",
            "operation.started",
            "operation.finished",
            "inspection.result",
        } and not (self.item_id or payload_item):
            raise ValueError("item_id is required for this event type")
        self.item_id = self.item_id or payload_item
        self.operation_run_id = self.operation_run_id or payload_run
        return self


def validate_event(value: Any) -> EventEnvelope:
    if not isinstance(value, dict):
        raise TraceQError("INVALID_EVENT", "Event must be a JSON object", 422)
    event_type = value.get("event_type")
    version = value.get("schema_version")
    if (event_type, version) not in SCHEMA_REGISTRY and version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TraceQError("UNSUPPORTED_SCHEMA_VERSION", "Unsupported event schema version", 422)
    if (event_type, version) not in SCHEMA_REGISTRY and event_type in SUPPORTED_EVENT_TYPES:
        raise TraceQError("UNSUPPORTED_SCHEMA_VERSION", "Unsupported event schema version", 422)
    payload_model = PAYLOAD_MODELS.get(event_type)
    if payload_model is None:
        raise TraceQError("UNSUPPORTED_EVENT_TYPE", "Unsupported event type", 422)
    candidate = dict(value)
    try:
        candidate["payload"] = payload_model.model_validate(value.get("payload"))
        return EventEnvelope.model_validate(candidate)
    except ValidationError as exc:
        semantic = any("SEMANTIC_VALIDATION_ERROR" in str(error.get("msg")) for error in exc.errors())
        code = "SEMANTIC_VALIDATION_ERROR" if semantic else "EVENT_SCHEMA_VALIDATION_ERROR"
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        )
        raise TraceQError(code, f"Event validation failed: {details}", 422) from exc


def canonical_event_dict(event: EventEnvelope) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude_none=False)


def data_quality_warnings(event: EventEnvelope) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if isinstance(event.payload, OperationFinishedPayload) and event.payload.duration:
        seconds = event.payload.duration.value
        factor = {"ms": 0.001, "s": 1, "min": 60, "h": 3600}[event.payload.duration.unit]
        if seconds * factor > 4 * 3600:
            warnings.append(
                {
                    "code": "SUSPICIOUS_DURATION",
                    "message": "Reported operation duration exceeds four hours",
                }
            )
    return warnings
