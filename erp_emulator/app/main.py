from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field


class QualityResultInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    item_id: str
    nonconformance_id: str
    decision_id: str
    verdict: str
    disposition: str
    containment: str
    decided_at: str


class BehaviorInput(BaseModel):
    mode: Literal["NORMAL", "TIMEOUT_ONCE", "ERROR_503", "REJECT_400", "OFFLINE"]


class State:
    def __init__(self) -> None:
        self.lock = Lock()
        self.mode = "NORMAL"
        self.timeout_consumed = False
        self.deliveries: dict[str, dict] = {}

    def reset(self) -> None:
        with self.lock:
            self.mode = "NORMAL"
            self.timeout_consumed = False
            self.deliveries = {}


state = State()
app = FastAPI(title="TRACE-Q ERP Emulator", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "healthy", "mode": state.mode}


@app.get("/api/v1/jobs")
def jobs():
    if state.mode == "OFFLINE":
        raise HTTPException(status_code=503, detail="emulator offline")
    return [
        {
            "job_id": "ERP-JOB-001",
            "product_definition_id": "ERP-PD-TRACE-01",
            "revision": "A",
            "quantity": 4,
            "route_code": "ROUTE-DEFAULT",
            "status": "released",
        }
    ]


@app.get("/api/v1/references")
def references():
    if state.mode == "OFFLINE":
        raise HTTPException(status_code=503, detail="emulator offline")
    return {
        "products": [{"external_id": "ERP-PD-TRACE-01", "code": "PD-TRACE-01", "revision": "A"}],
        "operations": ["OP-INCOMING", "OP-TURN", "OP-ASSEMBLY"],
    }


@app.post("/api/v1/quality-results")
async def quality_results(body: QualityResultInput):
    with state.lock:
        mode = state.mode
        should_timeout = mode == "TIMEOUT_ONCE" and not state.timeout_consumed
        if should_timeout:
            state.timeout_consumed = True
    if mode == "OFFLINE":
        raise HTTPException(status_code=503, detail="emulator offline")
    if mode == "ERROR_503":
        raise HTTPException(status_code=503, detail="simulated temporary failure")
    if mode == "REJECT_400":
        raise HTTPException(status_code=400, detail="simulated schema rejection")
    if should_timeout:
        await asyncio.sleep(12)
    with state.lock:
        existing = state.deliveries.get(body.message_id)
        if existing:
            return existing["ack"]
        ack = {
            "message_id": body.message_id,
            "status": "ACK",
            "external_result_id": f"ERP-QR-{len(state.deliveries) + 1:05d}",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        state.deliveries[body.message_id] = {"payload": body.model_dump(), "ack": ack}
        return ack


@app.get("/api/v1/quality-results/{message_id}")
def quality_result(message_id: str):
    delivery = state.deliveries.get(message_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="delivery not found")
    return delivery


@app.put("/api/v1/demo/behavior")
def behavior(body: BehaviorInput):
    with state.lock:
        state.mode = body.mode
        state.timeout_consumed = False
    return {"mode": state.mode}


@app.get("/api/v1/demo/deliveries")
def deliveries():
    return list(state.deliveries.values())


@app.post("/api/v1/demo/reset", status_code=204)
def reset():
    state.reset()
    return Response(status_code=204)
