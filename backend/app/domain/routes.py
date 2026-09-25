from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

from backend.app.errors import TraceQError


class StepInput(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    operation_name: str = Field(min_length=1, max_length=255)
    control_point_id: str | None = Field(default=None, max_length=128)
    required: bool = False
    inspection_scope: dict | list | None = None
    trust_policy_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def required_has_control_point(self) -> "StepInput":
        if self.required and not self.control_point_id:
            raise ValueError("required inspection needs control_point_id")
        return self


def validate_steps(steps: list[StepInput]) -> None:
    operations = [step.operation_id for step in steps]
    if len(operations) != len(set(operations)):
        raise TraceQError("INVALID_ROUTE", "Operation IDs must be unique within a revision", 422)
    control_points = [step.control_point_id for step in steps if step.control_point_id]
    if len(control_points) != len(set(control_points)):
        raise TraceQError("INVALID_ROUTE", "Control point IDs must be unique within a revision", 422)
