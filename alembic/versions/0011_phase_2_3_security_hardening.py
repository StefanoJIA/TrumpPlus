"""phase 2.3 security hardening

Revision ID: 0011_phase_2_3
Revises: 0010_phase_2_2
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_phase_2_3"
down_revision = "0010_phase_2_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=120), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_name", sa.String(length=120), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_role", sa.String(length=40), nullable=True))
    op.add_column("audit_logs", sa.Column("before_state_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("after_state_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("approval_records", sa.Column("request_id", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("approval_records", "request_id")
    op.drop_column("audit_logs", "immutable")
    op.drop_column("audit_logs", "after_state_hash")
    op.drop_column("audit_logs", "before_state_hash")
    op.drop_column("audit_logs", "actor_role")
    op.drop_column("audit_logs", "actor_name")
    op.drop_column("audit_logs", "request_id")
