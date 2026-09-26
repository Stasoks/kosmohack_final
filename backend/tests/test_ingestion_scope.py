from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.errors import TraceQError
from backend.app.ingestion.service import _enforce_source_scope, _resolve_event_scope
from backend.app.persistence.models import Equipment, Item, OperationRun, Station


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def get(self, model, key):
        return self.rows.get((model, key))


def test_source_scope_is_resolved_from_item_and_operation_context() -> None:
    db = FakeSession({
        (OperationRun, "RUN-1"): SimpleNamespace(item_id="ITEM-1", station_id="ST-1"),
        (Item, "ITEM-1"): SimpleNamespace(line_id="LINE-A"),
    })
    event = SimpleNamespace(item_id="ITEM-1", operation_run_id="RUN-1")
    assert _resolve_event_scope(db, event, {}) == ("LINE-A", "ST-1")


def test_machine_scope_can_be_resolved_from_equipment() -> None:
    db = FakeSession({
        (Equipment, "EQ-1"): SimpleNamespace(station_id="ST-2"),
        (Station, "ST-2"): SimpleNamespace(line_id="LINE-B"),
    })
    event = SimpleNamespace(item_id=None, operation_run_id=None)
    assert _resolve_event_scope(db, event, {"equipment_id": "EQ-1"}) == ("LINE-B", "ST-2")


def test_scoped_source_fails_closed_when_context_is_unknown() -> None:
    db = FakeSession({})
    source = SimpleNamespace(allowed_line_ids=["LINE-A"], allowed_station_ids=[])
    event = SimpleNamespace(item_id="UNKNOWN", operation_run_id=None)
    with pytest.raises(TraceQError) as caught:
        _enforce_source_scope(db, source, event, {})
    assert caught.value.code == "SOURCE_SCOPE_VIOLATION"


def test_scoped_source_rejects_resolved_foreign_station() -> None:
    db = FakeSession({
        (OperationRun, "RUN-1"): SimpleNamespace(item_id="ITEM-1", station_id="ST-9"),
        (Item, "ITEM-1"): SimpleNamespace(line_id="LINE-A"),
    })
    source = SimpleNamespace(allowed_line_ids=["LINE-A"], allowed_station_ids=["ST-1"])
    event = SimpleNamespace(item_id="ITEM-1", operation_run_id="RUN-1")
    with pytest.raises(TraceQError) as caught:
        _enforce_source_scope(db, source, event, {})
    assert caught.value.code == "SOURCE_SCOPE_VIOLATION"
