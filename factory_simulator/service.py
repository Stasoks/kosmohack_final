from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from factory_simulator.client import TraceQClient
from factory_simulator.engine import SimulationEngine
from factory_simulator.models import FeedEntry, SessionCreate, SessionStatus, SimulationSession


class SessionManager:
    def __init__(self, client: TraceQClient):
        self.client = client
        self.engine = SimulationEngine()
        self.sessions: dict[UUID, SimulationSession] = {}
        self.tasks: dict[UUID, asyncio.Task] = {}

    async def create(self, body: SessionCreate) -> SimulationSession:
        route = await self.client.route_snapshot(body.route_code)
        if not route.steps:
            raise ValueError("В активной ревизии маршрута нет операций.")
        if body.mode.value == "defect_rework" and not any(
            step.required for step in route.steps
        ):
            raise ValueError(
                "Для режима с дефектом маршрут должен содержать обязательный контроль."
            )
        session = self.engine.create_session(
            route,
            item_count=body.item_count,
            mode=body.mode,
            interval_seconds=body.interval_seconds,
            seed=body.seed,
        )
        self.sessions[session.id] = session
        return session

    def get(self, session_id: UUID) -> SimulationSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise KeyError("Simulation session not found") from exc

    async def start(self, session_id: UUID) -> SimulationSession:
        session = self.get(session_id)
        if session.status == SessionStatus.COMPLETED:
            return session
        session.status = SessionStatus.RUNNING
        task = self.tasks.get(session_id)
        if task is None or task.done():
            self.tasks[session_id] = asyncio.create_task(self._run(session_id))
        return session

    async def pause(self, session_id: UUID) -> SimulationSession:
        session = self.get(session_id)
        session.status = SessionStatus.PAUSED
        await self._cancel_task(session_id)
        return session

    async def resume(self, session_id: UUID) -> SimulationSession:
        return await self.start(session_id)

    async def stop(self, session_id: UUID) -> SimulationSession:
        session = self.get(session_id)
        session.status = SessionStatus.STOPPED
        await self._cancel_task(session_id)
        return session

    async def reset(self, session_id: UUID) -> SimulationSession:
        session = self.get(session_id)
        await self._cancel_task(session_id)
        self.engine.reset(session)
        return session

    async def delete(self, session_id: UUID) -> None:
        self.get(session_id)
        await self._cancel_task(session_id)
        del self.sessions[session_id]

    async def step(self, session_id: UUID) -> SimulationSession:
        session = self.get(session_id)
        try:
            item = self.engine.next_item(session)
            if item is None:
                return session
            if item.phase == "wait_controller":
                rows = await self.client.nonconformances()
                ncr = next(
                    (
                        row
                        for row in rows
                        if row.get("item_id") == item.item_id
                        and row.get("disposition") == "REWORK_REQUIRED"
                    ),
                    None,
                )
                if ncr is None:
                    self._feed(session, item.item_id, "waiting", "Ожидается решение контролёра")
                    return session
                self.engine.controller_allowed_rework(item, str(ncr["id"]))
            elif item.phase == "wait_release":
                value = await self.client.item_state(item.item_id)
                if not value or value.get("status") != "RELEASED":
                    self._feed(session, item.item_id, "waiting", "Ожидается проверка доработки")
                    return session
                self.engine.released_after_rework(session, item)

            event = self.engine.advance(session, item)
            if event is None:
                self.engine.next_item(session)
                return session
            result = await self.client.publish(event)
            self._feed(
                session,
                item.item_id,
                str(result.get("ingestion_status") or "sent"),
                f"{event['event_type']} принят TRACE-Q",
                event_id=event["event_id"],
                event_type=event["event_type"],
            )
            self.engine.next_item(session)
        except Exception as exc:
            session.status = SessionStatus.ERROR
            session.last_error = f"{type(exc).__name__}: {exc}"
            self._feed(session, None, "error", session.last_error)
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(self._cancel_task(session_id) for session_id in list(self.tasks)),
            return_exceptions=True,
        )

    async def _run(self, session_id: UUID) -> None:
        try:
            while True:
                session = self.get(session_id)
                if session.status in {
                    SessionStatus.PAUSED,
                    SessionStatus.STOPPED,
                    SessionStatus.COMPLETED,
                    SessionStatus.ERROR,
                }:
                    return
                await self.step(session_id)
                await asyncio.sleep(session.interval_seconds)
        except asyncio.CancelledError:
            return

    async def _cancel_task(self, session_id: UUID) -> None:
        task = self.tasks.pop(session_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def _feed(
        session: SimulationSession,
        item_id: str | None,
        status: str,
        message: str,
        *,
        event_id: str | None = None,
        event_type: str | None = None,
    ) -> None:
        session.feed.append(
            FeedEntry(
                at=datetime.now(timezone.utc),
                item_id=item_id,
                event_id=event_id,
                event_type=event_type,
                status=status,
                message=message,
            )
        )
        session.feed = session.feed[-200:]
