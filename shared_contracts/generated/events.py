"""Generated from contracts/events/canonical-event.schema.json. Do not edit."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(ContractModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=64)
    sequence: int | None = Field(default=None, ge=0)

class Duration(ContractModel):
    value: float = Field(ge=0)
    unit: Literal['ms', 's', 'min', 'h']
    meaning: str = Field(min_length=1, max_length=64)

class Defect(ContractModel):
    defect_type: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    severity: str | None = Field(default=None, max_length=32)
    component_instance_id: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0, le=1)

class ItemRegisteredPayload(ContractModel):
    product_definition_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    line_id: str | None = Field(default=None)
    route_id: str | None = Field(default=None)
    route_revision: int | str | None = Field(default=None)

class OperationStartedPayload(ContractModel):
    operation_id: str
    operator_id: str
    equipment_id: str
    station_id: str
    parameters: dict[str, Any] | None = Field(default=None)
    previous_operation_run_id: str | None = Field(default=None)
    run_reason: Literal['production', 'rework'] = Field(default='production')
    rework_for_nonconformance_id: str | None = Field(default=None)

class OperationFinishedPayload(ContractModel):
    completion_status: Literal['completed', 'failed', 'aborted', 'interrupted']
    duration: Duration | None = Field(default=None)
    stop_reason: str | None = Field(default=None)
    parameters: dict[str, Any] | None = Field(default=None)

class InspectionResultPayload(ContractModel):
    inspection_result: Literal['no_defect', 'defect_detected', 'impossible_to_assess']
    observation_quality: Literal['good', 'poor', 'unknown']
    control_point_id: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    inspection_scope: dict[str, Any] | list[Any] | None = Field(default=None)
    defects: list[Defect] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    component_instance_id: str | None = Field(default=None)
    control_device_id: str | None = Field(default=None)
    capture_session_id: str | None = Field(default=None)

class MachineStatePayload(ContractModel):
    equipment_id: str
    state: str
    code: str | None = Field(default=None)
    parameters: dict[str, Any] | None = Field(default=None)

class OperatorActionPayload(ContractModel):
    operator_id: str
    action_type: str
    parameters: dict[str, Any] | None = Field(default=None)

class ControlDeviceInvalidatedPayload(ContractModel):
    device_id: str = Field(min_length=1, max_length=128)
    affected_from: datetime
    affected_to: datetime
    reason: str = Field(min_length=3, max_length=2000)
    invalidation_type: str | None = Field(default=None, max_length=64)
    supporting_evidence_refs: list[str] = Field(default_factory=list, max_length=100)


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
