"""phase 2.4 workspace auth readiness

Revision ID: 0012_phase_2_4
Revises: 0011_phase_2_3
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_phase_2_4"
down_revision = "0011_phase_2_3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("email_or_name", sa.String(length=180), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="viewer"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "INSERT INTO workspaces (name, slug, status) VALUES "
        "('Daily Truth Brief Dev', 'daily-truth-brief-dev', 'active')"
    )
    for table_name in [
        "source_review_items",
        "posts",
        "brief_scripts",
        "editorial_topics",
        "editorial_calendar_entries",
        "render_packages",
        "final_videos",
        "platform_packages",
        "audit_logs",
        "approval_records",
    ]:
        op.add_column(table_name, sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id")))
        op.execute(f"UPDATE {table_name} SET workspace_id = 1 WHERE workspace_id IS NULL")


def downgrade() -> None:
    for table_name in [
        "approval_records",
        "audit_logs",
        "platform_packages",
        "final_videos",
        "render_packages",
        "editorial_calendar_entries",
        "editorial_topics",
        "brief_scripts",
        "posts",
        "source_review_items",
    ]:
        op.drop_column(table_name, "workspace_id")
    op.drop_table("api_tokens")
    op.drop_table("invites")
    op.drop_table("team_members")
    op.drop_table("workspaces")
