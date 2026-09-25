from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Identity,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(96), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class EventSource(Base):
    __tablename__ = "event_sources"
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    auth_method: Mapped[str] = mapped_column(String(32), default="shared_secret_legacy")
    token_hash: Mapped[str | None] = mapped_column(String(255))
    secret_env_name: Mapped[str | None] = mapped_column(String(128))
    key_id: Mapped[str | None] = mapped_column(String(128))
    allowed_event_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_line_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_station_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source_sequence: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestAttempt(Base):
    __tablename__ = "ingest_attempts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_id: Mapped[str | None] = mapped_column(String(128), index=True)
    claimed_event_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    raw_event_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    rejected_payload_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    safe_error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class TransportNonce(Base):
    __tablename__ = "transport_nonces"
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecurityAlert(Base):
    __tablename__ = "security_alerts"
    id: Mapped[uuid.UUID] = uuid_pk()
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    source_id: Mapped[str | None] = mapped_column(String(128), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrityStreamState(Base):
    __tablename__ = "integrity_stream_states"
    stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_mac: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    status: Mapped[str] = mapped_column(String(32), default="OK")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawEvent(Base):
    __tablename__ = "raw_events"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    source_sequence: Mapped[int | None] = mapped_column(BigInteger)
    item_id: Mapped[str | None] = mapped_column(String(128), index=True)
    operation_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ingest_seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    payload_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    content_hash: Mapped[str] = mapped_column(String(64))
    integrity_stream_id: Mapped[str] = mapped_column(String(128), index=True)
    integrity_seq: Mapped[int] = mapped_column(BigInteger)
    prev_integrity_mac: Mapped[bytes] = mapped_column(LargeBinary)
    integrity_mac: Mapped[bytes] = mapped_column(LargeBinary)
    crypto_key_id: Mapped[str] = mapped_column(String(128))
    key_version: Mapped[str] = mapped_column(String(32), default="1")
    crypto_profile_id: Mapped[str] = mapped_column(String(64), default="classic-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("integrity_stream_id", "integrity_seq", name="uq_integrity_stream_seq"),
        Index("ix_raw_event_business_order", "item_id", "occurred_at", "source_id"),
    )


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(96), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    safe_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    integrity_sequence: Mapped[int | None] = mapped_column(BigInteger)
    prev_integrity_mac: Mapped[bytes | None] = mapped_column(LargeBinary)
    integrity_mac: Mapped[bytes | None] = mapped_column(LargeBinary)


class ProductDefinition(Base):
    __tablename__ = "product_definitions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    revision: Mapped[str] = mapped_column(String(64))


class ComponentDefinition(Base):
    __tablename__ = "component_definitions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    revision: Mapped[str] = mapped_column(String(64))


class ItemComponent(Base):
    __tablename__ = "item_components"
    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    component_instance_id: Mapped[str] = mapped_column(String(128), unique=True)
    component_definition_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_component_instance_id: Mapped[str | None] = mapped_column(String(128))


class Line(Base):
    __tablename__ = "lines"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    line_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))


class Operator(Base):
    __tablename__ = "operators"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_code: Mapped[str] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    station_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))


class OperationDefinition(Base):
    __tablename__ = "operation_definitions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    expected_duration_seconds: Mapped[float | None] = mapped_column(Float)


class Item(Base):
    __tablename__ = "items"
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_definition_id: Mapped[str] = mapped_column(String(128), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    line_id: Mapped[str | None] = mapped_column(String(128), index=True)
    route_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="IN_PROCESS")
    structure_status: Mapped[str] = mapped_column(String(32), default="available")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperationRun(Base):
    __tablename__ = "operation_runs"
    operation_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    operator_id: Mapped[str | None] = mapped_column(String(128), index=True)
    equipment_id: Mapped[str | None] = mapped_column(String(128), index=True)
    station_id: Mapped[str | None] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_status: Mapped[str | None] = mapped_column(String(32))
    duration_value: Mapped[float | None] = mapped_column(Float)
    duration_unit: Mapped[str | None] = mapped_column(String(16))
    duration_meaning: Mapped[str | None] = mapped_column(String(64))
    previous_operation_run_id: Mapped[str | None] = mapped_column(String(128))
    run_reason: Mapped[str] = mapped_column(String(32), default="production")
    rework_for_nonconformance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    inspection_result: Mapped[str] = mapped_column(String(32))
    observation_quality: Mapped[str] = mapped_column(String(32))
    control_point_id: Mapped[str] = mapped_column(String(128), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    inspection_scope: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    component_instance_id: Mapped[str | None] = mapped_column(String(128), index=True)
    control_device_id: Mapped[str | None] = mapped_column(String(128), index=True)
    capture_session_id: Mapped[str | None] = mapped_column(String(128))
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    trust_status: Mapped[str] = mapped_column(String(32), index=True)
    trust_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)


