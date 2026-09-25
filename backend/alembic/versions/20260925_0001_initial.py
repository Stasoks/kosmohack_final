"""Initial TRACE-Q schema and append-only database controls.

Revision ID: 20260925_0001
Revises:
"""
from __future__ import annotations

from alembic import op

from backend.app.persistence.models import Base


revision = "20260925_0001"
down_revision = None
branch_labels = None
depends_on = None


APPEND_ONLY_TABLES = (
    "ingest_attempts",
    "raw_events",
    "controller_decisions",
    "audit_entries",
    "integration_messages",
    "quality_results",
    "analysis_versions",
    "analysis_evidence",
    "cause_assessments",
    "investigation_notes",
    "product_structure_snapshots",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION traceq_prevent_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'append-only table % cannot be updated or deleted', TG_TABLE_NAME
            USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION traceq_prevent_mutation();
            """
        )

    op.execute("GRANT USAGE ON SCHEMA public TO traceq_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO traceq_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO traceq_app")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM traceq_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO traceq_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO traceq_app"
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP FUNCTION IF EXISTS traceq_prevent_mutation()")
