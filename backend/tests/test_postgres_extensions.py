import os
import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.postgres, pytest.mark.skipif(os.getenv("RUN_POSTGRES_TESTS") != "1", reason="isolated PostgreSQL required")]


def test_extension_tables_and_route_trigger_exist():
    from backend.app.persistence.database import engine
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
        assert {"auth_sessions", "transport_nonces", "security_alerts", "control_device_invalidations",
                "approval_requests", "blast_radius_queries", "blast_radius_exposures", "containment_applications", "crypto_profiles",
                "integrity_checkpoints"} <= tables
        triggers = {row[0] for row in connection.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))}
        assert "trg_route_revision_immutable" in triggers


def test_runtime_role_cannot_mutate_raw_or_append_only_security_facts():
    from backend.app.persistence.database import engine
    with engine.connect() as connection:
        for table in ("raw_events", "transport_nonces", "control_device_invalidations", "integrity_checkpoints", "containment_applications"):
            assert connection.scalar(text("SELECT has_table_privilege(current_user, :table, 'UPDATE')"), {"table": table}) is False