class DefectObservation(Base):
    __tablename__ = "defect_observations"
    id: Mapped[uuid.UUID] = uuid_pk()
    observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("observations.id"))
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    defect_type: Mapped[str] = mapped_column(String(128), index=True)
    component_instance_id: Mapped[str | None] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(32))


class MachineEvent(Base):
    __tablename__ = "machine_events"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[str | None] = mapped_column(String(128), index=True)
    operation_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    equipment_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(64))
    code: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class OperatorAction(Base):
    __tablename__ = "operator_actions"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[str | None] = mapped_column(String(128), index=True)
    operation_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    operator_id: Mapped[str] = mapped_column(String(128), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class DefectOccurrence(Base):
    __tablename__ = "defect_occurrences"
    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    defect_type: Mapped[str] = mapped_column(String(128), index=True)
    component_instance_id: Mapped[str | None] = mapped_column(String(128), index=True)
    first_observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    current_observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Nonconformance(Base):
    __tablename__ = "nonconformities"
    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    defect_type: Mapped[str] = mapped_column(String(128), index=True)
    component_instance_id: Mapped[str | None] = mapped_column(String(128))
    verdict: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    cause_status: Mapped[str] = mapped_column(String(32), default="not_established")
    disposition: Mapped[str] = mapped_column(String(32), default="IN_PROCESS")
    containment: Mapped[str] = mapped_column(String(32), default="REVIEW_REQUIRED")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_analysis_version: Mapped[int] = mapped_column(Integer, default=1)
    resolution_type: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verification_status: Mapped[str | None] = mapped_column(String(32))


class AnalysisVersion(Base):
    __tablename__ = "analysis_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    nonconformance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    defect_type: Mapped[str] = mapped_column(String(128))
    component_instance_id: Mapped[str | None] = mapped_column(String(128))
    left_boundary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    right_boundary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    algorithm_version: Mapped[str] = mapped_column(String(32), default="birth-window-v1")
    reason: Mapped[str] = mapped_column(String(128), default="projection_rebuild")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("nonconformance_id", "version", name="uq_analysis_nc_version"),
    )


class AnalysisEvidence(Base):
    __tablename__ = "analysis_evidence"
    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    evidence_type: Mapped[str] = mapped_column(String(64))
    evidence_role: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str | None] = mapped_column(String(128))
    source_entity_type: Mapped[str | None] = mapped_column(String(64))
    source_entity_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CauseAssessment(Base):
    __tablename__ = "cause_assessments"
    id: Mapped[uuid.UUID] = uuid_pk()
    nonconformance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    cause_type: Mapped[str] = mapped_column(String(64))
    cause_entity_id: Mapped[str | None] = mapped_column(String(128))
    rationale: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"
    id: Mapped[uuid.UUID] = uuid_pk()
    nonconformance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContainmentProposal(Base):
    __tablename__ = "containment_proposals"
    id: Mapped[uuid.UUID] = uuid_pk()
    nonconformance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    blast_radius_query_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    proposed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    containment: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlastRadiusQuery(Base):
    __tablename__ = "blast_radius_queries"
    id: Mapped[uuid.UUID] = uuid_pk()
    factor_type: Mapped[str] = mapped_column(String(32), index=True)
    factor_value: Mapped[str] = mapped_column(String(256), index=True)
    affected_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    affected_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlastRadiusExposure(Base):
    __tablename__ = "blast_radius_exposures"
    id: Mapped[uuid.UUID] = uuid_pk()
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blast_radius_queries.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    relationship_path: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    exposure_event_id: Mapped[str | None] = mapped_column(String(128))
    operation_run_id: Mapped[str | None] = mapped_column(String(128))
    last_inspection_event_id: Mapped[str | None] = mapped_column(String(128))
    proposed_action: Mapped[str] = mapped_column(String(32), default="REVIEW_REQUIRED")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    approvals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlDeviceInvalidation(Base):
    __tablename__ = "control_device_invalidations"
    id: Mapped[uuid.UUID] = uuid_pk()
    source_event_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    affected_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    affected_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(Text)
    invalidation_type: Mapped[str | None] = mapped_column(String(64))
    supporting_evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ControllerDecision(Base):
    __tablename__ = "controller_decisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    nonconformance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    verdict: Mapped[str] = mapped_column(String(32))
    disposition: Mapped[str] = mapped_column(String(32))
    containment: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    analysis_version: Mapped[int] = mapped_column(Integer)
    previous_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectionState(Base):
    __tablename__ = "projection_state"
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    latest_raw_ingest_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_projected_ingest_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    projection_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="stale")
    last_successful_rebuild_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class RouteDefinition(Base):
    __tablename__ = "route_definitions"
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(96), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RouteRevision(Base):
    __tablename__ = "route_revisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("route_definitions.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    immutable_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("route_id", "revision", name="uq_route_revision"),)


