from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_TESTS") != "1",
        reason="set RUN_POSTGRES_TESTS=1 against an isolated PostgreSQL demo database",
    ),
]


def _client() -> TestClient:
    from backend.app.main import app

    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _reset(client: TestClient, controller: dict) -> None:
    response = client.post("/api/v1/demo/reset", headers=_headers(controller))
    assert response.status_code == 200, response.text


def _add_observation(
    db,
    *,
    item_id: str,
    occurred_at: datetime,
    result: str,
    trust_status: str,
    station_id: str,
    defect_type: str | None = None,
    item_status: str = "IN_PROCESS",
) -> None:
    from backend.app.persistence.models import (
        DefectObservation,
        Item,
        Observation,
        OperationRun,
    )

    run_id = f"RUN-{item_id}"
    db.add(
        Item(
            item_id=item_id,
            product_definition_id="PD-LIVE",
            revision="A",
            line_id="LINE-LIVE",
            status=item_status,
            registered_at=occurred_at - timedelta(minutes=5),
        )
    )
    db.add(
        OperationRun(
            operation_run_id=run_id,
            item_id=item_id,
            station_id=station_id,
            started_at=occurred_at - timedelta(minutes=2),
            finished_at=occurred_at - timedelta(minutes=1),
            completion_status="completed",
            run_reason="production",
        )
    )
    observation = Observation(
        id=uuid.uuid4(),
        event_id=f"EV-{item_id}",
        item_id=item_id,
        operation_run_id=run_id,
        occurred_at=occurred_at,
        inspection_result=result,
        observation_quality="good",
        control_point_id=f"CP-{station_id}",
        confidence=0.95,
        inspection_scope={"defect_types": ["*"], "component_instance_ids": ["*"]},
        evidence_refs=[],
        trust_status=trust_status,
        trust_reasons=[],
    )
    db.add(observation)
    db.flush()
    if defect_type:
        db.add(
            DefectObservation(
                observation_id=observation.id,
                item_id=item_id,
                defect_type=defect_type,
                severity="medium",
            )
        )


def _add_ncr(db, *, item_id: str, occurred_at: datetime, verdict: str, disposition: str) -> None:
    from backend.app.persistence.models import DefectOccurrence, Nonconformance, Observation

    observation = db.query(Observation).filter_by(item_id=item_id).one()
    occurrence = DefectOccurrence(
        id=uuid.uuid4(),
        item_id=item_id,
        defect_type="surface_crack",
        first_observation_id=observation.id,
        current_observation_id=observation.id,
        status="OPEN",
        opened_at=occurred_at,
    )
    db.add(occurrence)
    db.flush()
    db.add(
        Nonconformance(
            occurrence_id=occurrence.id,
            item_id=item_id,
            defect_type="surface_crack",
            verdict=verdict,
            disposition=disposition,
            containment="HOLD" if disposition == "REWORK_REQUIRED" else "REVIEW_REQUIRED",
            opened_at=occurred_at,
        )
    )


