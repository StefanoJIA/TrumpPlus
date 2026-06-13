"""phase 1.6 evidence pack

Revision ID: 0007_phase_1_6
Revises: 0006_phase_1_5
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_phase_1_6"
down_revision: Union[str, None] = "0006_phase_1_5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(length=180), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("archive_url", sa.String(length=800), nullable=True),
        sa.Column("publisher_type", sa.String(length=40), nullable=False, server_default="other"),
        sa.Column("reliability_tier", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terms_status", sa.String(length=40), nullable=False, server_default="manual_review_required"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("evidence_source_id", sa.Integer(), sa.ForeignKey("evidence_sources.id"), nullable=False),
        sa.Column("excerpt", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("supports_claim", sa.String(length=40), nullable=False, server_default="unclear"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "evidence_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("verdict", sa.String(length=40), nullable=False, server_default="unclear"),
        sa.Column("rationale", sa.String(length=1200), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("required_human_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reviewer_name", sa.String(length=120), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("evidence_packs")
    op.drop_table("evidence_items")
    op.drop_table("evidence_sources")
