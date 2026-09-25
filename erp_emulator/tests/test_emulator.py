from __future__ import annotations

from fastapi.testclient import TestClient

from erp_emulator.app.main import app, state


client = TestClient(app)


def test_quality_result_delivery_is_idempotent() -> None:
    state.reset()
    payload = {
        "message_id": "TEST-MESSAGE-1",
        "item_id": "ITEM-1",
        "nonconformance_id": "NC-1",
        "decision_id": "D-1",
        "verdict": "confirmed",
        "disposition": "REWORK_REQUIRED",
        "containment": "HOLD",
        "decided_at": "2026-09-25T10:00:00Z",
    }
    first = client.post("/api/v1/quality-results", json=payload)
    second = client.post("/api/v1/quality-results", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["external_result_id"] == second.json()["external_result_id"]
    assert len(state.deliveries) == 1


def test_reject_mode_returns_permanent_400() -> None:
    state.reset()
    client.put("/api/v1/demo/behavior", json={"mode": "REJECT_400"})
    response = client.post(
        "/api/v1/quality-results",
        json={
            "message_id": "TEST-MESSAGE-2",
            "item_id": "ITEM-1",
            "nonconformance_id": "NC-1",
            "decision_id": "D-1",
            "verdict": "confirmed",
            "disposition": "REWORK_REQUIRED",
            "containment": "HOLD",
            "decided_at": "2026-09-25T10:00:00Z",
        },
    )
    assert response.status_code == 400
