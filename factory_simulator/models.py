from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class SimulationMode(StrEnum):
    NORMAL = "normal"
    DEFECT_REWORK = "defect_rework"
    EQUIPMENT_ISSUE = "equipment_issue"


class SessionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_CONTROLLER = "waiting_for_controller"
    WAITING_FOR_RELEASE = "waiting_for_release"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class RouteStepSnapshot(BaseModel):
    position: int
    operation_id: str
    operation_name: str
    station_id: str
    control_point_id: str | None = None
    required: bool = False
    inspection_scope: dict[str, Any] | list[Any] | None = None


class RouteSnapshot(BaseModel):
    route_id: UUID
    route_code: str
    revision_id: UUID
    revision: int
    steps: list[RouteStepSnapshot]


class ItemSimulationState(BaseModel):
    item_id: str
    item_index: int
    step_index: int = 0
    phase: str = "register"
    current_run_id: str | None = None
    production_run_id: str | None = None
    nonconformance_id: str | None = None
    active_defects: list[str] = Field(default_factory=list)
    equipment_history: list[dict[str, Any]] = Field(default_factory=list)
    operation_history: list[dict[str, Any]] = Field(default_factory=list)
    waiting_reason: str | None = None
    rework_count: int = 0
    defect_injected: bool = False
    equipment_warning_sent: bool = False
    completed: bool = False


class FeedEntry(BaseModel):
    at: datetime
    item_id: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    status: str
    message: str


class SimulationSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    mode: SimulationMode
    status: SessionStatus = SessionStatus.CREATED
    route: RouteSnapshot
    items: list[ItemSimulationState]
    interval_seconds: float = 2.0
    seed: int = 2026
    defect_item_index: int | None = None
    defect_step_index: int | None = None
    generation: int = 1
    event_counter: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: str | None = None
    feed: list[FeedEntry] = Field(default_factory=list)


class SessionCreate(BaseModel):
    route_code: str = "ROUTE-DEFAULT"
    item_count: int = Field(default=3, ge=1, le=20)
    mode: SimulationMode = SimulationMode.NORMAL
    interval_seconds: float = Field(default=2.0, ge=0.2, le=60.0)
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def equipment_issue_needs_shared_population(self) -> "SessionCreate":
        if self.mode == SimulationMode.EQUIPMENT_ISSUE and self.item_count < 3:
            raise ValueError("equipment_issue mode requires at least 3 items")
        return self
