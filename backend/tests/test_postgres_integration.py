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



def test_blast_radius_requires_human_approval_before_application() -> None:
    from backend.app.persistence.database import engine

    client = _client()
    controller = _login(client, "controller", "controller-demo")
    response = client.post(
        "/api/v1/demo/scenarios/S18/run",
        headers=_headers(controller),
    )
    assert response.status_code == 200, response.text
    assert response.json()["passed"] is True

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
