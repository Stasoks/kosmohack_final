from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.api.risk import control_devices, equipment_issues


class _Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _ReadOnlySession:
    def __init__(self, *, scalar_rows=None, execute_rows=None):
        self.scalar_rows = scalar_rows or []
        self.execute_rows = execute_rows or []

    def scalars(self, _statement):
        return _Rows(self.scalar_rows)

    def execute(self, _statement):
        return _Rows(self.execute_rows)


def test_equipment_issues_endpoint_is_a_read_only_warning_projection() -> None:
    occurred_at = datetime(2026, 9, 26, 11, 27, tzinfo=timezone.utc)
    db = _ReadOnlySession(
        scalar_rows=[
            SimpleNamespace(
                event_id="EV-WARN-1",
                equipment_id="EQ-LATHE-01",
                state="warning",
                code="SIM_VIBRATION_HIGH",
                occurred_at=occurred_at,
                item_id="ITEM-1",
                operation_run_id="RUN-1",
            ),
            SimpleNamespace(
                event_id="EV-WARN-OLDER",
                equipment_id="EQ-LATHE-01",
                state="warning",
                code="SIM_VIBRATION_HIGH",
                occurred_at=occurred_at,
                item_id="ITEM-2",
                operation_run_id="RUN-2",
            ),
        ]
    )

    result = equipment_issues(SimpleNamespace(), db)  # type: ignore[arg-type]

    assert result == [
        {
            "event_id": "EV-WARN-1",
            "equipment_id": "EQ-LATHE-01",
            "state": "warning",
            "code": "SIM_VIBRATION_HIGH",
            "occurred_at": occurred_at,
            "item_id": "ITEM-1",
            "operation_run_id": "RUN-1",
        }
    ]


def test_control_device_catalog_returns_observed_devices_without_writes() -> None:
    first = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)
    last = datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)
    db = _ReadOnlySession(execute_rows=[("SIM-CAMERA-01", first, last, 3)])

    result = control_devices(SimpleNamespace(), db)  # type: ignore[arg-type]

    assert result == [
        {
            "device_id": "SIM-CAMERA-01",
            "first_observed_at": first,
            "last_observed_at": last,
            "observation_count": 3,
        }
    ]
