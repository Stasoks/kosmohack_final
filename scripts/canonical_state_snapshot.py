from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    ControllerDecision,
    DefectOccurrence,
    IntegrationMessage,
    Item,
    Nonconformance,
    Observation,
    OperationRun,
    OutboxMessage,
    ProjectionState,
    RouteDefinition,
    RouteRevision,
)


VOLATILE_KEYS = frozenset(
    {
        "calculated_at",
        "recalculated_at",
        "created_at",
        "updated_at",
        "delivered_at",
        "last_successful_rebuild_at",
        "heartbeat_at",
        "request_id",
        "session_id",
    }
)


def normalize(value: Any) -> Any:
    """Return a JSON-safe, deterministically ordered business representation."""
    if isinstance(value, dict):
        return {
            str(key): normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        normalized = [normalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((normalize(row) for row in rows), key=canonical_json_bytes)


def _occurrence_identity(
    occurrence: DefectOccurrence,
    observation_events: dict[uuid.UUID, str],
) -> str:
    first_event = observation_events.get(occurrence.first_observation_id, "unknown")
    component = occurrence.component_instance_id or "item"
    return f"{occurrence.item_id}|{occurrence.defect_type}|{component}|{first_event}"


def build_state_snapshot(db: Session) -> dict[str, Any]:
    observations = db.scalars(select(Observation)).all()
    observation_events = {row.id: row.event_id for row in observations}
    occurrences = db.scalars(select(DefectOccurrence)).all()
    occurrence_keys = {
        row.id: _occurrence_identity(row, observation_events) for row in occurrences
    }
    nonconformances = db.scalars(select(Nonconformance)).all()
    ncr_keys = {
        row.id: occurrence_keys.get(row.occurrence_id, f"unknown:{row.occurrence_id}")
        for row in nonconformances
    }
    analyses = db.scalars(select(AnalysisVersion)).all()
    analysis_keys = {
        row.id: f"{ncr_keys.get(row.nonconformance_id, 'unknown')}|v{row.version}"
        for row in analyses
    }
    decisions = db.scalars(select(ControllerDecision)).all()
    decision_keys = {
        row.id: (
            f"{ncr_keys.get(row.nonconformance_id, 'unknown')}|v{row.analysis_version}|"
            f"{row.verdict}|{row.disposition}|{row.containment}"
        )
        for row in decisions
    }
    route_rows = db.execute(
        select(RouteRevision.id, RouteDefinition.code, RouteRevision.revision).join(
            RouteDefinition, RouteDefinition.id == RouteRevision.route_id
        )
    ).all()
    route_keys = {row_id: f"{code}|v{revision}" for row_id, code, revision in route_rows}

    snapshot = {
        "items": _sorted_rows(
            [
                {
                    "item_id": row.item_id,
                    "product_definition_id": row.product_definition_id,
                    "revision": row.revision,
                    "line_id": row.line_id,
                    "route_revision": route_keys.get(row.route_revision_id),
                    "status": row.status,
                    "structure_status": row.structure_status,
                    "registered_at": row.registered_at,
                }
                for row in db.scalars(select(Item)).all()
            ]
        ),
        "operation_runs": _sorted_rows(
            [
                {
                    "operation_run_id": row.operation_run_id,
                    "item_id": row.item_id,
                    "operation_id": row.operation_id,
                    "operator_id": row.operator_id,
                    "equipment_id": row.equipment_id,
                    "station_id": row.station_id,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                    "completion_status": row.completion_status,
                    "duration_value": row.duration_value,
                    "duration_unit": row.duration_unit,
                    "duration_meaning": row.duration_meaning,
                    "previous_operation_run_id": row.previous_operation_run_id,
                    "run_reason": row.run_reason,
                    "rework_for_nonconformance": ncr_keys.get(
                        row.rework_for_nonconformance_id
                    ),
                    "parameters": row.parameters,
                }
                for row in db.scalars(select(OperationRun)).all()
            ]
        ),
        "observations": _sorted_rows(
            [
                {
                    "event_id": row.event_id,
                    "item_id": row.item_id,
                    "operation_run_id": row.operation_run_id,
                    "occurred_at": row.occurred_at,
                    "inspection_result": row.inspection_result,
                    "observation_quality": row.observation_quality,
                    "control_point_id": row.control_point_id,
                    "confidence": row.confidence,
                    "inspection_scope": row.inspection_scope,
                    "component_instance_id": row.component_instance_id,
                    "control_device_id": row.control_device_id,
                    "capture_session_id": row.capture_session_id,
                    "evidence_refs": row.evidence_refs,
                    "trust_status": row.trust_status,
                    "trust_reasons": row.trust_reasons,
                }
                for row in observations
            ]
        ),
        "defect_occurrences": _sorted_rows(
            [
                {
                    "occurrence": occurrence_keys[row.id],
                    "item_id": row.item_id,
                    "defect_type": row.defect_type,
                    "component_instance_id": row.component_instance_id,
                    "first_observation_event_id": observation_events.get(
                        row.first_observation_id
                    ),
                    "current_observation_event_id": observation_events.get(
                        row.current_observation_id
                    ),
                    "status": row.status,
                    "opened_at": row.opened_at,
                    "closed_at": row.closed_at,
                }
                for row in occurrences
            ]
        ),
        "nonconformances": _sorted_rows(
            [
                {
                    "nonconformance": ncr_keys[row.id],
                    "item_id": row.item_id,
                    "defect_type": row.defect_type,
                    "component_instance_id": row.component_instance_id,
                    "verdict": row.verdict,
                    "cause_status": row.cause_status,
                    "disposition": row.disposition,
                    "containment": row.containment,
                    "opened_at": row.opened_at,
                    "closed_at": row.closed_at,
                    "current_analysis_version": row.current_analysis_version,
                    "resolution_type": row.resolution_type,
                    "resolved_at": row.resolved_at,
                    "verification_decision": decision_keys.get(
                        row.verification_decision_id
                    ),
                    "verification_status": row.verification_status,
                }
                for row in nonconformances
            ]
        ),
        "analysis_versions": _sorted_rows(
            [
                {
                    "analysis": analysis_keys[row.id],
                    "nonconformance": ncr_keys.get(row.nonconformance_id),
                    "item_id": row.item_id,
                    "version": row.version,
                    "status": row.status,
                    "defect_type": row.defect_type,
                    "component_instance_id": row.component_instance_id,
                    "left_boundary_at": row.left_boundary_at,
                    "right_boundary_at": row.right_boundary_at,
                    "algorithm_version": row.algorithm_version,
                    "reason": row.reason,
                }
                for row in analyses
            ]
        ),
        "analysis_evidence": _sorted_rows(
            [
                {
                    "analysis": analysis_keys.get(row.analysis_version_id),
                    "evidence_type": row.evidence_type,
                    "evidence_role": row.evidence_role,
                    "source_event_id": row.source_event_id,
                    "source_entity_type": row.source_entity_type,
                    "source_entity_id": row.source_entity_id,
                    "occurred_at": row.occurred_at,
                    "details": row.details,
                }
                for row in db.scalars(select(AnalysisEvidence)).all()
            ]
        ),
        "decisions": _sorted_rows(
            [
                {
                    "decision": decision_keys[row.id],
                    "nonconformance": ncr_keys.get(row.nonconformance_id),
                    "verdict": row.verdict,
                    "disposition": row.disposition,
                    "containment": row.containment,
                    "reason": row.reason,
                    "analysis_version": row.analysis_version,
                    "previous_decision": decision_keys.get(row.previous_decision_id),
                }
                for row in decisions
            ]
        ),
        "projection_state": _sorted_rows(
            [
                {
                    "item_id": row.item_id,
                    "status": row.status,
                    "caught_up": row.latest_raw_ingest_seq
                    == row.last_projected_ingest_seq,
                    "last_error": row.last_error,
                }
                for row in db.scalars(select(ProjectionState)).all()
            ]
        ),
        "outbox_messages": _sorted_rows(
            [
                {
                    "message_id": row.message_id,
                    "destination": row.destination,
                    "message_type": row.message_type,
                    "payload": row.payload,
                    "state": row.state,
                    "attempts": row.attempts,
                    "last_error": row.last_error,
                }
                for row in db.scalars(select(OutboxMessage)).all()
            ]
        ),
        "integration_messages": _sorted_rows(
            [
                {
                    "message_id": row.message_id,
                    "direction": row.direction,
                    "external_system": row.external_system,
                    "status": row.status,
                    "safe_payload": row.safe_payload,
                }
                for row in db.scalars(select(IntegrationMessage)).all()
            ]
        ),
    }
    return normalize(snapshot)


def build_kpi_snapshot(db: Session) -> dict[str, Any]:
    from backend.app.api.analytics import quality_kpi

    return normalize(quality_kpi(None, db))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a canonical TRACE-Q business-state snapshot")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from backend.app.persistence.database import SessionLocal

    db = SessionLocal()
    try:
        state = build_state_snapshot(db)
        result = {
            "projection_hash": stable_hash(state),
            "kpi_hash": stable_hash(build_kpi_snapshot(db)),
            "state": state,
        }
    finally:
        db.close()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
