from __future__ import annotations

import pytest

from backend.app.domain.routes import StepInput, validate_steps
from backend.app.errors import TraceQError


def test_required_control_point_is_validated() -> None:
    with pytest.raises(ValueError):
        StepInput(operation_id="OP1", operation_name="Operation", required=True)


def test_duplicate_operation_is_rejected() -> None:
    steps = [
        StepInput(operation_id="OP1", operation_name="One"),
        StepInput(operation_id="OP1", operation_name="Again"),
    ]
    with pytest.raises(TraceQError) as caught:
        validate_steps(steps)
    assert caught.value.code == "INVALID_ROUTE"
