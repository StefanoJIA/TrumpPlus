"""phase 1.3 final videos

Revision ID: 0004_phase_1_3
Revises: 0003_phase_1_2
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_phase_1_3"
down_revision: Union[str, None] = "0003_phase_1_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "final_videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_id", sa.Integer(), sa.ForeignKey("brief_scripts.id"), nullable=False),
        sa.Column("render_package_id", sa.Integer(), sa.ForeignKey("render_packages.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("video_path", sa.String(length=1000), nullable=True),
        sa.Column("report_path", sa.String(length=1000), nullable=True),
        sa.Column("tts_provider", sa.String(length=80), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("final_videos")
