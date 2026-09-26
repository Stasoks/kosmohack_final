from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.security.permissions import (
    PERMISSION_CATALOG,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    SYSTEM_LOCKED_ROLES,
)
from backend.app.security.auth import create_access_token
from backend.app.settings import get_settings


def test_permission_catalog_has_human_readable_metadata() -> None:
    assert set(PERMISSION_CATALOG) == set(PERMISSIONS)
    assert all(row["label"] and row["description"] for row in PERMISSION_CATALOG.values())
    assert "Управление" in PERMISSION_CATALOG["MANAGE_USERS"]["label"]


def test_default_separation_of_duties_is_unchanged() -> None:
    assert "ISSUE_QC_DECISION" in ROLE_PERMISSIONS["controller"]
    assert "ISSUE_QC_DECISION" not in ROLE_PERMISSIONS["admin"]
    assert "ISSUE_QC_DECISION" not in ROLE_PERMISSIONS["technologist"]
    assert "APPROVE_CONTAINMENT" in ROLE_PERMISSIONS["controller"]
    assert "PROPOSE_CONTAINMENT" in ROLE_PERMISSIONS["technologist"]
    assert SYSTEM_LOCKED_ROLES == {"simulator_reader"}


def test_access_token_does_not_cache_runtime_permissions() -> None:
    user = SimpleNamespace(id=uuid.uuid4(), username="rbac-test-user")
    token, _ = create_access_token(user, uuid.uuid4(), get_settings())
    claims = jwt.decode(token, options={"verify_signature": False})

    assert "permissions" not in claims
    assert "roles" not in claims


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="set RUN_POSTGRES_TESTS=1 against an isolated PostgreSQL demo database",
)
def test_runtime_role_permission_management_and_seed_preservation() -> None:
    from backend.app.main import app
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import Permission, Role, RolePermission
    from backend.app.seed import seed

    client = TestClient(app)

    def login(username: str, password: str) -> dict:
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def headers(tokens: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    admin_tokens = login("admin", "admin-demo")
    technologist_tokens = login("technologist", "technologist-demo")
    admin_headers = headers(admin_tokens)
    technologist_headers = headers(technologist_tokens)

    roles_response = client.get("/api/v1/admin/roles", headers=admin_headers)
    assert roles_response.status_code == 200, roles_response.text
    roles = {row["name"]: row for row in roles_response.json()}
    technologist = roles["technologist"]
    admin = roles["admin"]
    simulator = roles["simulator_reader"]
    original = set(technologist["permissions"])
    assert original == ROLE_PERMISSIONS["technologist"]
    assert simulator["system_locked"] is True
    assert technologist["permission_catalog"][0]["label"]

    invalid = client.patch(
        f"/api/v1/admin/roles/{technologist['id']}/permissions",
        headers=admin_headers,
        json={"permissions": sorted(original | {"NOT_A_PERMISSION"}), "reason": "test unknown"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "UNKNOWN_PERMISSION"

    locked = client.patch(
        f"/api/v1/admin/roles/{simulator['id']}/permissions",
        headers=admin_headers,
        json={"permissions": simulator["permissions"], "reason": "test locked role"},
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "SYSTEM_ROLE_LOCKED"

    last_admin = client.patch(
        f"/api/v1/admin/roles/{admin['id']}/permissions",
        headers=admin_headers,
        json={
            "permissions": sorted(set(admin["permissions"]) - {"MANAGE_USERS"}),
            "reason": "test last administrator protection",
        },
    )
    assert last_admin.status_code == 409
    assert last_admin.json()["error"]["code"] == "LAST_ADMIN_CAPABILITY"

    route_rows = client.get("/api/v1/routes", headers=technologist_headers)
    assert route_rows.status_code == 200, route_rows.text
    route_id = route_rows.json()[0]["id"]
    assert client.get(
        f"/api/v1/routes/{route_id}/export", headers=technologist_headers
    ).status_code == 200

    without_manage_routes = sorted(original - {"MANAGE_ROUTES"})
    try:
        changed = client.patch(
            f"/api/v1/admin/roles/{technologist['id']}/permissions",
            headers=admin_headers,
            json={
                "permissions": without_manage_routes,
                "reason": "test immediate runtime enforcement",
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["customized"] is True

        # The access token has not changed. Authorization is evaluated from the
        # database for every request, so the old session loses access immediately.
        denied = client.get(
            f"/api/v1/routes/{route_id}/export", headers=technologist_headers
        )
        assert denied.status_code == 403

        users = client.get("/api/v1/admin/users", headers=admin_headers)
        assert users.status_code == 200, users.text
        technologist_user = next(
            row for row in users.json() if row["username"] == "technologist"
        )
        assert "MANAGE_ROUTES" not in technologist_user["effective_permissions"]

        # Re-running bootstrap must preserve the administrator's customization.
        seed()
        db = SessionLocal()
        try:
            still_removed = db.scalar(
                select(RolePermission.role_id)
                .join(Role, Role.id == RolePermission.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(
                    Role.name == "technologist",
                    Permission.name == "MANAGE_ROUTES",
                )
            )
            assert still_removed is None
        finally:
            db.close()

        restored = client.patch(
            f"/api/v1/admin/roles/{technologist['id']}/permissions",
            headers=admin_headers,
            json={"permissions": sorted(original), "reason": "restore test baseline"},
        )
        assert restored.status_code == 200, restored.text
        assert client.get(
            f"/api/v1/routes/{route_id}/export", headers=technologist_headers
        ).status_code == 200

        audit = client.get("/api/v1/admin/audit", headers=admin_headers)
        assert audit.status_code == 200, audit.text
        entries = [
            row for row in audit.json() if row["action"] == "role_permissions_update"
        ]
        assert entries
        removal = next(
            row for row in entries if row["safe_details"]["reason"] == "test immediate runtime enforcement"
        )
        assert removal["safe_details"]["before"] == sorted(original)
        assert removal["safe_details"]["after"] == without_manage_routes
        assert removal["safe_details"]["added"] == []
        assert removal["safe_details"]["removed"] == ["MANAGE_ROUTES"]
    finally:
        # Keep the shared integration database stable even if an assertion above fails.
        current = client.get("/api/v1/admin/roles", headers=admin_headers)
        if current.status_code == 200:
            row = next(
                item for item in current.json() if item["name"] == "technologist"
            )
            if set(row["permissions"]) != original:
                client.patch(
                    f"/api/v1/admin/roles/{technologist['id']}/permissions",
                    headers=admin_headers,
                    json={"permissions": sorted(original), "reason": "restore test baseline"},
                )
