from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select


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


def _controller_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "controller", "password": "controller-demo"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _reset_and_run(client: TestClient, headers: dict[str, str], scenario: str) -> None:
    reset = client.post("/api/v1/demo/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    result = client.post(f"/api/v1/demo/scenarios/{scenario}/run", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["passed"] is True


def _counts(item_id: str) -> tuple[int, int, int]:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import (
        AnalysisVersion,
        DefectOccurrence,
        Nonconformance,
    )

    db = SessionLocal()
    try:
        occurrence_count = db.scalar(
            select(func.count(DefectOccurrence.id)).where(
                DefectOccurrence.item_id == item_id
            )
        )
        ncr_count = db.scalar(
            select(func.count(Nonconformance.id)).where(
                Nonconformance.item_id == item_id
            )
        )
        analysis_count = db.scalar(
            select(func.count(AnalysisVersion.id)).where(
                AnalysisVersion.item_id == item_id
            )
        )
        return int(occurrence_count or 0), int(ncr_count or 0), int(analysis_count or 0)
    finally:
        db.close()


def _rebuild(item_id: str, repeats: int = 1) -> None:
    from backend.app.persistence.database import SessionLocal
    from backend.app.projections.rebuild import rebuild_item
    from backend.app.settings import get_settings

    for _ in range(repeats):
        db = SessionLocal()
        try:
            rebuild_item(db, item_id, get_settings())
        finally:
            db.close()


def _post_defect(
    client: TestClient,
    *,
    item_id: str,
    event_id: str,
    sequence: int,
    occurred_at: str,
    defect_type: str,
    operation_run_id: str,
) -> None:
    from backend.app.settings import get_settings

    token = get_settings().source_demo_token
    assert token is not None
    response = client.post(
        "/api/v1/events",
        headers={
            "X-Source-Id": "VISION-01",
            "X-Source-Token": token.get_secret_value(),
        },
        json={
            "event_id": event_id,
            "event_type": "inspection.result",
            "schema_version": "1.0",
            "occurred_at": occurred_at,
            "source": {
                "source_id": "VISION-01",
                "source_type": "vision_qc",
                "sequence": sequence,
            },
            "payload": {
                "inspection_result": "defect_detected",
                "observation_quality": "good",
                "control_point_id": "CP-POST-GRIND",
                "confidence": 0.96,
                "inspection_scope": {
                    "components": ["COMP-HOUSING-1"],
                    "defect_types": [defect_type],
                },
                "defects": [
                    {
                        "defect_type": defect_type,
                        "component_instance_id": "COMP-HOUSING-1",
                        "severity": "medium",
                        "confidence": 0.96,
                    }
                ],
                "control_device_id": "CAM-02",
                "capture_session_id": f"CAP-{event_id}",
                "evidence_refs": [f"media://vision-01/{event_id}.jpg"],
            },
            "item_id": item_id,
            "operation_run_id": operation_run_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ingestion_status"] == "accepted"
    assert response.json()["projection_status"] == "updated"


def test_closed_occurrence_replay_is_idempotent_and_analysis_is_not_duplicated() -> None:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import DefectOccurrence, Nonconformance

    client = _client()
    headers = _controller_headers(client)
    _reset_and_run(client, headers, "S08")

    db = SessionLocal()
    try:
        occurrence = db.scalar(
            select(DefectOccurrence).where(DefectOccurrence.item_id == "ITEM-S08")
        )
        ncr = db.scalar(
            select(Nonconformance).where(Nonconformance.item_id == "ITEM-S08")
        )
        assert occurrence is not None and occurrence.status == "CLOSED"
        assert ncr is not None and ncr.closed_at is not None
        stable_identity = (occurrence.id, ncr.id, occurrence.first_observation_id)
    finally:
        db.close()

    baseline = _counts("ITEM-S08")
    assert baseline[0:2] == (1, 1)
    _rebuild("ITEM-S08", repeats=5)
    assert _counts("ITEM-S08") == baseline

    db = SessionLocal()
    try:
        occurrence = db.scalar(
            select(DefectOccurrence).where(DefectOccurrence.item_id == "ITEM-S08")
        )
        ncr = db.scalar(
            select(Nonconformance).where(Nonconformance.item_id == "ITEM-S08")
        )
        assert occurrence is not None and ncr is not None
        assert (occurrence.id, ncr.id, occurrence.first_observation_id) == stable_identity
    finally:
        db.close()

    analysis = client.get("/api/v1/items/ITEM-S08/analysis", headers=headers)
    assert analysis.status_code == 200, analysis.text
    assert len(analysis.json()) == 1


def test_new_defect_after_closed_episode_creates_exactly_one_new_occurrence() -> None:
    client = _client()
    headers = _controller_headers(client)
    _reset_and_run(client, headers, "S08")

    _post_defect(
        client,
        item_id="ITEM-S08",
        event_id="EV-S08-SECOND-DEFECT",
        sequence=18,
        occurred_at="2026-09-25T16:30:00Z",
        defect_type="surface_crack",
        operation_run_id="RUN-S08-GRIND-R2",
    )

    assert _counts("ITEM-S08")[0:2] == (2, 2)
    _rebuild("ITEM-S08", repeats=5)
    assert _counts("ITEM-S08")[0:2] == (2, 2)
    analysis = client.get("/api/v1/items/ITEM-S08/analysis", headers=headers)
    assert analysis.status_code == 200, analysis.text
    assert len(analysis.json()) == 2


def test_repeated_defect_observation_inside_open_episode_reuses_occurrence() -> None:
    client = _client()
    headers = _controller_headers(client)
    _reset_and_run(client, headers, "S03")

    _post_defect(
        client,
        item_id="ITEM-S03",
        event_id="EV-S03-REPEAT-DEFECT",
        sequence=7,
        occurred_at="2026-09-25T10:43:00Z",
        defect_type="scratch_or_gouge",
        operation_run_id="RUN-S03-GRIND",
    )

    assert _counts("ITEM-S03")[0:2] == (1, 1)
    _rebuild("ITEM-S03", repeats=5)
    assert _counts("ITEM-S03")[0:2] == (1, 1)
    analysis = client.get("/api/v1/items/ITEM-S03/analysis", headers=headers)
    assert analysis.status_code == 200, analysis.text
    assert len(analysis.json()) == 1
