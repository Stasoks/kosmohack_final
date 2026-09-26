from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.app.persistence.models import ControllerDecision
from backend.app.scenarios.harness import ScenarioBundle, compare_invariants
from backend.app.scenarios.runtime import ScenarioRuntime, automatic_defect_assignment_detected


def test_all_acceptance_scenarios_are_discoverable():
    root = Path(__file__).resolve().parents[2] / "scenarios"
    ids = {path.name.split("_")[0] for path in root.iterdir() if path.is_dir()}
    assert ids == {f"S{index:02d}" for index in range(1, 26)}
    for path in root.iterdir():
        if path.is_dir():
            bundle = ScenarioBundle.load(path)
            assert bundle.expected


def test_demo_scenario_catalog_uses_fixture_metadata_titles() -> None:
    from backend.app.api.demo import scenarios

    catalog = scenarios()

    assert len(catalog) == 25
    assert {row["name"] for row in catalog} == {f"S{index:02d}" for index in range(1, 26)}
    assert all(row["title"] != row["name"] for row in catalog)
    assert next(row for row in catalog if row["name"] == "S08")["title"] == (
        "Успешный rework lifecycle"
    )


def test_expected_is_subset_not_snapshot():
    assert compare_invariants({"ncr": {"open": True, "id": "x"}, "extra": 1}, {"ncr": {"open": True}}) == []


def test_delivery_order_is_preserved(tmp_path):
    scenario = tmp_path / "S00"; scenario.mkdir()
    (scenario / "events.jsonl").write_text('{"event_id":"second"}\n{"event_id":"first"}\n', encoding="utf-8")
    (scenario / "expected.json").write_text('{"ok":true}', encoding="utf-8")
    assert [row["event_id"] for row in ScenarioBundle.load(scenario).events] == ["second", "first"]



def test_harness_executes_event_id_and_dependent_actions(tmp_path):
    scenario = tmp_path / "S98"; scenario.mkdir()
    (scenario / "scenario.json").write_text('{"scenario_id":"S98"}', encoding="utf-8")
    (scenario / "events.jsonl").write_text(
        '{"event_id":"E1"}\n{"event_id":"E2"}\n', encoding="utf-8"
    )
    (scenario / "expected.json").write_text('{"ok":true}', encoding="utf-8")
    (scenario / "actions.json").write_text(
        '[{"after_event_id":"E1","action":"FIRST"},'
        '{"after_action":"FIRST","action":"SECOND"}]',
        encoding="utf-8",
    )
    calls = []
    harness = __import__(
        "backend.app.scenarios.harness", fromlist=["ScenarioHarness"]
    ).ScenarioHarness(
        reset=lambda: calls.append("reset"),
        setup=lambda _: None,
        deliver=lambda row: calls.append(row["event_id"]),
        action=lambda row: calls.append(row["action"]),
        request=lambda _: None,
        erp=lambda _: None,
        route_change=lambda _: None,
        analysis=lambda _: None,
        tamper=lambda _: None,
        normalize=lambda: {"ok": True},
    )
    result = harness.run(ScenarioBundle.load(scenario))
    assert result["scenario"] == "S98"
    assert result["passed"] is True
    assert calls == ["reset", "E1", "FIRST", "SECOND", "E2"]


def test_harness_unwraps_request_and_tamper_step_collections():
    from backend.app.scenarios.harness import ScenarioHarness

    assert ScenarioHarness._rows({"requests": [{"request_id": "R1"}]}) == [{"request_id": "R1"}]
    assert ScenarioHarness._rows({"steps": [{"action": "VERIFY"}]}) == [{"action": "VERIFY"}]


def test_compare_invariants_supports_alternatives_and_forbidden_members():
    assert compare_invariants(401, [401, 403], "$.http_status") == []
    assert compare_invariants([], ["bad claim"], "$.must_not_output") == []
    assert compare_invariants(["bad claim"], ["bad claim"], "$.must_not_output")


def test_s18_automatic_defect_assignment_uses_persistent_ncr_delta() -> None:
    # An NCR that existed before the proposal must not be attributed to Blast Radius.
    assert not automatic_defect_assignment_detected(
        analysis_performed=True,
        ncr_count_before_analysis=1,
        current_ncr_count=1,
    )
    assert automatic_defect_assignment_detected(
        analysis_performed=True,
        ncr_count_before_analysis=1,
        current_ncr_count=2,
    )
    assert not automatic_defect_assignment_detected(
        analysis_performed=False,
        ncr_count_before_analysis=None,
        current_ncr_count=2,
    )


def test_scenario_action_clock_follows_last_fixture_event_deterministically() -> None:
    runtime = ScenarioRuntime.__new__(ScenarioRuntime)
    runtime._last_event_at = datetime(2026, 9, 25, 15, 52, tzinfo=timezone.utc)
    runtime._action_offset = 0

    first = runtime._next_action_at()
    second = runtime._next_action_at()
    next_production_event = datetime(2026, 9, 25, 16, 10, tzinfo=timezone.utc)

    assert first == datetime(2026, 9, 25, 15, 52, 0, 1, tzinfo=timezone.utc)
    assert second == datetime(2026, 9, 25, 15, 52, 0, 2, tzinfo=timezone.utc)
    assert first < second < next_production_event


def test_scenario_decision_clock_sets_timestamp_on_insert_without_update() -> None:
    engine = create_engine("sqlite://")
    ControllerDecision.__table__.create(engine)
    statements: list[str] = []

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    with Session(engine, expire_on_commit=False) as db:
        runtime = ScenarioRuntime.__new__(ScenarioRuntime)
        runtime.db = db
        runtime._last_event_at = datetime(2026, 9, 25, 15, 52, tzinfo=timezone.utc)
        runtime._action_offset = 0
        decision = ControllerDecision(
            nonconformance_id=UUID(int=1),
            user_id=UUID(int=2),
            verdict="confirmed",
            disposition="REWORK_REQUIRED",
            containment="HOLD",
            reason="Scenario controller decision",
            analysis_version=1,
        )

        with runtime._decision_clock():
            db.add(decision)
            db.flush()
        runtime._sync_decision_closure_times(
            {"decision_id": decision.id},
            SimpleNamespace(verification_decision_id=None),
        )

        assert decision.created_at == datetime(
            2026, 9, 25, 15, 52, 0, 1, tzinfo=timezone.utc
        )

    assert any(statement.lstrip().upper().startswith("INSERT") for statement in statements)
    assert not any(
        statement.lstrip().upper().startswith("UPDATE CONTROLLER_DECISIONS")
        for statement in statements
    )


@pytest.mark.postgres
@pytest.mark.skipif(
    __import__("os").getenv("RUN_POSTGRES_TESTS") != "1",
    reason="requires isolated PostgreSQL demo database",
)
def test_all_real_scenarios_execute_through_demo_api():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "controller", "password": "controller-demo"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    failures = {}
    for index in range(1, 26):
        scenario_id = f"S{index:02d}"
        response = client.post(
            f"/api/v1/demo/scenarios/{scenario_id}/run",
            headers=headers,
        )
        assert response.status_code == 200, f"{scenario_id}: {response.text}"
        result = response.json()
        if not result["passed"]:
            failures[scenario_id] = result["failures"]
    assert failures == {}
