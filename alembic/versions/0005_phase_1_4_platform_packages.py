"""phase 1.4 platform packages

Revision ID: 0005_phase_1_4
Revises: 0004_phase_1_3
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_phase_1_4"
down_revision: Union[str, None] = "0004_phase_1_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_id", sa.Integer(), sa.ForeignKey("brief_scripts.id"), nullable=False),
        sa.Column("final_video_id", sa.Integer(), sa.ForeignKey("final_videos.id"), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False, server_default="all"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("output_dir", sa.String(length=1000), nullable=True),
        sa.Column("package_path", sa.String(length=1000), nullable=True),
        sa.Column("qa_report_path", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("platform_packages")
