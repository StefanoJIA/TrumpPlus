"""phase 1.2 render packages

Revision ID: 0003_phase_1_2
Revises: 0002_phase_1_1
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_phase_1_2"
down_revision: Union[str, None] = "0002_phase_1_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "render_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_id", sa.Integer(), sa.ForeignKey("brief_scripts.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("output_dir", sa.String(length=1000), nullable=True),
        sa.Column("manifest_path", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("render_packages")
