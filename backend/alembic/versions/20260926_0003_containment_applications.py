"""Containment application facts and append-only protection.

Revision ID: 20260926_0003
Revises: 20260925_0002
"""
from alembic import op

from backend.app.persistence.models import Base


revision = "20260926_0003"
down_revision = "20260925_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    op.execute("REVOKE UPDATE, DELETE ON containment_applications FROM traceq_app")
    op.execute("DROP TRIGGER IF EXISTS trg_containment_applications_append_only ON containment_applications")
    op.execute(
        "CREATE TRIGGER trg_containment_applications_append_only "
        "BEFORE UPDATE OR DELETE ON containment_applications "
        "FOR EACH ROW EXECUTE FUNCTION traceq_prevent_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS containment_applications CASCADE")
