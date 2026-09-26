from uuid import uuid4

from backend.app.domain.events import validate_event
from factory_simulator.engine import SimulationEngine
from factory_simulator.models import (
    ItemSimulationState,
    RouteSnapshot,
    RouteStepSnapshot,
    SimulationMode,
)
from shared_contracts.generated.events import PAYLOAD_MODELS


def _route() -> RouteSnapshot:
    return RouteSnapshot(
        route_id=uuid4(),
        route_code="ROUTE-DEFAULT",
        revision_id=uuid4(),
        revision=1,
        steps=[
            RouteStepSnapshot(
                position=1,
                operation_id="OP-TURN",
                operation_name="Механическая обработка",
                station_id="ST-20",
                control_point_id="CP-AFTER-TURN",
                required=True,
                inspection_scope={"defect_types": ["*"], "component_instance_ids": ["*"]},
            )
        ],
    )


def test_normal_mode_builds_canonical_events_without_source_sequence() -> None:
    engine = SimulationEngine()
    session = engine.create_session(
        _route(), item_count=1, mode=SimulationMode.NORMAL, interval_seconds=1
    )
    item = engine.next_item(session)
    assert item is not None

    events = []
    while not item.completed:
        event = engine.advance(session, item)
        if event:
            events.append(event)

    assert [row["event_type"] for row in events] == [
        "item.registered",
        "operator.action",
        "operation.started",
        "operation.finished",
        "inspection.result",
    ]
    for event in events:
        assert "sequence" not in event["source"]
        assert event["schema_version"] == "1.0"
        PAYLOAD_MODELS[event["event_type"]](**event["payload"])
        validate_event(event)


def test_defect_persists_until_successful_rework_inspection() -> None:
    engine = SimulationEngine()
    session = engine.create_session(
        _route(), item_count=1, mode=SimulationMode.DEFECT_REWORK, interval_seconds=1
    )
    item = engine.next_item(session)
    assert item is not None

    defect_event = None
    while item.phase != "wait_controller":
        defect_event = engine.advance(session, item)
    assert defect_event is not None
    assert defect_event["payload"]["inspection_result"] == "defect_detected"
    assert item.active_defects == ["surface_crack"]

    engine.controller_allowed_rework(item, str(uuid4()))
    assert item.active_defects == ["surface_crack"]
    engine.advance(session, item)  # rework started
    assert item.active_defects == ["surface_crack"]
    engine.advance(session, item)  # rework finished
    assert item.active_defects == []
    repeat = engine.advance(session, item)
    assert repeat is not None
    assert repeat["payload"]["inspection_result"] == "no_defect"
    assert item.active_defects == []
    assert item.phase == "wait_release"


def test_failed_rework_does_not_remove_physical_defect() -> None:
    item = ItemSimulationState(
        item_id="SIM-FAILED-001",
        item_index=1,
        active_defects=["surface_crack"],
    )

    SimulationEngine.apply_rework_result(item, successful=False)

    assert item.active_defects == ["surface_crack"]


def test_inspection_observes_but_never_removes_physical_defect() -> None:
    engine = SimulationEngine()
    session = engine.create_session(
        _route(), item_count=1, mode=SimulationMode.NORMAL, interval_seconds=1
    )
    item = session.items[0]
    item.phase = "inspection"
    item.active_defects = ["surface_crack"]

    event = engine.advance(session, item)

    assert event is not None
    assert event["payload"]["inspection_result"] == "defect_detected"
    assert item.active_defects == ["surface_crack"]


def test_current_event_sources_match_seeded_minimal_source_scopes() -> None:
    engine = SimulationEngine()
    session = engine.create_session(
        _route(), item_count=1, mode=SimulationMode.EQUIPMENT_ISSUE, interval_seconds=1
    )
    item = engine.next_item(session)
    assert item is not None
    events = []
    while not item.completed:
        event = engine.advance(session, item)
        if event:
            events.append(event)

    sources = {(row["event_type"], row["source"]["source_id"]) for row in events}
    assert ("item.registered", "MES-01") in sources
    assert ("inspection.result", "VISION-01") in sources
    assert ("machine.state", "EQUIP-GW-01") in sources
    assert ("operator.action", "OPTERM-01") in sources


def test_seed_selects_the_same_defect_item_deterministically() -> None:
    engine = SimulationEngine()
    first = engine.create_session(
        _route(), item_count=7, mode=SimulationMode.DEFECT_REWORK, interval_seconds=1, seed=42
    )
    second = engine.create_session(
        _route(), item_count=7, mode=SimulationMode.DEFECT_REWORK, interval_seconds=1, seed=42
    )

    assert first.defect_item_index == second.defect_item_index
    assert first.defect_item_index in range(1, 8)


def test_factory_simulator_package_has_no_database_dependency() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
        if path.name != "__init__.py"
    )
    assert "sqlalchemy" not in source.lower()
    assert "backend.app.persistence" not in source
