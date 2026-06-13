"""phase 1.9 evidence candidates

Revision ID: 0008_phase_1_9
Revises: 0007_phase_1_6
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_phase_1_9"
down_revision: Union[str, None] = "0007_phase_1_6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_name", sa.String(length=180), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("archive_url", sa.String(length=800), nullable=True),
        sa.Column("excerpt", sa.String(length=500), nullable=False),
        sa.Column("publisher_type", sa.String(length=40), nullable=False, server_default="other"),
        sa.Column("reliability_tier", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("search_query", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("reviewer_name", sa.String(length=120), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("evidence_candidates")
