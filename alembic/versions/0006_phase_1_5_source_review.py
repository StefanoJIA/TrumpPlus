"""phase 1.5 source review queue

Revision ID: 0006_phase_1_5
Revises: 0005_phase_1_4
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_phase_1_5"
down_revision: Union[str, None] = "0005_phase_1_4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adapter_name", sa.String(length=120), nullable=False),
        sa.Column("source_name", sa.String(length=180), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("archive_url", sa.String(length=800), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_excerpt", sa.String(length=500), nullable=False),
        sa.Column("normalized_summary", sa.String(length=1000), nullable=False),
        sa.Column("media_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("terms_status", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("human_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("reviewer_name", sa.String(length=120), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("source_review_items")
