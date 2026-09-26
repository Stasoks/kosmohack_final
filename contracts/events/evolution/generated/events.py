"""Generated from contracts/events/evolution/canonical-event-1.1-demo.schema.json. Do not edit."""
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

class Defect(ContractModel):
    defect_type: str = Field(min_length=1, max_length=128)
    component_instance_id: str | None = Field(default=None)

class InspectionResultPayload(ContractModel):
    inspection_result: Literal['no_defect', 'defect_detected', 'impossible_to_assess']
    observation_quality: Literal['good', 'poor', 'unknown']
    control_point_id: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    inspection_scope: dict[str, Any] | list[Any] | None = Field(default=None)
    defects: list[Defect] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    analyzer_version: str | None = Field(default=None, max_length=128)


EVENT_TYPES = ('inspection.result',)
SCHEMA_REGISTRY = frozenset((('inspection.result', '1.1'),))
PAYLOAD_MODELS = {
    "inspection.result": InspectionResultPayload,
}
