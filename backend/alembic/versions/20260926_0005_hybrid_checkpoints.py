"""Add algorithm and external-key metadata for hybrid checkpoints.

Revision ID: 20260926_0005
Revises: 20260926_0004
"""
from __future__ import annotations

from alembic import op


revision = "20260926_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = (
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS format_version varchar(16)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS classic_key_id varchar(128)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS classic_key_version varchar(32)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS classic_algorithm varchar(64)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS pq_key_id varchar(128)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS pq_key_version varchar(32)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS pq_algorithm varchar(64)",
        "ALTER TABLE integrity_checkpoints ADD COLUMN IF NOT EXISTS payload_hash varchar(64)",
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for column in (
        "payload_hash",
        "pq_algorithm",
        "pq_key_version",
        "pq_key_id",
        "classic_algorithm",
        "classic_key_version",
        "classic_key_id",
        "format_version",
    ):
        op.execute(f"ALTER TABLE integrity_checkpoints DROP COLUMN IF EXISTS {column}")
