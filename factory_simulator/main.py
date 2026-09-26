from __future__ import annotations

import os
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response

from factory_simulator.client import TraceQClient
from factory_simulator.models import SessionCreate, SimulationSession
from factory_simulator.service import SessionManager


def create_app(manager: SessionManager | None = None) -> FastAPI:
    simulator_manager = manager or SessionManager(
        TraceQClient(
            os.getenv("TRACEQ_API_URL", "http://backend:8080"),
            os.getenv("SOURCE_DEMO_TOKEN", ""),
            os.getenv("SIMULATOR_READER_USERNAME", "factory-simulator"),
            os.getenv("SIMULATOR_READER_PASSWORD", ""),
        )
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await simulator_manager.shutdown()

    app = FastAPI(title="TRACE-Q Factory Simulator", version="0.1.0", lifespan=lifespan)
    app.state.manager = simulator_manager

    def session_or_404(session_id: UUID) -> SimulationSession:
        try:
            return simulator_manager.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/sessions")
    async def sessions():
        return list(simulator_manager.sessions.values())

    @app.get("/routes")
    async def routes():
        try:
            return await simulator_manager.client.available_routes()
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail="Не удалось получить активные маршруты TRACE-Q."
            ) from exc

    @app.post("/sessions", response_model=SimulationSession)
    async def create_session(body: SessionCreate):
        try:
            return await simulator_manager.create(body)
        except ValueError as exc:
            message = str(exc)
            if "Active route not found" in message:
                message = "У выбранного маршрута нет активной ревизии."
            raise HTTPException(status_code=422, detail=message) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail="Сервис TRACE-Q недоступен."
            ) from exc

    @app.get("/sessions/{session_id}", response_model=SimulationSession)
    async def get_session(session_id: UUID):
        return session_or_404(session_id)

    @app.post("/sessions/{session_id}/start", response_model=SimulationSession)
    async def start(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.start(session_id)

    @app.post("/sessions/{session_id}/pause", response_model=SimulationSession)
    async def pause(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.pause(session_id)

    @app.post("/sessions/{session_id}/resume", response_model=SimulationSession)
    async def resume(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.resume(session_id)

    @app.post("/sessions/{session_id}/step", response_model=SimulationSession)
    async def step(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.step(session_id)

    @app.post("/sessions/{session_id}/stop", response_model=SimulationSession)
    async def stop(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.stop(session_id)

    @app.post("/sessions/{session_id}/reset", response_model=SimulationSession)
    async def reset(session_id: UUID):
        session_or_404(session_id)
        return await simulator_manager.reset(session_id)

    @app.delete("/sessions/{session_id}", status_code=204)
    async def delete(session_id: UUID):
        session_or_404(session_id)
        await simulator_manager.delete(session_id)
        return Response(status_code=204)

    return app


app = create_app()
