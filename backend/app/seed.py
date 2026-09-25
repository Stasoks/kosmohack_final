from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select

from backend.app.persistence.database import SessionLocal
from backend.app.persistence.models import (
    ComponentDefinition,
    CryptoProfile,
    Equipment,
    EventSource,
    IntegrationHealth,
    Line,
    OperationDefinition,
    Operator,
    Permission,
    ProductDefinition,
    ProductStructureSnapshot,
    Role,
    RolePermission,
    RouteDefinition,
    RouteRevision,
    RouteStep,
    Station,
    TrustPolicy,
    User,
)
from backend.app.security.crypto import canonical_json_bytes, sha256_hex, token_hash, utcnow
from backend.app.security.passwords import hash_password
from backend.app.security.permissions import PERMISSIONS, ROLE_PERMISSIONS
from backend.app.settings import get_settings


def _get_or_create(db, model, defaults: dict[str, Any] | None = None, **lookup):
    row = db.scalar(select(model).filter_by(**lookup))
    if row:
        return row, False
    row = model(**lookup, **(defaults or {}))
    db.add(row)
    db.flush()
    return row, True


def seed() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        permissions: dict[str, Permission] = {}
        for name in PERMISSIONS:
            permissions[name], _ = _get_or_create(db, Permission, name=name)
        roles: dict[str, Role] = {}
        for role_name in ROLE_PERMISSIONS:
            roles[role_name], _ = _get_or_create(
                db,
                Role,
                defaults={"description": f"TRACE-Q base role: {role_name}"},
                name=role_name,
            )
            for permission_name in ROLE_PERMISSIONS[role_name]:
                _get_or_create(
                    db,
                    RolePermission,
                    role_id=roles[role_name].id,
                    permission_id=permissions[permission_name].id,
                )

        if settings.demo_mode:
            password_fields = {
                "controller": settings.demo_controller_password,
                "master": settings.demo_master_password,
                "technologist": settings.demo_technologist_password,
                "manager": settings.demo_manager_password,
                "admin": settings.demo_admin_password,
            }
            missing = [name for name, value in password_fields.items() if not value]
            if missing:
                raise RuntimeError(f"Missing demo passwords: {', '.join(missing)}")
            display_names = {
                "controller": "Контролёр качества",
                "master": "Мастер участка",
                "technologist": "Технолог",
                "manager": "Руководитель производства",
                "admin": "Администратор",
            }
            for username, password in password_fields.items():
                user = db.scalar(select(User).where(User.username == username))
                if user is None:
                    user = User(
                        username=username,
                        display_name=display_names[username],
                        password_hash=hash_password(password.get_secret_value()),  # type: ignore[union-attr]
                        enabled=True,
                        roles=[roles[username]],
                    )
                    db.add(user)
                elif roles[username] not in user.roles:
                    user.roles = [roles[username]]

        for line_id, name in (("LINE-A", "Участок механической обработки"), ("LINE-B", "Участок сборки")):
            _get_or_create(db, Line, defaults={"name": name}, id=line_id)
        for station_id, line_id, name in (
            ("ST-10", "LINE-A", "Входной контроль"),
            ("ST-20", "LINE-A", "Механическая обработка"),
            ("ST-30", "LINE-B", "Сборка и выходной контроль"),
        ):
            _get_or_create(db, Station, defaults={"line_id": line_id, "name": name}, id=station_id)
        for operator_id in ("OPER-01", "OPER-02"):
            _get_or_create(
                db, Operator, defaults={"display_code": operator_id, "active": True}, id=operator_id
            )
        for equipment_id, station_id, name in (
            ("EQ-LATHE-01", "ST-20", "Токарный центр"),
            ("EQ-ASSEMBLY-01", "ST-30", "Сборочный стенд"),
        ):
            _get_or_create(
                db,
                Equipment,
                defaults={"station_id": station_id, "name": name},
                id=equipment_id,
            )
        for operation_id, name, seconds in (
            ("OP-INCOMING", "Входной контроль", 120.0),
            ("OP-TURN", "Механическая обработка", 1200.0),
            ("OP-ASSEMBLY", "Сборка", 900.0),
        ):
            _get_or_create(
                db,
                OperationDefinition,
                defaults={"name": name, "expected_duration_seconds": seconds},
                id=operation_id,
            )
        _get_or_create(
            db,
            ProductDefinition,
            defaults={"name": "Условный корпус TRACE-Q", "revision": "A"},
            id="PD-TRACE-01",
        )
        _get_or_create(
            db,
            ComponentDefinition,
            defaults={"name": "Корпус", "revision": "A"},
            id="COMP-BODY",
        )

        route = db.scalar(select(RouteDefinition).where(RouteDefinition.code == "ROUTE-DEFAULT"))
        if route is None:
            route = RouteDefinition(code="ROUTE-DEFAULT", name="Основной маршрут корпуса")
            db.add(route)
            db.flush()
            revision = RouteRevision(
                route_id=route.id,
                revision=1,
                status="active",
                immutable_after=utcnow(),
            )
            db.add(revision)
            db.flush()
            steps = (
                (1, "OP-INCOMING", "Входной контроль", "ST-10", "CP-IN", True),
                (2, "OP-TURN", "Механическая обработка", "ST-20", "CP-AFTER-TURN", True),
                (3, "OP-ASSEMBLY", "Сборка", "ST-30", "CP-FINAL", True),
            )
            for position, operation_id, name, station_id, control_point, required in steps:
                db.add(
                    RouteStep(
                        route_revision_id=revision.id,
                        position=position,
                        operation_id=operation_id,
                        operation_name=name,
                        station_id=station_id,
                        control_point_id=control_point,
                        required_inspection=required,
                        inspection_scope={"defect_types": ["*"], "component_instance_ids": ["*"]},
                    )
                )
            route.active_revision_id = revision.id

        for control_point in ("CP-IN", "CP-AFTER-TURN", "CP-FINAL"):
            if not db.scalar(
                select(TrustPolicy).where(
                    TrustPolicy.control_point_id == control_point,
                    TrustPolicy.policy_version == 1,
                )
            ):
                db.add(
                    TrustPolicy(
                        policy_version=1,
                        control_point_id=control_point,
                        allowed_observation_quality=["good"],
                        confidence_required=False,
                        requires_valid_device=False,
                        media_required=False,
                        conflict_policy="mark_conflicted",
                        active=True,
                    )
                )

        structure = {
            "assembly_id": "PD-TRACE-01",
            "revision": "A",
            "components": [{"component_definition_id": "COMP-BODY", "quantity": 1}],
            "relations": [],
        }
        structure_hash = sha256_hex(canonical_json_bytes(structure))
        if not db.scalar(
            select(ProductStructureSnapshot).where(
                ProductStructureSnapshot.assembly_id == "PD-TRACE-01",
                ProductStructureSnapshot.revision == "A",
                ProductStructureSnapshot.content_hash == structure_hash,
            )
        ):
            db.add(
                ProductStructureSnapshot(
                    assembly_id="PD-TRACE-01",
                    revision="A",
                    content_hash=structure_hash,
                    components=structure["components"],
                    relations=structure["relations"],
                )
            )

        if settings.source_demo_token:
            token = settings.source_demo_token.get_secret_value()
            sources = {
                "MES-01": ("mes", ["item.registered", "operation.started", "operation.finished"]),
                "VISION-02": ("vision_qc", ["inspection.result"]),
                "MACHINE-01": ("machine_logs", ["machine.state"]),
                "OPERATOR-01": ("operator_vision", ["operator.action"]),
                "CALIBRATION-01": ("calibration_system", ["control_device.invalidated"]),
            }
            for number in range(1, 11):
                sources[f"LOAD-MES-{number:02d}"] = ("mes", ["item.registered"])
            for source_id, (source_type, allowed) in sources.items():
                auth_method = "HMAC_V1" if source_id == "CALIBRATION-01" else "shared_secret_legacy"
                hmac_key_id = source_id if auth_method == "HMAC_V1" else None
                legacy_token_hash = None if auth_method == "HMAC_V1" else token_hash(token)
                source = db.get(EventSource, source_id)
                if source is None:
                    db.add(
                        EventSource(
                            source_id=source_id,
                            source_type=source_type,
                            enabled=True,
                            status="ACTIVE",
                            auth_method=auth_method,
                            token_hash=legacy_token_hash,
                            key_id=hmac_key_id,
                            secret_env_name="SOURCE_HMAC_SECRETS_JSON" if hmac_key_id else None,
                            allowed_event_types=allowed,
                        )
                    )
                else:
                    source.enabled = True
                    source.status = "ACTIVE"
                    source.auth_method = auth_method
                    source.allowed_event_types = allowed
                    source.token_hash = legacy_token_hash
                    source.key_id = hmac_key_id
                    source.secret_env_name = "SOURCE_HMAC_SECRETS_JSON" if hmac_key_id else None
        _get_or_create(
            db,
            IntegrationHealth,
            defaults={"status": "UNKNOWN"},
            integration_id="erp-emulator",
        )
        classic = db.get(CryptoProfile, "CLASSIC_V1")
        if classic is None:
            db.add(CryptoProfile(profile_id="CLASSIC_V1", status="ACTIVE",
                                 algorithms={"encryption": "AES-256-GCM", "integrity": "HMAC-SHA256", "checkpoint": "ECDSA-P256"},
                                 activated_at=utcnow()))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
