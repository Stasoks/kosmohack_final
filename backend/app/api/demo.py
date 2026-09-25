from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.ingestion.service import ingest_event
from backend.app.persistence.database import SessionLocal, get_db
from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    IngestAttempt,
    IntegrityStreamState,
    Nonconformance,
)
from backend.app.projections.rebuild import rebuild_item
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal, require_permission
from backend.app.security.integrity import verify_integrity
from backend.app.settings import Settings, get_settings


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
        values.append(
            {
                "name": path.name,
                "description": expected.get("description", path.name),
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
    path = _scenario_path(name)
    if not settings.source_demo_token:
        raise TraceQError("DEMO_SOURCE_NOT_CONFIGURED", "Demo source token is not configured", 503)
    expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted = duplicates = 0
    item_ids: set[str] = set()
    for event in events:
        result = ingest_event(
            db,
            event,
            header_source_id=event["source"]["source_id"],
            source_token=settings.source_demo_token.get_secret_value(),
            settings=settings,
        )
        accepted += result.ingestion_status == "accepted"
        duplicates += result.ingestion_status == "duplicate"
        item_id = event.get("item_id") or event.get("payload", {}).get("item_id")
        if item_id:
            item_ids.add(item_id)
            if result.ingestion_status == "accepted":
                rebuild_item(db, item_id, settings)
    for item_id in sorted(item_ids):
        rebuild_item(db, item_id, settings)
    if expected.get("tamper") and events:
        _tamper(settings, events[0]["event_id"])
        db.expire_all()
        integrity_failures = verify_integrity(db, settings)
    else:
        integrity_failures = []

    expected_item = expected.get("item_id")
    ncrs = db.scalars(
        select(Nonconformance).where(Nonconformance.item_id == expected_item)
        if expected_item
        else select(Nonconformance).where(Nonconformance.item_id.in_(item_ids))
    ).all()
    versions = []
    for ncr in ncrs:
        versions.extend(
            db.scalars(
                select(AnalysisVersion)
                .where(AnalysisVersion.nonconformance_id == ncr.id)
                .order_by(AnalysisVersion.version)
            ).all()
        )
    evidence_types: set[str] = set()
    if versions:
        evidence_types = set(
            db.scalars(
                select(AnalysisEvidence.evidence_type).where(
                    AnalysisEvidence.analysis_version_id.in_([version.id for version in versions])
                )
            ).all()
        )
    actual = {
        "accepted_count": accepted,
        "duplicate_count": duplicates,
        "ncr_count": len(ncrs),
        "latest_analysis_status": versions[-1].status if versions else None,
        "analysis_version_count": len(versions),
        "verdict": ncrs[-1].verdict if ncrs else None,
        "evidence_types": sorted(evidence_types),
        "integrity_status": "FAILED" if integrity_failures else "OK",
    }
    checks: dict[str, bool] = {}
    for key in (
        "duplicate_count",
        "ncr_count",
        "latest_analysis_status",
        "verdict",
        "integrity_status",
    ):
        if key in expected:
            checks[key] = actual[key] == expected[key]
    if "min_analysis_versions" in expected:
        checks["min_analysis_versions"] = (
            actual["analysis_version_count"] >= expected["min_analysis_versions"]
        )
    if "evidence_types" in expected:
        checks["evidence_types"] = set(expected["evidence_types"]).issubset(evidence_types)
    write_audit(
        db,
        action="demo_scenario_run",
        outcome="success" if all(checks.values()) else "failure",
        actor_user_id=principal.user_id,
        session_id=principal.session_id,
        target_type="scenario",
        target_id=name,
        request_id=request.state.request_id,
        safe_details={"checks": checks},
    )
    db.commit()
    return {"scenario": name, "passed": all(checks.values()), "checks": checks, "actual": actual}


@router.post("/reset")
def reset_demo(
    request: Request,
    principal: Principal = Depends(require_permission("RUN_DEMO_SCENARIOS")),
    settings: Settings = Depends(get_settings),
):
    if not settings.demo_privileged_database_url:
        raise TraceQError("DEMO_RESET_UNAVAILABLE", "Demo reset connection is not configured", 503)
    tables = (
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
