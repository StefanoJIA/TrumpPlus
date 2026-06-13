"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("terms_safe", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("post_id", sa.String(length=180), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("short_excerpt", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("fact_check_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("ranking_score", sa.Float(), nullable=True),
        sa.Column("ranking_breakdown", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_url"),
        sa.UniqueConstraint("post_id"),
        sa.UniqueConstraint("text_hash"),
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("claim_text", sa.String(length=1000), nullable=False),
        sa.Column("claim_type", sa.String(length=40), nullable=False),
        sa.Column("requires_fact_check", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "fact_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("verdict", sa.String(length=40), nullable=False),
        sa.Column("rationale", sa.String(length=1200), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "brief_scripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("script_text", sa.Text(), nullable=False),
        sa.Column("subtitle_draft", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ranked_posts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("claims", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fact_checks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("visual_plan", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "safety_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_script_id", sa.Integer(), sa.ForeignKey("brief_scripts.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("human_review_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "video_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_script_id", sa.Integer(), sa.ForeignKey("brief_scripts.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("asset_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("export_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("video_assets")
    op.drop_table("safety_reviews")
    op.drop_table("brief_scripts")
    op.drop_table("fact_checks")
    op.drop_table("claims")
    op.drop_table("posts")
    op.drop_table("sources")

