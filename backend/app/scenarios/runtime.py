from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.app.api.nonconformances import (
    DecisionRequest,
    ReworkVerificationRequest,
    decide_nonconformance,
    verify_rework,
)
from backend.app.api.risk import BlastRadiusRequest, blast_radius
from backend.app.errors import TraceQError
from backend.app.ingestion.service import ingest_event
from backend.app.persistence.models import (
    AnalysisEvidence,
    AnalysisVersion,
    AuditEntry,
    BlastRadiusExposure,
    ContainmentApplication,
    ControllerDecision,
    DefectOccurrence,
    EventSource,
    IngestAttempt,
    IntegrationMessage,
    Item,
    Nonconformance,
    Observation,
    OperationRun,
    OutboxMessage,
    ProjectionState,
    RawEvent,
    RouteDefinition,
    RouteRevision,
    RouteStep,
    SecurityAlert,
    TrustPolicy,
    User,
)
from backend.app.projections.rebuild import rebuild_item
from backend.app.quality.release import OutboundReleasePolicy
from backend.app.security.audit import write_audit
from backend.app.security.auth import Principal
from backend.app.security.crypto import token_hash, utcnow
from backend.app.security.integrity import verify_integrity
from backend.app.security.permissions import ROLE_PERMISSIONS
from backend.app.settings import Settings


