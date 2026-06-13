"""phase 2.0 editorial calendar

Revision ID: 0009_phase_2_0
Revises: 0008_phase_1_9
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_phase_2_0"
down_revision = "0008_phase_1_9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brief_scripts", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "editorial_topics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.String(length=1200), nullable=False),
        sa.Column("topic_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("evidence_score", sa.Float(), nullable=False),
        sa.Column("platform_fit_score", sa.Float(), nullable=False),
        sa.Column("selected_post_ids", sa.JSON(), nullable=False),
        sa.Column("selected_claim_ids", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("editor_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "editorial_calendar_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("slot_name", sa.String(length=120), nullable=False),
        sa.Column("target_platforms", sa.JSON(), nullable=False),
        sa.Column("planned_duration", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("assigned_editor", sa.String(length=120), nullable=True),
        sa.Column("publish_window_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["topic_id"], ["editorial_topics.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("editorial_calendar_entries")
    op.drop_table("editorial_topics")
    op.drop_column("brief_scripts", "metadata_json")
