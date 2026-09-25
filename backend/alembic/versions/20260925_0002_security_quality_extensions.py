"""Sessions, source replay, invalidation, approvals, blast radius and crypto profiles.

Revision ID: 20260925_0002
Revises: 20260925_0001
"""
from alembic import op
from backend.app.persistence.models import Base

revision = "20260925_0002"
down_revision = "20260925_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The published initial revision used metadata.create_all. create_all keeps fresh installs
    # compatible; these statements upgrade databases already running 0001.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    statements = (
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS status varchar(32) NOT NULL DEFAULT 'ACTIVE'",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS auth_method varchar(32) NOT NULL DEFAULT 'shared_secret_legacy'",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS secret_env_name varchar(128)",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS key_id varchar(128)",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS allowed_line_ids jsonb NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS allowed_station_ids jsonb NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS valid_from timestamptz",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS valid_to timestamptz",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS revoked_at timestamptz",
        "ALTER TABLE event_sources ADD COLUMN IF NOT EXISTS last_source_sequence bigint",
        "ALTER TABLE nonconformities ADD COLUMN IF NOT EXISTS resolution_type varchar(32)",
        "ALTER TABLE nonconformities ADD COLUMN IF NOT EXISTS resolved_at timestamptz",
        "ALTER TABLE nonconformities ADD COLUMN IF NOT EXISTS verification_decision_id uuid",
        "ALTER TABLE nonconformities ADD COLUMN IF NOT EXISTS verification_status varchar(32)",
        "ALTER TABLE containment_proposals ADD COLUMN IF NOT EXISTS blast_radius_query_id uuid",
        "ALTER TABLE containment_proposals ALTER COLUMN nonconformance_id DROP NOT NULL",
        "ALTER TABLE audit_entries ADD COLUMN IF NOT EXISTS integrity_sequence bigint",
        "ALTER TABLE audit_entries ADD COLUMN IF NOT EXISTS prev_integrity_mac bytea",
        "ALTER TABLE audit_entries ADD COLUMN IF NOT EXISTS integrity_mac bytea",
    )
    for statement in statements:
        op.execute(statement)
    for table in ("transport_nonces", "security_alerts", "control_device_invalidations", "blast_radius_queries", "blast_radius_exposures", "integrity_checkpoints"):
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM traceq_app")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute(f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION traceq_prevent_mutation()")
    op.execute("""
      CREATE OR REPLACE FUNCTION traceq_route_revision_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.immutable_after IS NOT NULL AND NOT (
          OLD.status = 'active' AND NEW.status = 'superseded'
          AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status')
        ) THEN
          RAISE EXCEPTION 'active route revision is immutable' USING ERRCODE='55000';
        END IF;
        RETURN NEW;
      END $$;
      DROP TRIGGER IF EXISTS trg_route_revision_immutable ON route_revisions;
      CREATE TRIGGER trg_route_revision_immutable BEFORE UPDATE OR DELETE ON route_revisions
      FOR EACH ROW EXECUTE FUNCTION traceq_route_revision_immutable();
    """)


def downgrade() -> None:
    for table in ("integrity_checkpoints", "crypto_profiles", "approval_requests", "blast_radius_exposures", "blast_radius_queries", "control_device_invalidations", "security_alerts", "transport_nonces", "auth_sessions"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