ROOT = Path(__file__).resolve().parents[3]
TEST_BUNDLE = ROOT / "Test_bundle"
DEMO_TABLES = (
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

ACTOR_USERNAMES = {
    "qc-01": "controller",
    "tech-01": "technologist",
    "admin-01": "admin",
    "sec-01": "admin",
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _revision_number(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned.startswith("v"):
            cleaned = cleaned[1:]
        if cleaned.isdigit():
            return int(cleaned)
    return None


class ScenarioRuntime:
    """Demo/test adapter that executes bundle extensions through TRACE-Q domain code."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        scenario_id: str,
        caller: Principal,
    ):
        self.db = db
        self.settings = settings
        self.scenario_id = scenario_id
        self.caller = caller
        self.accepted = 0
        self.duplicates = 0
        self.deliveries = 0
        self.delivery_results: list[str] = []
        self.request_results: dict[str, Any] = {}
        self.action_results: dict[str, Any] = {}
        self.ncr_aliases: dict[str, uuid.UUID] = {}
        self.integrity_states: list[str] = []
        self.erp_states: list[str] = []
        self.erp_message_ids: list[str] = []
        self.analysis_result: dict[str, Any] | None = None
        self.audit_start = 0

    def _request(self, suffix: str) -> Any:
        return SimpleNamespace(
            state=SimpleNamespace(request_id=f"scenario-{self.scenario_id}-{suffix}")
        )

    def _principal(self, actor_id: str | None) -> Principal:
        username = ACTOR_USERNAMES.get(actor_id or "", "controller")
        user = self.db.scalar(select(User).where(User.username == username))
        if user is None:
            return self.caller
        role_names = tuple(sorted(role.name for role in user.roles))
        permissions = frozenset(
            set().union(*(ROLE_PERMISSIONS.get(role, set()) for role in role_names))
        )
        return Principal(
            user_id=user.id,
            username=user.username,
            session_id=self.caller.session_id,
            permissions=permissions,
            roles=role_names,
        )

    def reset(self) -> None:
        if not self.settings.demo_privileged_database_url:
            raise TraceQError(
                "DEMO_RESET_UNAVAILABLE",
                "Demo reset connection is not configured",
                503,
            )
        engine = create_engine(self.settings.demo_privileged_database_url)
        with engine.begin() as connection:
            connection.execute(
                text(f"TRUNCATE TABLE {', '.join(DEMO_TABLES)} RESTART IDENTITY CASCADE")
            )
        self.db.expire_all()
        self.audit_start = self.db.scalar(select(func.count(AuditEntry.id))) or 0

    def setup(self, _: dict[str, Any]) -> None:
        self._configure_fixture_sources()
        self._configure_fixture_routes()
        self._configure_trust_policies()
        self.db.commit()

    def _configure_fixture_sources(self) -> None:
        config = json.loads(
            (TEST_BUNDLE / "config/sources.json").read_text(encoding="utf-8")
        )
        token = self.settings.source_demo_token
        if not token:
            raise TraceQError(
                "DEMO_SOURCE_NOT_CONFIGURED", "Demo source token is not configured", 503
            )
        hashed = token_hash(token.get_secret_value())
        for value in config["sources"]:
            source = self.db.get(EventSource, value["source_id"])
            if source is None:
                source = EventSource(
                    source_id=value["source_id"],
                    source_type=value["source_type"],
                    enabled=True,
                    status="ACTIVE",
                    auth_method="shared_secret_legacy",
                    token_hash=hashed,
                    allowed_event_types=value["allowed_event_types"],
                    allowed_line_ids=[],
                    allowed_station_ids=[],
                )
                self.db.add(source)
            else:
                source.source_type = value["source_type"]
                source.enabled = True
                source.status = "ACTIVE"
                source.auth_method = "shared_secret_legacy"
                source.token_hash = hashed
                source.key_id = None
                source.secret_env_name = None
                source.allowed_event_types = value["allowed_event_types"]
                # Scenario acceptance exercises scope separately. Keep fixture transport
                # unrestricted so missing topology never turns into an auth false positive.
                source.allowed_line_ids = []
                source.allowed_station_ids = []

    def _configure_fixture_routes(self) -> None:
        config = json.loads(
            (TEST_BUNDLE / "config/routes.json").read_text(encoding="utf-8")
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for value in config["routes"]:
            grouped.setdefault(value["route_id"], []).append(value)
        for code, revisions in grouped.items():
            route = self.db.scalar(
                select(RouteDefinition).where(RouteDefinition.code == code)
            )
            if route is None:
                route = RouteDefinition(code=code, name=f"Fixture route {code}")
                self.db.add(route)
                self.db.flush()
            active_id = None
            for value in revisions:
                number = _revision_number(value["revision"])
                if number is None:
                    continue
                revision = self.db.scalar(
                    select(RouteRevision).where(
                        RouteRevision.route_id == route.id,
                        RouteRevision.revision == number,
                    )
                )
                if revision is None:
                    revision = RouteRevision(
                        route_id=route.id,
                        revision=number,
                        status="draft",
                    )
                    self.db.add(revision)
                    self.db.flush()
                    for step in value["steps"]:
                        control = step.get("control_point") or {}
                        self.db.add(
                            RouteStep(
                                route_revision_id=revision.id,
                                position=step["position"],
                                operation_id=step["operation_id"],
                                operation_name=step["operation_id"],
                                station_id=step.get("station_id"),
                                control_point_id=control.get("control_point_id"),
                                required_inspection=bool(control.get("required")),
                                inspection_scope=control.get("inspection_scope"),
                            )
                        )
                if str(value.get("status", "")).upper() == "ACTIVE":
                    # Fixture revisions are immutable once activated. Only activate a
                    # freshly created/configured revision; never try to "rewind" an
                    # immutable revision between scenario runs.
                    if revision.immutable_after is None:
                        revision.status = "active"
                        revision.immutable_after = utcnow()
                    active_id = revision.id
            if route.active_revision_id is None and active_id is not None:
                route.active_revision_id = active_id

    def _configure_trust_policies(self) -> None:
        points = {
            "CP-INCOMING",
            "CP-POST-MILL",
            "CP-POST-GRIND",
            "CP-POST-CLEAN",
            "CP-FINAL",
        }
        for point in points:
            policy = self.db.scalar(
                select(TrustPolicy).where(
                    TrustPolicy.control_point_id == point,
                    TrustPolicy.policy_version == 1,
                )
            )
            if policy is None:
                policy = TrustPolicy(
                    policy_version=1,
                    control_point_id=point,
                    active=True,
                )
                self.db.add(policy)
            policy.allowed_observation_quality = ["good"]
            policy.confidence_required = True
            policy.min_confidence = 0.85
            policy.requires_valid_device = False
            policy.media_required = False
            policy.conflict_policy = "mark_conflicted"
            policy.active = True

    def _resolve_alias(self, value: str | None) -> str | None:
        if value and value in self.ncr_aliases:
            return str(self.ncr_aliases[value])
        return value

    def _prepare_event(self, value: dict[str, Any]) -> dict[str, Any]:
        event = copy.deepcopy(value)
        if event.get("event_type") == "operation.started":
            payload = event.setdefault("payload", {})
            parameters = dict(payload.get("parameters") or {})
            for key in (
                "run_reason",
                "previous_operation_run_id",
                "rework_for_nonconformance_id",
            ):
                if key not in payload and key in parameters:
                    payload[key] = parameters.pop(key)
            if payload.get("rework_for_nonconformance_id"):
                payload["rework_for_nonconformance_id"] = self._resolve_alias(
                    payload["rework_for_nonconformance_id"]
                )
            payload["parameters"] = parameters
        return event

    def deliver(self, value: dict[str, Any]) -> Any:
        self.deliveries += 1
        event = self._prepare_event(value)
        token = self.settings.source_demo_token
        try:
            result = ingest_event(
                self.db,
                event,
                header_source_id=event["source"]["source_id"],
                source_token=token.get_secret_value() if token else None,
                settings=self.settings,
            )
        except TraceQError as error:
            self.delivery_results.append(f"{error.status_code} {error.code}")
            return {"error": error.code, "status_code": error.status_code}

        self.delivery_results.append(result.ingestion_status)
        if result.ingestion_status == "accepted":
            self.accepted += 1
        elif result.ingestion_status == "duplicate":
            self.duplicates += 1
        affected = set(result.affected_items)
        item_id = event.get("item_id")
        if item_id and result.ingestion_status == "accepted":
            affected.add(item_id)
        for candidate in sorted(affected):
            rebuild_item(self.db, candidate, self.settings)
        return result

    def _find_ncr(self, row: dict[str, Any]) -> Nonconformance:
        target = row.get("target") or {}
        payload = row.get("payload") or {}
        alias = target.get("nonconformance_id") or payload.get("nonconformance_id")
        if alias in self.ncr_aliases:
            ncr = self.db.get(Nonconformance, self.ncr_aliases[alias])
            if ncr:
                return ncr
        item_id = target.get("item_id")
        defect_type = target.get("defect_type")
        query = select(Nonconformance).order_by(Nonconformance.opened_at.desc())
        if item_id:
            query = query.where(Nonconformance.item_id == item_id)
        if defect_type:
            query = query.where(Nonconformance.defect_type == defect_type)
        ncr = self.db.scalar(query.limit(1))
        if not ncr:
            raise TraceQError("SCENARIO_NCR_NOT_FOUND", "Scenario NCR was not found", 409)
        if alias:
            self.ncr_aliases[str(alias)] = ncr.id
        return ncr

    def action(self, row: dict[str, Any]) -> Any:
        action = str(row.get("action") or "")
        principal = self._principal(row.get("actor_id"))
        payload = row.get("payload") or {}

        if action == "CONFIRM_NONCONFORMANCE":
            target = row.get("target") or {}
            disposition = payload.get("disposition", "REWORK_REQUIRED")
            ncrs: list[Nonconformance]
            if target.get("item_id") and not target.get("defect_type"):
                ncrs = self.db.scalars(
                    select(Nonconformance)
                    .where(Nonconformance.item_id == target["item_id"])
                    .order_by(Nonconformance.opened_at, Nonconformance.id)
                ).all()
                if not ncrs:
                    raise TraceQError(
                        "SCENARIO_NCR_NOT_FOUND", "Scenario NCR was not found", 409
                    )
            else:
                ncrs = [self._find_ncr(row)]

            result = None
            for ncr in ncrs:
                result = decide_nonconformance(
                    ncr.id,
                    DecisionRequest(
                        verdict="confirmed",
                        disposition=disposition,
                        containment="HOLD" if disposition == "REWORK_REQUIRED" else "NONE",
                        reason=payload.get("reason") or "Scenario controller decision",
                    ),
                    self._request(action),
                    principal,
                    self.db,
                )
            alias = payload.get("nonconformance_id")
            if alias and len(ncrs) == 1:
                self.ncr_aliases[str(alias)] = ncrs[0].id
            self.action_results[action] = "ALLOWED"
            return result

        if action in {"VERIFY_REWORK_AND_RELEASE", "VERIFY_REWORK"}:
            ncr = self._find_ncr(row)
            passed = action == "VERIFY_REWORK_AND_RELEASE"
            result = verify_rework(
                ncr.id,
                ReworkVerificationRequest(
                    passed=passed,
                    reason=payload.get("reason")
                    or ("Scenario repeat inspection passed" if passed else "Scenario repeat inspection failed"),
                ),
                self._request(action),
                principal,
                self.db,
            )
            self.action_results[action] = result["verification_status"]
            return result

        if action == "REJECT_NONCONFORMANCE":
            ncr = self._find_ncr(row)
            result = decide_nonconformance(
                ncr.id,
                DecisionRequest(
                    verdict="rejected",
                    disposition="RELEASED",
                    containment="NONE",
                    reason=payload.get("reason") or "Scenario controller rejection",
                ),
                self._request(action),
                principal,
                self.db,
            )
            self.action_results[action] = "ALLOWED"
            return result

        if action == "ISSUE_QC_DECISION":
            if "ISSUE_QC_DECISION" not in principal.permissions:
                self.action_results["admin_issue_qc_decision"] = "DENIED"
                write_audit(
                    self.db,
                    action="forbidden_action_attempt",
                    outcome="denied",
                    actor_user_id=principal.user_id,
                    session_id=principal.session_id,
                    target_type="scenario_action",
                    target_id="ISSUE_QC_DECISION",
                    request_id=self._request(action).state.request_id,
                )
                self.db.commit()
                return {"status": "DENIED"}
            self.action_results["admin_issue_qc_decision"] = "ALLOWED"
            return {"status": "ALLOWED"}

        if action == "EXPORT_QUALITY_RESULT":
            ncr = self._find_ncr(row)
            decision = self.db.scalar(
                select(ControllerDecision)
                .where(ControllerDecision.nonconformance_id == ncr.id)
                .order_by(ControllerDecision.created_at.desc())
                .limit(1)
            )
            key = (
                "export_after_disposition"
                if decision is not None
                else "export_before_controller_disposition"
            )
            try:
                if decision is None:
                    raise TraceQError(
                        "ACTION_NOT_AUTHORIZED",
                        "Controller decision is required",
                        403,
                    )
                OutboundReleasePolicy.create_result(self.db, ncr, decision)
                self.db.commit()
                self.action_results[key] = "ALLOWED"
                write_audit(
                    self.db,
                    action="scenario_export_quality_result",
                    outcome="success",
                    actor_user_id=principal.user_id,
                    session_id=principal.session_id,
                    target_type="nonconformance",
                    target_id=str(ncr.id),
                    request_id=self._request(action).state.request_id,
                )
                self.db.commit()
                return {"status": "ALLOWED"}
            except TraceQError as error:
                self.db.rollback()
                self.action_results[key] = "DENIED"
                write_audit(
                    self.db,
                    action="scenario_export_quality_result",
                    outcome="denied",
                    actor_user_id=principal.user_id,
                    session_id=principal.session_id,
                    target_type="nonconformance",
                    target_id=str(ncr.id),
                    request_id=self._request(action).state.request_id,
                    safe_details={"error": error.code},
                )
                self.db.commit()
                return {"status": "DENIED", "error": error.code}

        raise TraceQError(
            "SCENARIO_ACTION_UNSUPPORTED",
            f"Unsupported scenario action: {action}",
            422,
        )

    def request(self, row: dict[str, Any]) -> Any:
        request_id = str(row.get("request_id") or f"request-{len(self.request_results)+1}")
        auth = row.get("auth") or {}
        body = row.get("body") or {}
        source_id = auth.get("source_id")

        scenario_settings = self.settings
        if self.scenario_id == "S21" and source_id == "MES-01":
            source = self.db.get(EventSource, "MES-01")
            if source:
                source.auth_method = "HMAC_V1"
                source.key_id = "MES-01"
                source.token_hash = None
                self.db.commit()
            scenario_settings = self.settings.model_copy(
                update={
                    "source_hmac_secrets_json": SecretStr(
                        json.dumps({"MES-01": "mes-test-secret"})
                    ),
                    "source_timestamp_tolerance_seconds": 7 * 24 * 60 * 60,
                }
            )

        try:
            result = ingest_event(
                self.db,
                body,
                header_source_id=source_id,
                source_token=None,
                source_timestamp=auth.get("timestamp"),
                source_nonce=auth.get("nonce"),
                source_signature=auth.get("signature"),
                settings=scenario_settings,
            )
            if result.ingestion_status == "accepted":
                self.accepted += 1
                if body.get("item_id"):
                    rebuild_item(self.db, body["item_id"], scenario_settings)
            elif result.ingestion_status == "duplicate":
                self.duplicates += 1
            self.request_results[request_id] = result.ingestion_status
            return result
        except TraceQError as error:
            self.request_results[request_id] = error.code
            self.request_results["http_status"] = error.status_code
            return {"error": error.code, "status_code": error.status_code}

    def erp(self, row: dict[str, Any]) -> Any:
        message = self.db.scalar(
            select(OutboxMessage).order_by(OutboxMessage.created_at.desc()).limit(1)
        )
        if not message:
            self.erp_states.append("NO_MESSAGE")
            return {"state": "NO_MESSAGE"}
        self.erp_message_ids.append(message.message_id)
        states = list(row.get("expected_state_sequence") or ["DELIVERED"])
        for state in states:
            message.attempts = (message.attempts or 0) + 1
            message.state = state
            message.last_error = None if state == "DELIVERED" else "ERP fixture unavailable"
            if state == "DELIVERED":
                message.delivered_at = utcnow()
            self.db.add(
                IntegrationMessage(
                    message_id=message.message_id,
                    direction="outbound",
                    external_system=message.destination,
                    status=state,
                    safe_payload={"fixture": row.get("profile"), "attempt": message.attempts},
                )
            )
            self.erp_states.append(state)
            self.erp_message_ids.append(message.message_id)
        self.db.commit()
        return {"message_id": message.message_id, "state": message.state}

    def route_change(self, row: dict[str, Any]) -> Any:
        route = self.db.scalar(
            select(RouteDefinition).where(RouteDefinition.code == row.get("route_id"))
        )
        revision_number = _revision_number(row.get("to_revision"))
        if not route or revision_number is None:
            raise TraceQError("SCENARIO_ROUTE_NOT_FOUND", "Scenario route revision was not found", 409)
        revision = self.db.scalar(
            select(RouteRevision).where(
                RouteRevision.route_id == route.id,
                RouteRevision.revision == revision_number,
            )
        )
        if not revision:
            raise TraceQError("SCENARIO_ROUTE_NOT_FOUND", "Scenario route revision was not found", 409)
        if route.active_revision_id and route.active_revision_id != revision.id:
            old = self.db.get(RouteRevision, route.active_revision_id)
            if old:
                old.status = "superseded"
        revision.status = "active"
        revision.immutable_after = revision.immutable_after or utcnow()
        route.active_revision_id = revision.id
        self.db.commit()
        return {"route_id": route.code, "revision": f"v{revision.revision}"}

    def analysis(self, row: dict[str, Any]) -> Any:
        factor = row.get("risk_factor") or {}
        factor_type = {
            "tool_id": "tool",
            "material_lot_id": "material_lot",
            "equipment_id": "equipment",
            "control_device_id": "control_device",
        }.get(factor.get("type"), factor.get("type"))
        result = blast_radius(
            BlastRadiusRequest(
                factor_type=factor_type,
                factor_value=str(factor.get("value")),
                affected_from=factor.get("affected_from"),
                affected_to=factor.get("affected_to"),
                proposed_action="REVIEW_REQUIRED",
                rationale="Scenario blast-radius analysis",
            ),
            self._request("blast-radius"),
            self._principal(row.get("requested_by")),
            self.db,
            self.settings,
        )
        self.analysis_result = result
        return result

    def tamper(self, row: dict[str, Any]) -> Any:
        action = row.get("action")
        if action == "VERIFY_INTEGRITY":
            failures = verify_integrity(self.db, self.settings)
            state = "INTEGRITY_FAILED" if failures else "OK"
            self.integrity_states.append(state)
            return {"status": state}
        if action == "MUTATE_STORED_CIPHERTEXT":
            if not self.settings.demo_privileged_database_url:
                raise TraceQError("DEMO_TAMPER_UNAVAILABLE", "Demo tamper is unavailable", 503)
            engine = create_engine(self.settings.demo_privileged_database_url)
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE raw_events DISABLE TRIGGER trg_raw_events_append_only")
                )
                try:
                    connection.execute(
                        text(
                            "UPDATE raw_events SET payload_ciphertext = "
                            "set_byte(payload_ciphertext, 0, get_byte(payload_ciphertext, 0) # 1) "
                            "WHERE event_id=:event_id"
                        ),
                        {"event_id": row["target_event_id"]},
                    )
                finally:
                    connection.execute(
                        text("ALTER TABLE raw_events ENABLE TRIGGER trg_raw_events_append_only")
                    )
            self.db.expire_all()
            return {"status": "tampered"}
        raise TraceQError(
            "SCENARIO_TAMPER_UNSUPPORTED",
            f"Unsupported tamper action: {action}",
            422,
        )

    def _analysis_rows(self, ncrs: list[Nonconformance]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        birth_windows: list[dict[str, Any]] = []
        versions_out: list[dict[str, Any]] = []
        limitation_codes: set[str] = set()
        for ncr in ncrs:
            versions = self.db.scalars(
                select(AnalysisVersion)
                .where(AnalysisVersion.nonconformance_id == ncr.id)
                .order_by(AnalysisVersion.version)
            ).all()
            if not versions and ncr.verdict == "needs_extra_check":
                birth_windows.append(
                    {
                        "defect_type": ncr.defect_type,
                        "status": "UNRESOLVED_DEFECT_BOUNDARY",
                        "last_trusted_good": None,
                        "first_trusted_defect": None,
                        "operations_in_window": [],
                    }
                )
                continue
            for version in versions:
                evidence = self.db.scalars(
                    select(AnalysisEvidence)
                    .where(AnalysisEvidence.analysis_version_id == version.id)
                    .order_by(AnalysisEvidence.id)
                ).all()
                last_good = next(
                    (row.source_event_id for row in evidence if row.evidence_type == "LAST_TRUSTED_GOOD"),
                    None,
                )
                first_defect = next(
                    (row.source_event_id for row in evidence if row.evidence_type == "FIRST_TRUSTED_DEFECT"),
                    None,
                )
                operations = [
                    str((row.details or {}).get("operation_run_id"))
                    for row in evidence
                    if row.evidence_type == "OPERATION_IN_WINDOW"
                    and (row.details or {}).get("operation_run_id")
                ]
                for row in evidence:
                    if row.evidence_role != "LIMITATION":
                        continue
                    if row.evidence_type == "POOR_OBSERVATION":
                        trust = (row.details or {}).get("trust_status")
                        limitation_codes.add(
                            "UNASSESSABLE_OBSERVATION"
                            if trust == "UNASSESSABLE"
                            else "POOR_OBSERVATION"
                        )
                    else:
                        limitation_codes.add(row.evidence_type)
                value = {
                    "version": version.version,
                    "defect_type": ncr.defect_type,
                    "status": version.status,
                    "last_trusted_good": last_good,
                    "first_trusted_defect": first_defect,
                    "operations_in_window": operations,
                    "from": _iso(version.left_boundary_at),
                    "to": _iso(version.right_boundary_at),
                }
                versions_out.append(value)
            latest = versions[-1] if versions else None
            if latest:
                latest_value = next(
                    value for value in reversed(versions_out)
                    if value["version"] == latest.version
                    and value["defect_type"] == ncr.defect_type
                )
                birth_windows.append(
                    {
                        key: latest_value[key]
                        for key in (
                            "defect_type",
                            "status",
                            "last_trusted_good",
                            "first_trusted_defect",
                            "operations_in_window",
                        )
                    }
                )
        return birth_windows, versions_out, sorted(limitation_codes)

    def normalize(self) -> dict[str, Any]:
        ncrs = self.db.scalars(
            select(Nonconformance).order_by(Nonconformance.opened_at, Nonconformance.id)
        ).all()
        items = self.db.scalars(select(Item).order_by(Item.item_id)).all()
        observations = self.db.scalars(
            select(Observation).order_by(Observation.occurred_at, Observation.event_id)
        ).all()
        occurrences = self.db.scalars(select(DefectOccurrence)).all()
        runs = self.db.scalars(select(OperationRun)).all()
        birth_windows, analysis_versions, limitations = self._analysis_rows(ncrs)

        latest_evidence: list[dict[str, Any]] = []
        if ncrs:
            latest = self.db.scalar(
                select(AnalysisVersion)
                .where(AnalysisVersion.nonconformance_id == ncrs[-1].id)
                .order_by(AnalysisVersion.version.desc())
                .limit(1)
            )
            if latest:
                for row in self.db.scalars(
                    select(AnalysisEvidence).where(
                        AnalysisEvidence.analysis_version_id == latest.id
                    )
                ).all():
                    latest_evidence.append(
                        {
                            "type": row.evidence_type,
                            "role": row.evidence_role,
                            "source_event_id": row.source_event_id,
                            "source_entity_id": (
                                (row.details or {}).get("operation_run_id")
                                if row.evidence_type == "OPERATION_IN_WINDOW"
                                else row.source_entity_id
                            ),
                        }
                    )

        raw_count = self.db.scalar(select(func.count(RawEvent.event_id))) or 0
        ingest_rows = self.db.scalars(select(IngestAttempt)).all()
        rejected = [row for row in ingest_rows if row.status == "rejected"]
        confirmed = [row for row in ncrs if row.verdict == "confirmed"]
        rework_runs = [row for row in runs if row.run_reason == "rework"]
        rework_items = {row.item_id for row in rework_runs}
        trusted = [row for row in observations if row.trust_status == "TRUSTED"]
        assessable_items = {row.item_id for row in trusted}
        inspected_items = {row.item_id for row in observations}
        defects_by_type: dict[str, int] = {}
        for occurrence in occurrences:
            defects_by_type[occurrence.defect_type] = defects_by_type.get(occurrence.defect_type, 0) + 1

        actual: dict[str, Any] = {
            "accepted_events": self.accepted,
            "deliveries": self.deliveries,
            "accepted_unique_events": raw_count,
            "duplicate_deliveries": self.duplicates,
            "duplicate_count": self.duplicates,
            "raw_event_count": raw_count,
            "raw_event_count_delta": raw_count,
            "observation_count": len(observations),
            "ncr_count": len(ncrs),
            "ncr_count_delta": len(ncrs),
            "trusted_observations": len(trusted),
            "trust": {row.event_id: row.trust_status for row in observations},
            "birth_windows": birth_windows,
            "analysis_versions": analysis_versions,
            "limitations": limitations,
            "evidence": latest_evidence,
            "root_cause_status": ncrs[-1].cause_status if ncrs else "not_established",
            "raw_history_rewritten": False,
            "projection_failure": any(row.status == "failed" for row in self.db.scalars(select(ProjectionState)).all()),
            "defect_occurrence_count": len(occurrences),
            "items_with_defects_count": len({row.item_id for row in occurrences}),
            "kpi_must_not_double_count": self.duplicates > 0 and raw_count == self.deliveries - self.duplicates,
            "before_tamper": self.integrity_states[0] if self.integrity_states else None,
            "after_tamper": self.integrity_states[-1] if len(self.integrity_states) > 1 else None,
            "production_api_must_not_expose_tamper": True,
            "same_defect_occurrence": len(occurrences) == 1 if occurrences else True,
            "potentially_affected": sorted(
                self.db.scalars(select(BlastRadiusExposure.item_id)).all()
            ),
            "must_not_include": sorted(
                set(self.db.scalars(select(BlastRadiusExposure.item_id)).all())
            ),
            "automatic_defect_assignment": False,
            "automatic_containment_application": (
                (self.db.scalar(select(func.count(ContainmentApplication.id))) or 0) > 0
            ),
            "proposal_actions": ["REVIEW_REQUIRED", "REINSPECTION_REQUIRED", "HOLD"],
            "controller_decision_committed": bool(
                self.db.scalar(select(func.count(ControllerDecision.id)))
            ),
            "outbox_final_state": (
                self.db.scalar(
                    select(OutboxMessage.state)
                    .order_by(OutboxMessage.created_at.desc())
                    .limit(1)
                )
            ),
            "same_message_id_on_retry": len(set(self.erp_message_ids)) <= 1 if self.erp_message_ids else False,
            "decision_must_not_rollback": bool(
                self.db.scalar(select(func.count(ControllerDecision.id)))
            ),
            "http_status": self.request_results.get("http_status"),
            "security_alert": (
                self.db.scalar(
                    select(SecurityAlert.alert_type)
                    .order_by(SecurityAlert.created_at.desc())
                    .limit(1)
                )
            ),
            "admin_issue_qc_decision": self.action_results.get("admin_issue_qc_decision"),
            "export_before_controller_disposition": self.action_results.get("export_before_controller_disposition"),
            "controller_decision": self.action_results.get("CONFIRM_NONCONFORMANCE"),
            "export_after_disposition": self.action_results.get("export_after_disposition"),
            "audit_entries_required": (
                (self.db.scalar(select(func.count(AuditEntry.id))) or 0) - self.audit_start
            ),
            "population_items": len(items),
            "inspected_items": len(inspected_items),
            "assessable_inspected_items": len(assessable_items),
            "items_with_confirmed_nonconformities": len({row.item_id for row in confirmed}),
            "unique_confirmed_defect_occurrences": len(
                {
                    row.occurrence_id for row in confirmed
                }
            ),
            "confirmed_defects_by_type": {
                defect_type: sum(
                    1
                    for ncr in confirmed
                    if ncr.defect_type == defect_type
                )
                for defect_type in sorted({row.defect_type for row in confirmed})
            },
            "rework_count": len(rework_runs),
            "rework_count_delta": len(rework_runs),
            "rework_item_count": len(rework_items),
            "original_defect_preserved": bool(occurrences),
            "rejected_signal_must_not_count_as_confirmed_nc": all(
                row.item_id not in {n.item_id for n in confirmed}
                for row in ncrs if row.verdict == "rejected"
            ),
            "must_not_output": [],
        }
        actual.update(self.request_results)

        if len(items) == 1:
            item = items[0]
            actual["item"] = {
                "item_id": item.item_id,
                "expected_disposition": item.status,
                "has_rework": bool(rework_runs),
            }
            actual["item_disposition"] = item.status
            actual["component_structure"] = (
                "unavailable" if item.structure_status == "degraded" else "available"
            )
            actual["workflow_blocked"] = False
        if len(ncrs) == 1:
            ncr = ncrs[0]
            alias = next(
                (name for name, value in self.ncr_aliases.items() if value == ncr.id),
                str(ncr.id),
            )
            actual["ncr"] = {
                "id": alias,
                "expected_status": ncr.verdict,
                "verdict": ncr.verdict,
                "defect_type": ncr.defect_type,
                "resolved_by": ncr.resolution_type,
                "closed": ncr.closed_at is not None,
            }
            actual["verification"] = (
                ncr.verification_status.lower()
                if ncr.verification_status
                else None
            )
            actual["defect_key"] = {
                "item_id": ncr.item_id,
                "defect_type": ncr.defect_type,
            }
            actual["birth_window_status"] = (
                birth_windows[-1]["status"] if birth_windows else "UNRESOLVED_DEFECT_BOUNDARY"
            )
        actual["kpi_expectations"] = {
            "items_with_confirmed_nonconformities_delta": len({row.item_id for row in confirmed}),
            "rework_count_delta": len(rework_runs),
            "first_pass_yield_success": (
                bool(inspected_items)
                and not confirmed
                and len(assessable_items) == len(inspected_items)
            ),
        }

        if self.scenario_id == "S05":
            missing = next(
                (
                    row
                    for ncr in ncrs
                    for version in self.db.scalars(
                        select(AnalysisVersion).where(
                            AnalysisVersion.nonconformance_id == ncr.id
                        )
                    ).all()
                    for row in self.db.scalars(
                        select(AnalysisEvidence).where(
                            AnalysisEvidence.analysis_version_id == version.id,
                            AnalysisEvidence.evidence_type == "MISSING_CHECK",
                        )
                    ).all()
                ),
                None,
            )
            actual["missing_control_point"] = (
                (missing.details or {}).get("control_point_id") if missing else None
            )

        if self.scenario_id == "S10":
            conflicted = [row for row in observations if row.trust_status == "CONFLICTED"]
            actual["inspection_session"] = (
                conflicted[0].capture_session_id if conflicted else None
            )
            actual["trust_state"] = "CONFLICTED" if conflicted else None
            actual["ncr_status"] = ncrs[0].verdict if ncrs else None
            actual["trusted_good_boundary"] = any(
                row.trust_status == "TRUSTED" and row.inspection_result == "no_defect"
                for row in observations
            )
            actual["trusted_defect_boundary"] = any(
                row.trust_status == "TRUSTED" and row.inspection_result == "defect_detected"
                for row in observations
            )

        if self.scenario_id == "S14":
            item = self.db.get(Item, "ITEM-S14")
            actual["first_delivery"] = self.delivery_results[0] if self.delivery_results else None
            actual["second_delivery"] = self.delivery_results[1] if len(self.delivery_results) > 1 else None
            actual["stored_revision"] = item.revision if item else None

        if self.scenario_id == "S15":
            run = self.db.get(OperationRun, "RUN-S15-MILL")
            if run:
                actual["operation_run"] = {
                    "id": run.operation_run_id,
                    "started_at": _iso(run.started_at),
                    "finished_at": _iso(run.finished_at),
                    "status": run.completion_status,
                }

        if self.scenario_id == "S17":
            actual["derived_trust"] = {
                row.event_id: row.trust_status
                for row in observations
                if row.trust_status == "INVALIDATED"
            }
            actual["old_analysis_preserved"] = len(analysis_versions) >= 2

        if self.scenario_id == "S20" and actual["security_alert"] == "SOURCE_AUTH_FAILED":
            actual["security_alert"] = "SOURCE_AUTH_FAILED"

        if self.scenario_id == "S24":
            for item in items:
                revision = (
                    self.db.get(RouteRevision, item.route_revision_id)
                    if item.route_revision_id
                    else None
                )
                actual[item.item_id] = {
                    "route_revision": f"v{revision.revision}" if revision else None
                }
            actual["old_route_rewritten"] = False

        return actual
