"""Generated from contracts/events/canonical-event.schema.json. Do not edit."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(ContractModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=64)
    sequence: int | None = Field(default=None, ge=0)


class Duration(ContractModel):
    value: float = Field(ge=0)
    unit: Literal["ms", "s", "min", "h"]
    meaning: str = Field(min_length=1, max_length=64)


class Defect(ContractModel):
    defect_type: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    severity: Literal["minor", "major", "critical"] | None = None
    component_instance_id: str | None = Field(default=None, max_length=128)


class ItemRegisteredPayload(ContractModel):
    product_definition_id: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=64)
    line_id: str | None = Field(default=None, max_length=128)
    route_id: str | None = Field(default=None, max_length=128)
    route_revision: int | None = Field(default=None, ge=1)


class OperationStartedPayload(ContractModel):
    operation_id: str = Field(min_length=1, max_length=128)
    operator_id: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    station_id: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] | None = None
    previous_operation_run_id: str | None = Field(default=None, max_length=128)
    run_reason: Literal["production", "rework"] = "production"
    rework_for_nonconformance_id: str | None = None


class OperationFinishedPayload(ContractModel):
    completion_status: Literal["completed", "failed", "aborted", "interrupted"]
    duration: Duration | None = None
    stop_reason: str | None = Field(default=None, max_length=1000)
    parameters: dict[str, Any] | None = None


class InspectionResultPayload(ContractModel):
    inspection_result: Literal["no_defect", "defect_detected", "impossible_to_assess"]
    observation_quality: Literal["good", "poor", "unknown"]
    control_point_id: str = Field(min_length=1, max_length=128)
    confidence: float | None = Field(default=None, ge=0, le=1)
    inspection_scope: dict[str, Any] | list[Any] | None = None
    defects: list[Defect] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    component_instance_id: str | None = Field(default=None, max_length=128)
    control_device_id: str | None = Field(default=None, max_length=128)
    capture_session_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_defects(self):
        if self.inspection_result == "defect_detected" and not self.defects:
            raise ValueError("defects must not be empty for defect_detected")
        if self.inspection_result != "defect_detected" and self.defects:
            raise ValueError("defects are only allowed for defect_detected")
        return self


class MachineStatePayload(ContractModel):
    equipment_id: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] | None = None


class OperatorActionPayload(ContractModel):
    operator_id: str = Field(min_length=1, max_length=128)
    action_type: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] | None = None


class ControlDeviceInvalidatedPayload(ContractModel):
    device_id: str = Field(min_length=1, max_length=128)
    affected_from: datetime
    affected_to: datetime
    reason: str = Field(min_length=3, max_length=2000)
    invalidation_type: str | None = Field(default=None, max_length=64)
    supporting_evidence_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_period(self):
        if self.affected_to < self.affected_from:
            raise ValueError("affected_to must not be before affected_from")
        return self


EVENT_TYPES = ('control_device.invalidated', 'inspection.result', 'item.registered', 'machine.state', 'operation.finished', 'operation.started', 'operator.action')
SCHEMA_REGISTRY = frozenset((('control_device.invalidated', '1.0'), ('inspection.result', '1.0'), ('item.registered', '1.0'), ('machine.state', '1.0'), ('operation.finished', '1.0'), ('operation.started', '1.0'), ('operator.action', '1.0')))
PAYLOAD_MODELS = {
    "item.registered": ItemRegisteredPayload,
    "operation.started": OperationStartedPayload,
    "operation.finished": OperationFinishedPayload,
    "inspection.result": InspectionResultPayload,
    "machine.state": MachineStatePayload,
    "operator.action": OperatorActionPayload,
    "control_device.invalidated": ControlDeviceInvalidatedPayload,
}
