from uuid import uuid4

from fastapi.testclient import TestClient

from factory_simulator.main import create_app
from factory_simulator.models import RouteSnapshot, RouteStepSnapshot
from factory_simulator.service import SessionManager


class FakeTraceQClient:
    def __init__(self) -> None:
        self.events = []
        self.fail_delivery = False

    async def route_snapshot(self, route_code: str) -> RouteSnapshot:
        return RouteSnapshot(
            route_id=uuid4(),
            route_code=route_code,
            revision_id=uuid4(),
            revision=2,
            steps=[
                RouteStepSnapshot(
                    position=1,
                    operation_id="OP-TURN",
                    operation_name="Обработка",
                    station_id="ST-20",
                    control_point_id="CP-AFTER-TURN",
                    required=True,
                )
            ],
        )

    async def available_routes(self):
        return [
            {
                "code": "ROUTE-DEFAULT",
                "name": "Основной маршрут",
                "revision": 2,
                "step_count": 1,
            }
        ]

    async def publish(self, event):
        if self.fail_delivery:
            raise RuntimeError("simulated delivery failure")
        self.events.append(event)
        return {"ingestion_status": "accepted"}

    async def nonconformances(self):
        return []

    async def item_state(self, item_id: str):
        return {"item_id": item_id, "status": "IN_PROCESS"}


def test_session_api_lifecycle_and_route_snapshot() -> None:
    fake = FakeTraceQClient()
    manager = SessionManager(fake)  # type: ignore[arg-type]
    with TestClient(create_app(manager)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/routes").json()[0]["revision"] == 2
        created = client.post(
            "/sessions",
            json={
                "route_code": "ROUTE-DEFAULT",
                "item_count": 1,
                "mode": "normal",
                "interval_seconds": 1,
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["id"]
        assert created.json()["route"]["revision"] == 2

        stepped = client.post(f"/sessions/{session_id}/step")
        assert stepped.status_code == 200
        assert stepped.json()["event_counter"] == 1
        assert fake.events[0]["event_type"] == "item.registered"

        started = client.post(f"/sessions/{session_id}/start")
        assert started.status_code == 200
        paused = client.post(f"/sessions/{session_id}/pause")
        assert paused.json()["status"] == "paused"
        resumed = client.post(f"/sessions/{session_id}/resume")
        assert resumed.status_code == 200
        stopped = client.post(f"/sessions/{session_id}/stop")
        assert stopped.json()["status"] == "stopped"

        reset = client.post(f"/sessions/{session_id}/reset")
        assert reset.json()["status"] == "created"
        assert reset.json()["event_counter"] == 0

        deleted = client.delete(f"/sessions/{session_id}")
        assert deleted.status_code == 204
        assert client.get(f"/sessions/{session_id}").status_code == 404


def test_delivery_error_is_stored_without_traceback_response() -> None:
    fake = FakeTraceQClient()
    fake.fail_delivery = True
    with TestClient(create_app(SessionManager(fake))) as client:  # type: ignore[arg-type]
        created = client.post(
            "/sessions",
            json={"route_code": "ROUTE-DEFAULT", "item_count": 1, "mode": "normal"},
        ).json()
        result = client.post(f"/sessions/{created['id']}/step")

        assert result.status_code == 200
        assert result.json()["status"] == "error"
        assert "simulated delivery failure" in result.json()["last_error"]


def test_defect_mode_waits_without_controller_decision() -> None:
    fake = FakeTraceQClient()
    with TestClient(create_app(SessionManager(fake))) as client:  # type: ignore[arg-type]
        created = client.post(
            "/sessions",
            json={
                "route_code": "ROUTE-DEFAULT",
                "item_count": 1,
                "mode": "defect_rework",
            },
        ).json()
        session_id = created["id"]
        for _ in range(5):
            value = client.post(f"/sessions/{session_id}/step").json()
        assert value["status"] == "waiting_for_controller"
        before = value["event_counter"]

        waiting = client.post(f"/sessions/{session_id}/step").json()

        assert waiting["status"] == "waiting_for_controller"
        assert waiting["event_counter"] == before
        assert not any("-RW-" in (row.get("operation_run_id") or "") for row in fake.events)