def test_rt01_empty_rt11_validation_and_rt12_permission() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    manager = _login(client, "manager", "manager-demo")
    _reset(client, controller)

    response = client.get(
        "/api/v1/analytics/live-quality", headers=_headers(manager)
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["window"] == "1h"
    assert value["inspections"] == {
        "total": 0,
        "trusted_good": 0,
        "trusted_defect": 0,
    }
    assert value["quality"] == {
        "confirmed_ncr": 0,
        "pending_review": 0,
        "rework_required": 0,
        "released": 0,
        "first_pass_yield": None,
    }
    assert value["stations"] == []
    assert value["defects_by_type"] == []
    assert value["equipment_context"] == []
    assert value["recent_activity"] == []
    assert value["timeline"]
    assert all(row["good"] == row["defect"] == 0 for row in value["timeline"])

    invalid = client.get(
        "/api/v1/analytics/live-quality?window=banana", headers=_headers(manager)
    )
    assert 400 <= invalid.status_code < 500
    forbidden = client.get(
        "/api/v1/analytics/live-quality", headers=_headers(controller)
    )
    assert forbidden.status_code == 403


def test_rt02_through_rt10_aggregates_trusted_projection_facts() -> None:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import MachineEvent

    client = _client()
    controller = _login(client, "controller", "controller-demo")
    manager = _login(client, "manager", "manager-demo")
    _reset(client, controller)
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        _add_observation(
            db,
            item_id="LIVE-GOOD",
            occurred_at=now - timedelta(minutes=10),
            result="no_defect",
            trust_status="TRUSTED",
            station_id="ST-LIVE-A",
            item_status="RELEASED",
        )
        for item_id, verdict, disposition, minutes in (
            ("LIVE-PENDING", "pending_review", "IN_PROCESS", 9),
            ("LIVE-CONFIRMED", "confirmed", "REWORK_REQUIRED", 8),
            ("LIVE-REJECTED", "rejected", "IN_PROCESS", 7),
        ):
            _add_observation(
                db,
                item_id=item_id,
                occurred_at=now - timedelta(minutes=minutes),
                result="defect_detected",
                trust_status="TRUSTED",
                station_id="ST-LIVE-B",
                defect_type="surface_crack",
            )
            _add_ncr(
                db,
                item_id=item_id,
                occurred_at=now - timedelta(minutes=minutes),
                verdict=verdict,
                disposition=disposition,
            )
        for index, trust_status in enumerate(
            ("UNTRUSTED", "UNASSESSABLE", "CONFLICTED", "INVALIDATED"), start=1
        ):
            _add_observation(
                db,
                item_id=f"LIVE-{trust_status}",
                occurred_at=now - timedelta(minutes=index),
                result="defect_detected",
                trust_status=trust_status,
                station_id="ST-LIVE-C",
                defect_type="dent_or_deformation",
            )
        _add_observation(
            db,
            item_id="LIVE-OLD",
            occurred_at=now - timedelta(hours=2),
            result="defect_detected",
            trust_status="TRUSTED",
            station_id="ST-LIVE-OLD",
            defect_type="scratch_or_gouge",
        )
        _add_ncr(
            db,
            item_id="LIVE-OLD",
            occurred_at=now - timedelta(hours=2),
            verdict="confirmed",
            disposition="IN_PROCESS",
        )
        db.add(
            MachineEvent(
                event_id="EV-LIVE-WARNING",
                item_id="LIVE-CONFIRMED",
                operation_run_id="RUN-LIVE-CONFIRMED",
                equipment_id="EQ-LIVE-01",
                state="warning",
                code="VIBRATION_HIGH",
                occurred_at=now - timedelta(minutes=6),
            )
        )
        db.commit()
    finally:
        db.close()

    current = client.get(
        "/api/v1/analytics/live-quality?window=1h", headers=_headers(manager)
    )
    assert current.status_code == 200, current.text
    value = current.json()
    assert value["inspections"] == {
        "total": 8,
        "trusted_good": 1,
        "trusted_defect": 3,
    }
    assert value["quality"] == {
        "confirmed_ncr": 1,
        "pending_review": 1,
        "rework_required": 1,
        "released": 1,
        "first_pass_yield": 0.75,
    }
    station = next(row for row in value["stations"] if row["station_id"] == "ST-LIVE-B")
    assert station["inspected"] == 3
    assert station["trusted_defect"] == 3
    assert station["defect_signal_rate"] == 1.0
    assert value["defects_by_type"] == [{"defect_type": "surface_crack", "count": 3}]
    assert value["equipment_context"] == [{"equipment_id": "EQ-LIVE-01", "warnings": 1}]
    assert any(row["kind"] == "equipment_warning" for row in value["recent_activity"])
    assert not any("root" in key.lower() or "cause" in key.lower() for key in value)

    wider = client.get(
        "/api/v1/analytics/live-quality?window=24h", headers=_headers(manager)
    ).json()
    assert wider["inspections"]["total"] == 9
    assert wider["inspections"]["trusted_defect"] == 4
    assert wider["quality"]["confirmed_ncr"] == 2
    assert any(row["station_id"] == "ST-LIVE-OLD" for row in wider["stations"])


def test_rt13_fpy_parity_with_canonical_kpi() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    manager = _login(client, "manager", "manager-demo")
    _reset(client, controller)
    scenario = client.post(
        "/api/v1/demo/scenarios/S03/run", headers=_headers(controller)
    )
    assert scenario.status_code == 200, scenario.text

    live = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    )
    kpi = client.get("/api/v1/analytics/kpi", headers=_headers(manager))
    assert live.status_code == kpi.status_code == 200
    assert live.json()["quality"]["first_pass_yield"] == kpi.json()["first_pass_yield"]


def test_rt14_duplicate_and_rt15_late_event_are_stable_by_business_time() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    manager = _login(client, "manager", "manager-demo")

    duplicate = client.post(
        "/api/v1/demo/scenarios/S06/run", headers=_headers(controller)
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["passed"] is True
    duplicate_snapshot = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert duplicate_snapshot["inspections"] == {
        "total": 1,
        "trusted_good": 1,
        "trusted_defect": 0,
    }

    late = client.post(
        "/api/v1/demo/scenarios/S07/run", headers=_headers(controller)
    )
    assert late.status_code == 200, late.text
    assert late.json()["passed"] is True
    late_snapshot = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert late_snapshot["inspections"] == {
        "total": 1,
        "trusted_good": 1,
        "trusted_defect": 1,
    }
    assert [row["bucket"] for row in late_snapshot["timeline"]] == sorted(
        row["bucket"] for row in late_snapshot["timeline"]
    )


def test_realtime_demo_proof_keeps_signal_decision_rework_and_release_distinct() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    manager = _login(client, "manager", "manager-demo")

    _reset(client, controller)
    initial = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert initial["inspections"]["total"] == 0

    scenario = client.post(
        "/api/v1/demo/scenarios/S03/run", headers=_headers(controller)
    )
    assert scenario.status_code == 200, scenario.text
    signal = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert signal["inspections"] == {
        "total": 1,
        "trusted_good": 1,
        "trusted_defect": 1,
    }
    assert signal["quality"]["confirmed_ncr"] == 0
    assert signal["quality"]["pending_review"] == 1
    assert signal["equipment_context"] == [{"equipment_id": "CNC-04", "warnings": 1}]

    ncr = client.get(
        "/api/v1/nonconformances", headers=_headers(controller)
    ).json()[0]
    decision = client.post(
        f"/api/v1/nonconformances/{ncr['id']}/decision",
        headers=_headers(controller),
        json={
            "verdict": "confirmed",
            "disposition": "REWORK_REQUIRED",
            "containment": "HOLD",
            "reason": "Confirmed for realtime dashboard proof",
        },
    )
    assert decision.status_code == 200, decision.text
    confirmed = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert confirmed["quality"]["confirmed_ncr"] == 1
    assert confirmed["quality"]["rework_required"] == 1

    released_scenario = client.post(
        "/api/v1/demo/scenarios/S08/run", headers=_headers(controller)
    )
    assert released_scenario.status_code == 200, released_scenario.text
    assert released_scenario.json()["passed"] is True
    released = client.get(
        "/api/v1/analytics/live-quality?window=all", headers=_headers(manager)
    ).json()
    assert released["quality"]["released"] == 1
    assert released["quality"]["rework_required"] == 0
    assert released["quality"]["confirmed_ncr"] == 1
