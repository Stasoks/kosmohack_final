from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    DefectObservation,
    DefectOccurrence,
    ControlDeviceInvalidation,
    Item,
    MachineEvent,
    Nonconformance,
    Observation,
    OperationRun,
    OperatorAction,
    ProjectionState,
    ProductStructureSnapshot,
    RawEvent,
    RouteDefinition,
    RouteRevision,
    RouteStep,
    TrustPolicy,
)
from backend.app.quality.birth_window import EvidenceValue, calculate_birth_window
from backend.app.quality.trust import TrustPolicyValue, evaluate_trust
from backend.app.security.crypto import build_aad, decrypt_event, utcnow
from backend.app.settings import Settings


OBSERVATION_NAMESPACE = uuid.UUID("b8d12dc1-9b4e-4e16-a463-1323ea45b88c")


def _route_revision_number(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text_value = str(value).strip().lower()
    if text_value.startswith("v"):
        text_value = text_value[1:]
    return int(text_value) if text_value.isdigit() else None


def advisory_lock_key(item_id: str) -> int:
    raw = int.from_bytes(hashlib.sha256(item_id.encode("utf-8")).digest()[:8], "big", signed=False)
    return raw - 2**64 if raw >= 2**63 else raw


def _decrypt(raw: RawEvent, settings: Settings) -> dict[str, Any]:
    aad = build_aad(
        event_id=raw.event_id,
        event_type=raw.event_type,
        source_id=raw.source_id,
        schema_version=raw.schema_version,
        received_at=raw.received_at,
        occurred_at=raw.occurred_at,
        item_id=raw.item_id,
        crypto_key_id=raw.crypto_key_id,
        profile=raw.crypto_profile_id,
    )
    plaintext = decrypt_event(raw.payload_ciphertext, raw.nonce, settings.aes_key(), aad)
    return json.loads(plaintext)


def _trust_policy(db: Session, control_point_id: str) -> TrustPolicyValue:
    policy = db.scalar(
        select(TrustPolicy)
        .where(TrustPolicy.control_point_id == control_point_id, TrustPolicy.active.is_(True))
        .order_by(TrustPolicy.policy_version.desc())
        .limit(1)
    )
    if not policy:
        return TrustPolicyValue()
    return TrustPolicyValue(
        allowed_observation_quality=frozenset(policy.allowed_observation_quality),
        confidence_required=policy.confidence_required,
        min_confidence=policy.min_confidence,
        requires_valid_device=policy.requires_valid_device,
        media_required=policy.media_required,
    )


def _missing_check_limitations(
    db: Session,
    item: Item | None,
    operation_values: list[dict[str, Any]],
    observation_values: list[dict[str, Any]],
) -> list[EvidenceValue]:
    if not item or not item.route_revision_id:
        return []
    steps = db.scalars(
        select(RouteStep)
        .where(RouteStep.route_revision_id == item.route_revision_id)
        .order_by(RouteStep.position)
    ).all()
    operations = {value.get("operation_id"): value for value in operation_values}
    result: list[EvidenceValue] = []
    for index, step in enumerate(steps[:-1]):
        if not step.required_inspection or not step.control_point_id:
            continue
        next_step = steps[index + 1]
        next_run = operations.get(next_step.operation_id)
        if not next_run or not next_run.get("started_at"):
            continue
        completed = operations.get(step.operation_id)
        lower = completed.get("finished_at") if completed else None
        present = any(
            obs.get("control_point_id") == step.control_point_id
            and (lower is None or obs["occurred_at"] >= lower)
            and obs["occurred_at"] <= next_run["started_at"]
            for obs in observation_values
        )
        if not present:
            result.append(
                EvidenceValue(
                    "MISSING_CHECK",
                    "LIMITATION",
                    None,
                    next_run["started_at"],
                    {
                        "control_point_id": step.control_point_id,
                        "before_operation_id": next_step.operation_id,
                    },
                )
            )
    return result


def _analysis_changed(latest: AnalysisVersion | None, result) -> bool:
    return not latest or (
        latest.status != result.status
        or latest.left_boundary_at != result.left_boundary_at
        or latest.right_boundary_at != result.right_boundary_at
    )


def _create_analysis(
    db: Session,
    ncr: Nonconformance,
    defect: dict[str, Any],
    observations: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    machines: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    limitations: list[EvidenceValue],
) -> None:
    result = calculate_birth_window(
        defect_observation=defect,
        observations=observations,
        operations=operations,
        machine_events=machines,
        operator_actions=actions,
        limitations=limitations,
    )
    latest = db.scalar(
        select(AnalysisVersion)
        .where(AnalysisVersion.nonconformance_id == ncr.id)
        .order_by(AnalysisVersion.version.desc())
        .limit(1)
    )
    if not _analysis_changed(latest, result):
        return
    version_number = (latest.version + 1) if latest else 1
    analysis = AnalysisVersion(
        nonconformance_id=ncr.id,
        item_id=ncr.item_id,
        version=version_number,
        status=result.status,
        defect_type=ncr.defect_type,
        component_instance_id=ncr.component_instance_id,
        left_boundary_at=result.left_boundary_at,
        right_boundary_at=result.right_boundary_at,
        reason="late_event_rebuild" if latest else "initial_detection",
    )
    db.add(analysis)
    db.flush()
    for value in result.evidence:
        db.add(
            AnalysisEvidence(
                analysis_version_id=analysis.id,
                evidence_type=value.evidence_type,
                evidence_role=value.evidence_role,
                source_event_id=value.source_event_id,
                source_entity_type="raw_event" if value.source_event_id else None,
                source_entity_id=value.source_event_id,
                occurred_at=value.occurred_at,
                details=value.details,
            )
        )
    ncr.current_analysis_version = version_number


def _create_invalidated_analysis(db: Session, ncr: Nonconformance, observation: dict[str, Any]) -> None:
    latest = db.scalar(select(AnalysisVersion).where(
        AnalysisVersion.nonconformance_id == ncr.id
    ).order_by(AnalysisVersion.version.desc()).limit(1))
    if latest and latest.status == "EVIDENCE_INVALIDATED":
        return
    version = AnalysisVersion(
        nonconformance_id=ncr.id, item_id=ncr.item_id,
        version=(latest.version + 1) if latest else 1, status="EVIDENCE_INVALIDATED",
        defect_type=ncr.defect_type, component_instance_id=ncr.component_instance_id,
        left_boundary_at=None, right_boundary_at=None, reason="control_device_invalidation",
    )
    db.add(version); db.flush()
    db.add(AnalysisEvidence(
        analysis_version_id=version.id, evidence_type="DEVICE_VALIDITY", evidence_role="LIMITATION",
        source_event_id=observation.get("event_id"), source_entity_type="raw_event",
        source_entity_id=observation.get("event_id"), occurred_at=observation.get("occurred_at"),
        details={"trust_status": "INVALIDATED", "control_device_id": observation.get("control_device_id"),
                 "reasons": observation.get("trust_reasons", [])},
    ))
    ncr.current_analysis_version = version.version


def rebuild_item(db: Session, item_id: str, settings: Settings) -> None:
    state = db.get(ProjectionState, item_id)
    if state is None:
        state = ProjectionState(item_id=item_id)
        db.add(state)
        db.flush()
    state.status = "rebuilding"
    db.flush()
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_lock_key(item_id)})
    raws = db.scalars(
        select(RawEvent)
        .where(RawEvent.item_id == item_id)
        .order_by(
            RawEvent.occurred_at,
            RawEvent.source_id,
            RawEvent.source_sequence.asc().nullslast(),
            RawEvent.received_at,
            RawEvent.event_id,
        )
    ).all()
    if not raws:
        state.status = "up_to_date"
        db.commit()
        return

    events = [(raw, _decrypt(raw, settings)) for raw in raws]
    item_value: dict[str, Any] | None = None
    operation_values: dict[str, dict[str, Any]] = {}
    observation_values: list[dict[str, Any]] = []
    machine_values: list[dict[str, Any]] = []
    action_values: list[dict[str, Any]] = []

    for raw, event in events:
        payload = event["payload"]
        if raw.event_type == "item.registered":
            item_value = {**payload, "registered_at": raw.occurred_at}
        elif raw.event_type == "operation.started":
            run = operation_values.setdefault(raw.operation_run_id, {})
            run.update(
                {
                    **payload,
                    "item_id": raw.item_id,
                    "operation_run_id": raw.operation_run_id,
                    "started_at": raw.occurred_at,
                    "source_event_id": raw.event_id,
                }
            )
        elif raw.event_type == "operation.finished":
            run = operation_values.setdefault(
                raw.operation_run_id,
                {"item_id": item_id, "operation_run_id": raw.operation_run_id},
            )
            run.update(
                {
                    "finished_at": raw.occurred_at,
                    "completion_status": payload["completion_status"],
                    "duration": payload.get("duration"),
                    "finish_parameters": payload.get("parameters"),
                    "source_event_id": raw.event_id,
                }
            )
        elif raw.event_type == "inspection.result":
            policy = _trust_policy(db, payload["control_point_id"])
            invalidated = bool(payload.get("control_device_id") and db.scalar(select(ControlDeviceInvalidation.id).where(
                ControlDeviceInvalidation.device_id == payload.get("control_device_id"),
                ControlDeviceInvalidation.affected_from <= raw.occurred_at,
                ControlDeviceInvalidation.affected_to >= raw.occurred_at,
            ).limit(1)))
            trust = evaluate_trust(payload, policy, invalidated=invalidated)
            observation_values.append(
                {
                    **payload,
                    "item_id": raw.item_id,
                    "operation_run_id": raw.operation_run_id,
                    "event_id": raw.event_id,
                    "occurred_at": raw.occurred_at,
                    "trust_status": trust.status,
                    "trust_reasons": list(trust.reasons),
                }
            )
        elif raw.event_type == "machine.state":
            machine_values.append({**payload, "item_id": raw.item_id, "operation_run_id": raw.operation_run_id, "event_id": raw.event_id, "occurred_at": raw.occurred_at})
        elif raw.event_type == "operator.action":
            action_values.append({**payload, "item_id": raw.item_id, "operation_run_id": raw.operation_run_id, "event_id": raw.event_id, "occurred_at": raw.occurred_at})

    # Equal-time, equal-control-point observations with opposing results are not causal tie-breaks.
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for obs in observation_values:
        session = obs.get("capture_session_id")
        bucket = int(obs["occurred_at"].timestamp() // 300)
        key = (session or bucket, obs["control_point_id"], obs.get("component_instance_id"))
        groups.setdefault(key, []).append(obs)
    for group in groups.values():
        if len({obs["inspection_result"] for obs in group}) > 1:
            for obs in group:
                obs["trust_status"] = "CONFLICTED"
                obs["trust_reasons"] = ["EQUIVALENT_OBSERVATIONS_CONFLICT"]

    db.execute(delete(DefectObservation).where(DefectObservation.item_id == item_id))
    db.execute(delete(Observation).where(Observation.item_id == item_id))
    db.execute(delete(OperationRun).where(OperationRun.item_id == item_id))
    db.execute(delete(MachineEvent).where(MachineEvent.item_id == item_id))
    db.execute(delete(OperatorAction).where(OperatorAction.item_id == item_id))
    db.flush()

    item = db.get(Item, item_id)
    if item_value:
        route_revision_id = item.route_revision_id if item else None
        if not route_revision_id:
            route = db.scalar(select(RouteDefinition).where(RouteDefinition.code == (item_value.get("route_id") or "ROUTE-DEFAULT")))
            if route and item_value.get("route_revision") is not None:
                revision_number = _route_revision_number(item_value.get("route_revision"))
                revision = (
                    db.scalar(
                        select(RouteRevision).where(
                            RouteRevision.route_id == route.id,
                            RouteRevision.revision == revision_number,
                        )
                    )
                    if revision_number is not None
                    else None
                )
                route_revision_id = revision.id if revision else None
            elif route:
                route_revision_id = route.active_revision_id
        if item is None:
            structure_available = bool(db.scalar(select(ProductStructureSnapshot.id).where(
                ProductStructureSnapshot.assembly_id == item_value["product_definition_id"],
                ProductStructureSnapshot.revision == item_value["revision"],
            ).limit(1)))
            item = Item(
                item_id=item_id,
                product_definition_id=item_value["product_definition_id"],
                revision=item_value["revision"],
                line_id=item_value.get("line_id"),
                route_revision_id=route_revision_id,
                registered_at=item_value["registered_at"],
                structure_status="available" if structure_available else "degraded",
            )
            db.add(item)
        else:
            item.product_definition_id = item_value["product_definition_id"]
            item.revision = item_value["revision"]
            item.line_id = item_value.get("line_id")
            item.updated_at = utcnow()
    for run in operation_values.values():
        duration = run.get("duration") or {}
        db.add(
            OperationRun(
                operation_run_id=run["operation_run_id"],
                item_id=item_id,
                operation_id=run.get("operation_id"),
                operator_id=run.get("operator_id"),
                equipment_id=run.get("equipment_id"),
                station_id=run.get("station_id"),
                started_at=run.get("started_at"),
                finished_at=run.get("finished_at"),
                completion_status=run.get("completion_status"),
                duration_value=duration.get("value"),
                duration_unit=duration.get("unit"),
                duration_meaning=duration.get("meaning"),
                previous_operation_run_id=run.get("previous_operation_run_id"),
                run_reason=run.get("run_reason", "production"),
                rework_for_nonconformance_id=(uuid.UUID(run["rework_for_nonconformance_id"]) if run.get("rework_for_nonconformance_id") else None),
                parameters=run.get("parameters") or run.get("finish_parameters"),
            )
        )
    observation_ids: dict[str, uuid.UUID] = {}
    pending_defects: list[tuple[uuid.UUID, dict[str, Any], dict[str, Any]]] = []
    for value in observation_values:
        obs_id = uuid.uuid5(OBSERVATION_NAMESPACE, value["event_id"])
        observation_ids[value["event_id"]] = obs_id
        db.add(
            Observation(
                id=obs_id,
                event_id=value["event_id"],
                item_id=item_id,
                operation_run_id=value.get("operation_run_id"),
                occurred_at=value["occurred_at"],
                inspection_result=value["inspection_result"],
                observation_quality=value["observation_quality"],
                control_point_id=value["control_point_id"],
                confidence=value.get("confidence"),
                inspection_scope=value.get("inspection_scope"),
                component_instance_id=value.get("component_instance_id"),
                control_device_id=value.get("control_device_id"),
                capture_session_id=value.get("capture_session_id"),
                evidence_refs=value.get("evidence_refs", []),
                trust_status=value["trust_status"],
                trust_reasons=value["trust_reasons"],
            )
        )
        for defect in value.get("defects", []):
            pending_defects.append((obs_id, value, defect))

    # Flush parent observations first. Rebuilds use deterministic observation UUIDs and
    # bulk-delete the previous projection, so relying on implicit UoW ordering here can
    # race the FK on defect_observations during repeated rebuilds.
    db.flush()
    for obs_id, value, defect in pending_defects:
        db.add(
            DefectObservation(
                observation_id=obs_id,
                item_id=item_id,
                defect_type=defect["defect_type"],
                component_instance_id=defect.get("component_instance_id")
                or value.get("component_instance_id"),
                description=defect.get("description"),
                severity=defect.get("severity"),
            )
        )
    for value in machine_values:
        db.add(
            MachineEvent(
                event_id=value["event_id"],
                item_id=item_id,
                operation_run_id=value.get("operation_run_id"),
                equipment_id=value["equipment_id"],
                state=value["state"],
                code=value.get("code"),
                occurred_at=value["occurred_at"],
                parameters=value.get("parameters"),
            )
        )
    for value in action_values:
        db.add(
            OperatorAction(
                event_id=value["event_id"],
                item_id=item_id,
                operation_run_id=value.get("operation_run_id"),
                operator_id=value["operator_id"],
                action_type=value["action_type"],
                occurred_at=value["occurred_at"],
                parameters=value.get("parameters"),
            )
        )
    db.flush()

    operations_list = list(operation_values.values())
    limitations = _missing_check_limitations(db, item, operations_list, observation_values)
    for obs in observation_values:
        if obs["inspection_result"] != "defect_detected":
            continue
        for defect in obs.get("defects", []):
            component = defect.get("component_instance_id") or obs.get("component_instance_id")
            occurrence = db.scalar(
                select(DefectOccurrence).where(
                    DefectOccurrence.item_id == item_id,
                    DefectOccurrence.defect_type == defect["defect_type"],
                    DefectOccurrence.component_instance_id.is_(None)
                    if component is None
                    else DefectOccurrence.component_instance_id == component,
                    DefectOccurrence.status == "OPEN",
                )
            )
            if occurrence is None:
                occurrence = DefectOccurrence(
                    item_id=item_id,
                    defect_type=defect["defect_type"],
                    component_instance_id=component,
                    first_observation_id=observation_ids[obs["event_id"]],
                    current_observation_id=observation_ids[obs["event_id"]],
                    opened_at=obs["occurred_at"],
                )
                db.add(occurrence)
                db.flush()
            else:
                occurrence.current_observation_id = observation_ids[obs["event_id"]]
            ncr = db.scalar(select(Nonconformance).where(Nonconformance.occurrence_id == occurrence.id))
            if ncr is None:
                ncr = Nonconformance(
                    occurrence_id=occurrence.id,
                    item_id=item_id,
                    defect_type=defect["defect_type"],
                    component_instance_id=component,
                    verdict=(
                        "pending_review" if obs["trust_status"] == "TRUSTED" else "needs_extra_check"
                    ),
                    opened_at=obs["occurred_at"],
                )
                db.add(ncr)
                db.flush()
            if obs["trust_status"] == "TRUSTED":
                _create_analysis(
                    db,
                    ncr,
                    {
                        **obs,
                        "defect_type": defect["defect_type"],
                        "component_instance_id": component,
                    },
                    observation_values,
                    operations_list,
                    machine_values,
                    action_values,
                    limitations,
                )
            elif obs["trust_status"] == "INVALIDATED" and ncr.current_analysis_version:
                _create_invalidated_analysis(db, ncr, obs)

    state.latest_raw_ingest_seq = max(raw.ingest_seq for raw in raws)
    state.last_projected_ingest_seq = state.latest_raw_ingest_seq
    state.projection_version += 1
    state.status = "up_to_date"
    state.last_successful_rebuild_at = utcnow()
    state.last_error = None
    db.commit()


def mark_projection_failed(db: Session, item_id: str, safe_error: str) -> None:
    state = db.get(ProjectionState, item_id)
    if state is None:
        state = ProjectionState(item_id=item_id)
        db.add(state)
    state.status = "failed"
    state.last_error = safe_error[:2000]
    db.commit()


def recover_stale_projections(db: Session, settings: Settings) -> list[str]:
    item_ids = db.scalars(
        select(ProjectionState.item_id).where(
            (ProjectionState.latest_raw_ingest_seq > ProjectionState.last_projected_ingest_seq)
            | (ProjectionState.status.in_(["stale", "failed", "rebuilding"]))
        )
    ).all()
    recovered: list[str] = []
    for item_id in item_ids:
        try:
            rebuild_item(db, item_id, settings)
            recovered.append(item_id)
        except Exception as exc:  # recovery must continue for other items
            db.rollback()
            mark_projection_failed(db, item_id, f"{type(exc).__name__}: {exc}")
    return recovered
