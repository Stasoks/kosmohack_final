from __future__ import annotations

from datetime import timedelta
import random
from typing import Any

from factory_simulator.events import canonical_event
from factory_simulator.models import (
    ItemSimulationState,
    RouteSnapshot,
    SessionStatus,
    SimulationMode,
    SimulationSession,
)


class SimulationEngine:
    """Deterministic, in-memory state machine. It never reads or writes TRACE-Q storage."""

    @staticmethod
    def create_session(
        route: RouteSnapshot,
        *,
        item_count: int,
        mode: SimulationMode,
        interval_seconds: float,
        seed: int = 2026,
    ) -> SimulationSession:
        inspected_steps = [
            index for index, step in enumerate(route.steps) if step.required
        ]
        session = SimulationSession(
            mode=mode,
            route=route.model_copy(deep=True),
            items=[],
            interval_seconds=interval_seconds,
            seed=seed,
            defect_item_index=(
                random.Random(seed).randint(1, item_count)
                if mode == SimulationMode.DEFECT_REWORK
                else None
            ),
            defect_step_index=(
                inspected_steps[min(1, len(inspected_steps) - 1)]
                if mode == SimulationMode.DEFECT_REWORK and inspected_steps
                else None
            ),
        )
        prefix = str(session.id).split("-")[0].upper()
        session.items = [
            ItemSimulationState(
                item_id=f"SIM-{prefix}-G1-{index:03d}", item_index=index
            )
            for index in range(1, item_count + 1)
        ]
        return session

    @staticmethod
    def reset(session: SimulationSession) -> None:
        session.generation += 1
        prefix = str(session.id).split("-")[0].upper()
        for item in session.items:
            item.item_id = f"SIM-{prefix}-G{session.generation}-{item.item_index:03d}"
            item.step_index = 0
            item.phase = "register"
            item.current_run_id = None
            item.production_run_id = None
            item.nonconformance_id = None
            item.active_defects = []
            item.equipment_history = []
            item.operation_history = []
            item.waiting_reason = None
            item.rework_count = 0
            item.defect_injected = False
            item.equipment_warning_sent = False
            item.completed = False
        session.status = SessionStatus.CREATED
        session.event_counter = 0
        session.last_error = None
        session.feed = []

    @staticmethod
    def next_item(session: SimulationSession) -> ItemSimulationState | None:
        waiting = {
            "wait_controller": SessionStatus.WAITING_FOR_CONTROLLER,
            "wait_release": SessionStatus.WAITING_FOR_RELEASE,
        }
        waiting_item: ItemSimulationState | None = None
        for item in session.items:
            if item.completed:
                continue
            if item.phase in waiting:
                waiting_item = waiting_item or item
                continue
            session.status = SessionStatus.RUNNING
            return item
        if waiting_item is not None:
            session.status = waiting[waiting_item.phase]
            return waiting_item
        session.status = SessionStatus.COMPLETED
        return None

    @staticmethod
    def _event(
        session: SimulationSession,
        item: ItemSimulationState,
        event_type: str,
        payload: dict[str, Any],
        *,
        operation_run_id: str | None = None,
    ) -> dict[str, Any]:
        session.event_counter += 1
        occurred_at = session.created_at + timedelta(minutes=session.event_counter)
        event_id = (
            f"SIM-{str(session.id).split('-')[0].upper()}-"
            f"G{session.generation}-{session.event_counter:06d}"
        )
        return canonical_event(
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            item_id=item.item_id,
            operation_run_id=operation_run_id,
            payload=payload,
        )

    def advance(
        self, session: SimulationSession, item: ItemSimulationState
    ) -> dict[str, Any] | None:
        if item.completed or item.phase in {"wait_controller", "wait_release"}:
            return None
        step = session.route.steps[item.step_index] if session.route.steps else None

        if item.phase == "register":
            item.phase = "operator_action" if step else "complete"
            return self._event(
                session,
                item,
                "item.registered",
                {
                    "product_definition_id": "PD-TRACE-01",
                    "revision": "A",
                    "line_id": "LINE-A",
                    "route_id": session.route.route_code,
                    "route_revision": session.route.revision,
                },
            )

        if item.phase == "operator_action" and step:
            item.phase = "operation_start"
            return self._event(
                session,
                item,
                "operator.action",
                {
                    "operator_id": "OPER-01",
                    "action_type": "confirm_route_step",
                    "parameters": {
                        "operation_id": step.operation_id,
                        "station_id": step.station_id,
                    },
                },
            )

        if item.phase == "operation_start" and step:
            suffix = "RW" if item.nonconformance_id else "P"
            run_id = (
                f"RUN-{item.item_id}-{step.position:02d}-{suffix}-{session.event_counter + 1}"
            )
            item.current_run_id = run_id
            if not item.nonconformance_id:
                item.production_run_id = run_id
            item.phase = (
                "rework_finish"
                if item.nonconformance_id
                else "equipment_warning"
                if session.mode == SimulationMode.EQUIPMENT_ISSUE
                and not item.equipment_warning_sent
                and item.step_index == min(1, len(session.route.steps) - 1)
                else "operation_finish"
            )
            payload: dict[str, Any] = {
                "operation_id": step.operation_id,
                "operator_id": "OPER-01",
                "equipment_id": "EQ-LATHE-01",
                "station_id": step.station_id,
                "parameters": {},
                "run_reason": "rework" if item.nonconformance_id else "production",
            }
            if item.nonconformance_id:
                item.rework_count += 1
                payload.update(
                    {
                        "previous_operation_run_id": item.production_run_id,
                        "rework_for_nonconformance_id": item.nonconformance_id,
                    }
                )
            item.operation_history.append(
                {
                    "operation_run_id": run_id,
                    "operation_id": step.operation_id,
                    "kind": payload["run_reason"],
                    "state": "started",
                }
            )
            return self._event(
                session,
                item,
                "operation.started",
                payload,
                operation_run_id=run_id,
            )

        if item.phase == "equipment_warning" and step:
            item.equipment_warning_sent = True
            item.equipment_history.append(
                {
                    "equipment_id": "EQ-LATHE-01",
                    "state": "warning",
                    "code": "SIM_VIBRATION_HIGH",
                }
            )
            item.phase = "operation_finish"
            return self._event(
                session,
                item,
                "machine.state",
                {
                    "equipment_id": "EQ-LATHE-01",
                    "state": "warning",
                    "code": "SIM_VIBRATION_HIGH",
                    "parameters": {"operation_id": step.operation_id},
                },
                operation_run_id=item.current_run_id,
            )

        if item.phase in {"operation_finish", "rework_finish"} and step:
            was_rework = item.phase == "rework_finish"
            event = self._event(
                session,
                item,
                "operation.finished",
                {
                    "completion_status": "completed",
                    "duration": {
                        "value": 10,
                        "unit": "min",
                        "meaning": "simulated_cycle_time",
                    },
                    "parameters": {},
                },
                operation_run_id=item.current_run_id,
            )
            item.operation_history.append(
                {
                    "operation_run_id": item.current_run_id,
                    "operation_id": step.operation_id,
                    "kind": "rework" if was_rework else "production",
                    "state": "completed",
                }
            )
            if was_rework:
                self.apply_rework_result(item, successful=True)
                item.phase = "rework_inspection"
            elif step.required:
                item.phase = "inspection"
            else:
                self._move_to_next_step(session, item)
            return event

        if item.phase in {"inspection", "rework_inspection"} and step:
            rework = item.phase == "rework_inspection"
            inject = (
                session.mode == SimulationMode.DEFECT_REWORK
                and item.item_index == session.defect_item_index
                and not item.defect_injected
                and item.step_index == session.defect_step_index
            )
            defects: list[dict[str, Any]] = []
            result = "no_defect"
            if inject:
                item.defect_injected = True
                item.active_defects = ["surface_crack"]
            if item.active_defects:
                result = "defect_detected"
                defects = [
                    {
                        "defect_type": defect,
                        "description": "Детерминированный дефект demo-симуляции",
                        "severity": "medium",
                        "component_instance_id": "COMP-BODY-1",
                        "confidence": 0.97,
                    }
                    for defect in item.active_defects
                ]
                item.phase = "wait_controller"
                item.waiting_reason = (
                    "Доработка не устранила дефект; ожидается решение контролёра"
                    if rework
                    else "Ожидается решение контролёра"
                )
            elif rework:
                item.phase = "wait_release"
                item.waiting_reason = "Ожидается проверка доработки контролёром"
            else:
                self._move_to_next_step(session, item)
            return self._event(
                session,
                item,
                "inspection.result",
                {
                    "inspection_result": result,
                    "observation_quality": "good",
                    "control_point_id": step.control_point_id or f"CP-{step.position}",
                    "confidence": 0.97,
                    "inspection_scope": step.inspection_scope
                    or {"defect_types": ["*"], "component_instance_ids": ["*"]},
                    "defects": defects,
                    "evidence_refs": [
                        f"simulator://{session.id}/{item.item_id}/{session.event_counter + 1}"
                    ],
                    "control_device_id": "SIM-CAMERA-01",
                    "capture_session_id": f"CAP-{session.event_counter + 1}",
                },
                operation_run_id=item.current_run_id,
            )

        if item.phase == "complete":
            item.completed = True
            return None
        raise RuntimeError(f"Unsupported simulator phase: {item.phase}")

    @staticmethod
    def _move_to_next_step(
        session: SimulationSession, item: ItemSimulationState
    ) -> None:
        item.step_index += 1
        item.current_run_id = None
        item.production_run_id = None
        if item.step_index >= len(session.route.steps):
            item.completed = True
            item.phase = "complete"
        else:
            item.phase = "operation_start"

    @staticmethod
    def controller_allowed_rework(
        item: ItemSimulationState, nonconformance_id: str
    ) -> None:
        item.nonconformance_id = nonconformance_id
        item.waiting_reason = None
        item.phase = "operation_start"

    @staticmethod
    def released_after_rework(
        session: SimulationSession, item: ItemSimulationState
    ) -> None:
        item.nonconformance_id = None
        item.waiting_reason = None
        SimulationEngine._move_to_next_step(session, item)

    @staticmethod
    def apply_rework_result(
        item: ItemSimulationState, *, successful: bool, targeted_defect: str = "surface_crack"
    ) -> None:
        """A physical rework may remove a defect; an inspection never does."""
        if successful:
            item.active_defects = [
                defect for defect in item.active_defects if defect != targeted_defect
            ]
