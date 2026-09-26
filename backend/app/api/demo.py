from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.persistence.database import SessionLocal, get_db
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_permission
from backend.app.settings import Settings, get_settings
from backend.app.scenarios.harness import ScenarioBundle, ScenarioHarness
from backend.app.scenarios.runtime import FIXTURE_SOURCE_IDS, ScenarioRuntime


router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "scenarios"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _scenario_path(name: str) -> Path:
    if not SAFE_NAME.fullmatch(name):
        raise NotFoundError("Scenario")
    path = SCENARIOS / name
    if not path.is_dir() or not (path / "events.jsonl").is_file() or not (path / "expected.json").is_file():
        raise NotFoundError("Scenario")
    return path


@router.get("/scenarios")
def scenarios(_: Principal = Depends(require_permission("RUN_DEMO_SCENARIOS"))):
    values = []
    if not SCENARIOS.exists():
        return values
    for path in sorted(SCENARIOS.iterdir()):
        if not path.is_dir() or not (path / "expected.json").exists():
            continue
        expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
        metadata_path = path / "scenario.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.exists()
            else {}
        )
        values.append(
            {
                "name": path.name,
                "title": metadata.get("title", path.name),
                "description": metadata.get(
                    "purpose", expected.get("description", path.name)
                ),
                "priority": metadata.get("priority"),
                "test_targets": metadata.get("test_targets", []),
                "expected": {key: value for key, value in expected.items() if key != "description"},
            }
        )
    return values


def _tamper(settings: Settings, event_id: str) -> None:
    if not settings.demo_privileged_database_url:
        raise TraceQError("DEMO_TAMPER_UNAVAILABLE", "Demo tamper connection is not configured", 503)
    engine = create_engine(settings.demo_privileged_database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE raw_events DISABLE TRIGGER trg_raw_events_append_only"))
        try:
            connection.execute(
                text(
                    "UPDATE raw_events SET payload_ciphertext = "
                    "set_byte(payload_ciphertext, 0, get_byte(payload_ciphertext, 0) # 1) "
                    "WHERE event_id=:event_id"
                ),
                {"event_id": event_id},
            )
        finally:
            connection.execute(text("ALTER TABLE raw_events ENABLE TRIGGER trg_raw_events_append_only"))


@router.post("/scenarios/{name}/run")
def run_scenario(
    name: str,
    request: Request,
    principal: Principal = Depends(require_permission("RUN_DEMO_SCENARIOS")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    bundle = ScenarioBundle.load(_scenario_path(name))
    runtime = ScenarioRuntime(
        db,
        settings,
        scenario_id=bundle.scenario_id,
        caller=principal,
    )
    harness = ScenarioHarness(
        reset=runtime.reset,
        setup=runtime.setup,
        deliver=runtime.deliver,
        action=runtime.action,
        request=runtime.request,
        erp=runtime.erp,
        route_change=runtime.route_change,
        analysis=runtime.analysis,
        tamper=runtime.tamper,
        normalize=runtime.normalize,
    )
    result = harness.run(bundle)
    write_audit(
        db,
        action="demo_scenario_run",
        outcome="success" if result["passed"] else "failure",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="scenario",
        target_id=name,
        request_id=request.state.request_id,
        safe_details={"failures": result["failures"][:50]},
    )
    db.commit()
    return result


@router.post("/reset")
def reset_demo(
    request: Request,
    principal: Principal = Depends(require_permission("RUN_DEMO_SCENARIOS")),
    settings: Settings = Depends(get_settings),
):
    if not settings.demo_privileged_database_url:
        raise TraceQError("DEMO_RESET_UNAVAILABLE", "Demo reset connection is not configured", 503)
    tables = (
        "containment_applications",
        "blast_radius_exposures",
        "approval_requests",
        "containment_proposals",
        "blast_radius_queries",
        "control_device_invalidations",
        "transport_nonces",
        "security_alerts",
        "analysis_evidence",
        "analysis_versions",
        "controller_decisions",
        "quality_results",
        "outbox_messages",
        "integration_messages",
        "nonconformities",
        "defect_occurrences",
        "defect_observations",
        "observations",
        "machine_events",
        "operator_actions",
        "operation_runs",
        "items",
        "projection_state",
        "raw_events",
        "ingest_attempts",
        "integrity_stream_states",
    )
    engine = create_engine(settings.demo_privileged_database_url)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        connection.execute(
            text(
                "UPDATE event_sources SET last_source_sequence = NULL "
                "WHERE source_id IN :source_ids"
            ).bindparams(bindparam("source_ids", expanding=True)),
            {"source_ids": list(FIXTURE_SOURCE_IDS)},
        )
    audit_db = SessionLocal()
    try:
        write_audit(
            audit_db,
            action="demo_reset",
            outcome="success",
            actor_user_id=principal.user_id,
            session_id=principal.session_id,
            target_type="demo_data",
            target_id="all_scenarios",
            request_id=request.state.request_id,
        )
        audit_db.commit()
    finally:
        audit_db.close()
    return {"status": "reset"}