class RouteStep(Base):
    __tablename__ = "route_steps"
    id: Mapped[uuid.UUID] = uuid_pk()
    route_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("route_revisions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    operation_id: Mapped[str] = mapped_column(String(128))
    operation_name: Mapped[str] = mapped_column(String(255))
    control_point_id: Mapped[str | None] = mapped_column(String(128))
    required_inspection: Mapped[bool] = mapped_column(Boolean, default=False)
    inspection_scope: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    trust_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint("route_revision_id", "position", name="uq_route_step_pos"),)


class TrustPolicy(Base):
    __tablename__ = "trust_policies"
    id: Mapped[uuid.UUID] = uuid_pk()
    policy_version: Mapped[int] = mapped_column(Integer)
    control_point_id: Mapped[str] = mapped_column(String(128), index=True)
    allowed_observation_quality: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["good"])
    confidence_required: Mapped[bool] = mapped_column(Boolean, default=False)
    min_confidence: Mapped[float | None] = mapped_column(Float)
    requires_valid_device: Mapped[bool] = mapped_column(Boolean, default=False)
    media_required: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_policy: Mapped[str] = mapped_column(String(32), default="mark_conflicted")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("control_point_id", "policy_version", name="uq_trust_policy_version"),
    )


class QualityResult(Base):
    __tablename__ = "quality_results"
    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[str] = mapped_column(String(128), unique=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationMessage(Base):
    __tablename__ = "integration_messages"
    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    external_system: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    safe_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[str] = mapped_column(String(128), unique=True)
    destination: Mapped[str] = mapped_column(String(64), index=True)
    message_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id: Mapped[uuid.UUID] = uuid_pk()
    internal_entity_type: Mapped[str] = mapped_column(String(64))
    internal_id: Mapped[str] = mapped_column(String(128), index=True)
    external_system: Mapped[str] = mapped_column(String(64))
    external_entity_type: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(255))
    external_revision: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint(
            "external_system", "external_entity_type", "external_id", name="uq_external_identity"
        ),
    )


class ProductStructureSnapshot(Base):
    __tablename__ = "product_structure_snapshots"
    id: Mapped[uuid.UUID] = uuid_pk()
    assembly_id: Mapped[str] = mapped_column(String(128), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    components: Mapped[list[Any]] = mapped_column(JSONB)
    relations: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("assembly_id", "revision", "content_hash", name="uq_structure_snapshot"),
    )


class IntegrationHealth(Base):
    __tablename__ = "integration_health"
    integration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_type: Mapped[str] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="healthy")


class CryptoProfile(Base):
    __tablename__ = "crypto_profiles"
    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="INACTIVE")
    algorithms: Mapped[dict[str, Any]] = mapped_column(JSONB)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrityCheckpoint(Base):
    __tablename__ = "integrity_checkpoints"
    id: Mapped[uuid.UUID] = uuid_pk()
    stream_type: Mapped[str] = mapped_column(String(32), index=True)
    stream_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    root_mac: Mapped[bytes] = mapped_column(LargeBinary)
    crypto_profile_id: Mapped[str] = mapped_column(String(64))
    classic_signature: Mapped[bytes] = mapped_column(LargeBinary)
    pq_signature: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
