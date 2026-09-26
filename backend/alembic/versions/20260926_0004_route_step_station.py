"""Route step station mapping.

Revision ID: 20260926_0004
Revises: 20260926_0003
"""
from alembic import op


revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE route_steps ADD COLUMN IF NOT EXISTS station_id varchar(128)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_route_steps_station_id ON route_steps (station_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_route_steps_station_id")
    op.execute("ALTER TABLE route_steps DROP COLUMN IF EXISTS station_id")
