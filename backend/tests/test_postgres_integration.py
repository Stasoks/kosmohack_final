from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_TESTS") != "1",
        reason="set RUN_POSTGRES_TESTS=1 against an isolated PostgreSQL demo database",
    ),
]


def _client():
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


def test_demo_vertical_slice_security_and_outbox() -> None:
    from backend.app.persistence.database import engine

    client = _client()
    passwords = {
        "controller": "controller-demo",
        "master": "master-demo",
        "technologist": "technologist-demo",
        "manager": "manager-demo",
        "admin": "admin-demo",
    }
    tokens = {name: _login(client, name, password) for name, password in passwords.items()}

    reset = client.post("/api/v1/demo/reset", headers=_headers(tokens["controller"]))
    assert reset.status_code == 200, reset.text
    scenario = client.post(
        "/api/v1/demo/scenarios/S03/run",
        headers=_headers(tokens["controller"]),
    )
    assert scenario.status_code == 200, scenario.text
    assert scenario.json()["passed"] is True

    analyses = client.get(
        "/api/v1/items/ITEM-S03/analysis", headers=_headers(tokens["controller"])
    )
    assert analyses.status_code == 200
    assert analyses.json()[0]["versions"][-1]["status"] == "BOUNDED"
    evidence = analyses.json()[0]["versions"][-1]["evidence"]
    assert {row["type"] for row in evidence} >= {
        "LAST_TRUSTED_GOOD",
        "FIRST_TRUSTED_DEFECT",
        "OPERATION_IN_WINDOW",
    }
    timeline = client.get(
        "/api/v1/items/ITEM-S03/timeline", headers=_headers(tokens["controller"])
    )
    assert timeline.status_code == 200, timeline.text
    assert timeline.json()["events"]  # backward-compatible raw timeline remains available
    assert {row["type"] for row in timeline.json()["activity"]} >= {
        "item_registered",
        "inspection_result",
        "nonconformance_opened",
    }

    ncrs = client.get("/api/v1/nonconformances", headers=_headers(tokens["controller"])).json()
    ncr_id = ncrs[0]["id"]
    forbidden = client.post(
        f"/api/v1/nonconformances/{ncr_id}/decision",
        headers=_headers(tokens["admin"]),
        json={
            "verdict": "confirmed",
            "disposition": "REWORK_REQUIRED",
            "containment": "HOLD",
            "reason": "Admin must never be accepted as a quality controller",
        },
    )
    assert forbidden.status_code == 403

    decision = client.post(
        f"/api/v1/nonconformances/{ncr_id}/decision",
        headers=_headers(tokens["controller"]),
        json={
            "verdict": "confirmed",
            "disposition": "REWORK_REQUIRED",
            "containment": "HOLD",
            "reason": "Trusted defect requires controlled rework",
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["outbox_state"] is None
    assert decision.json()["message_id"] is None

    decided_timeline = client.get(
        "/api/v1/items/ITEM-S03/timeline", headers=_headers(tokens["controller"])
    ).json()
    assert "controller_decision" in {row["type"] for row in decided_timeline["activity"]}

    with engine.connect() as connection:
        ciphertext = connection.scalar(
            text("SELECT payload_ciphertext FROM raw_events WHERE event_id='EV-S03-001'")
        )
        assert ciphertext is not None
        assert b"ITEM-S03" not in bytes(ciphertext)
        outbox_count = connection.scalar(text("SELECT count(*) FROM outbox_messages"))
        assert outbox_count == 0  # defect/rework signals never bypass controlled release

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE raw_events SET event_type='tampered' WHERE event_id='EV-S03-001'")
            )


def test_timeline_activity_includes_rework_and_verification_decisions() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    headers = _headers(controller)
    reset = client.post("/api/v1/demo/reset", headers=headers)
    assert reset.status_code == 200, reset.text

    scenario = client.post("/api/v1/demo/scenarios/S08/run", headers=headers)
    assert scenario.status_code == 200, scenario.text
    assert scenario.json()["passed"] is True

    response = client.get("/api/v1/items/ITEM-S08/timeline", headers=headers)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["events"]
    activity_types = {row["type"] for row in value["activity"]}
    assert {
        "controller_decision",
        "rework_started",
        "rework_finished",
        "rework_verification",
        "final_disposition",
    } <= activity_types


def test_timeline_activity_exposes_effective_coverage_per_defect_key() -> None:
    client = _client()
    controller = _login(client, "controller", "controller-demo")
    headers = _headers(controller)
    reset = client.post("/api/v1/demo/reset", headers=headers)
    assert reset.status_code == 200, reset.text

    scenario = client.post("/api/v1/demo/scenarios/S12/run", headers=headers)
    assert scenario.status_code == 200, scenario.text
    assert scenario.json()["passed"] is True

    response = client.get("/api/v1/items/ITEM-S12/timeline", headers=headers)
    assert response.status_code == 200, response.text
    first_inspection = next(
        row for row in response.json()["activity"] if row["event_id"] == "EV-S12-002"
    )
    coverage = {
        row["defect_type"]: row["coverage"]
        for row in first_inspection["details"]["coverage"]
    }
    assert coverage == {
        "scratch_or_gouge": "FULL",
        "surface_crack": "PARTIAL",
    }



def test_blast_radius_requires_human_approval_before_application() -> None:
    from backend.app.persistence.database import engine

    client = _client()
    controller = _login(client, "controller", "controller-demo")
    response = client.post(
        "/api/v1/demo/scenarios/S18/run",
        headers=_headers(controller),
    )
    assert response.status_code == 200, response.text
    scenario_result = response.json()
    assert scenario_result["passed"] is True
    assert scenario_result["actual"]["automatic_defect_assignment"] is False
    assert scenario_result["actual"]["automatic_containment_application"] is False

    approvals = client.get(
        "/api/v1/risk/approvals",
        headers=_headers(controller),
    )
    assert approvals.status_code == 200, approvals.text
    rows = approvals.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "PENDING"

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM containment_applications")) == 0

    approved = client.post(
        f"/api/v1/risk/approvals/{rows[0]['id']}/approve",
        headers=_headers(controller),
        json={"reason": "Reviewed affected population and approved containment"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert set(approved.json()["applied_items"]) == {
        "ITEM-S18-A",
        "ITEM-S18-B",
        "ITEM-S18-C",
    }

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM containment_applications")) == 3


def test_route_import_activation_supersedes_previous_revision() -> None:
    client = _client()
    technologist = _login(client, "technologist", "technologist-demo")
    headers = _headers(technologist)
    route_code = "AUDIT-ROUTE-IMPORT"

    first = client.post(
        "/api/v1/routes/import",
        headers=headers,
        json={
            "code": route_code,
            "name": "Audit route import",
            "activate": True,
            "steps": [
                {
                    "operation_id": "AUDIT-OP-1",
                    "operation_name": "Audit operation 1",
                    "station_id": "ST-01",
                }
            ],
        },
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/v1/routes/import",
        headers=headers,
        json={
            "code": route_code,
            "name": "Audit route import",
            "activate": True,
            "steps": [
                {
                    "operation_id": "AUDIT-OP-2",
                    "operation_name": "Audit operation 2",
                    "station_id": "ST-02",
                }
            ],
        },
    )
    assert second.status_code == 200, second.text

    route_id = first.json()["route_id"]
    details = client.get(f"/api/v1/routes/{route_id}", headers=headers)
    assert details.status_code == 200, details.text
    statuses = [
        (row["revision"], row["status"])
        for row in details.json()["revisions"]
    ]
    assert statuses == [(1, "superseded"), (2, "active")]


def test_real_outbox_worker_retries_then_delivers_same_message(monkeypatch) -> None:
    import httpx

    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import IntegrationHealth, OutboxMessage
    from backend.app.security.crypto import utcnow
    from worker import main as worker_main

    client = _client()
    controller = _login(client, "controller", "controller-demo")
    response = client.post(
        "/api/v1/demo/scenarios/S22/run",
        headers=_headers(controller),
    )
    assert response.status_code == 200, response.text
    assert response.json()["passed"] is True

    db = SessionLocal()
    try:
        message = db.query(OutboxMessage).one()
        original_message_id = message.message_id
    finally:
        db.close()

    def fail_once(self, payload):
        raise httpx.ConnectError("simulated ERP outage")

    monkeypatch.setattr(worker_main.EmulatorAdapter, "send_quality_result", fail_once)
    assert worker_main.process_one() is True

    db = SessionLocal()
    try:
        message = db.query(OutboxMessage).one()
        assert message.message_id == original_message_id
        assert message.state == "RETRYING"
        assert message.attempts == 1
        health = db.get(IntegrationHealth, "erp-emulator")
        assert health is not None
        assert health.status == "UNHEALTHY"
        message.next_attempt_at = utcnow()
        db.commit()
    finally:
        db.close()

    def ack(self, payload):
        return {"message_id": payload["message_id"], "status": "ACK"}

    monkeypatch.setattr(worker_main.EmulatorAdapter, "send_quality_result", ack)
    assert worker_main.process_one() is True

    db = SessionLocal()
    try:
        message = db.query(OutboxMessage).one()
        assert message.message_id == original_message_id
        assert message.state == "DELIVERED"
        assert message.attempts == 2
        health = db.get(IntegrationHealth, "erp-emulator")
        assert health is not None
        assert health.status == "HEALTHY"
    finally:
        db.close()
