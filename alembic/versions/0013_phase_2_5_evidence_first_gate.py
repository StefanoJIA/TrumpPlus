"""phase 2.5 evidence first quality gate

Revision ID: 0013_phase_2_5
Revises: 0012_phase_2_4
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_phase_2_5"
down_revision = "0012_phase_2_4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_items", sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True))
    op.add_column("evidence_items", sa.Column("source_review_item_id", sa.Integer(), sa.ForeignKey("source_review_items.id"), nullable=True))
    op.add_column("evidence_items", sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=True))
    op.add_column("evidence_items", sa.Column("evidence_type", sa.String(length=40), nullable=False, server_default="manual_note"))
    op.add_column("evidence_items", sa.Column("title", sa.String(length=300), nullable=True))
    op.add_column("evidence_items", sa.Column("source_name", sa.String(length=180), nullable=True))
    op.add_column("evidence_items", sa.Column("source_url", sa.String(length=800), nullable=True))
    op.add_column("evidence_items", sa.Column("archive_url", sa.String(length=800), nullable=True))
    op.add_column("evidence_items", sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evidence_items", sa.Column("reliability_score", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("evidence_items", sa.Column("terms_status", sa.String(length=40), nullable=False, server_default="manual_review_required"))
    op.add_column("evidence_items", sa.Column("human_status", sa.String(length=40), nullable=False, server_default="pending"))
    op.add_column("evidence_items", sa.Column("created_by", sa.String(length=120), nullable=True))
    op.add_column("evidence_items", sa.Column("reviewed_by", sa.String(length=120), nullable=True))
    op.add_column("evidence_items", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.alter_column("evidence_items", "claim_id", nullable=True)
    op.alter_column("evidence_items", "evidence_source_id", nullable=True)
    op.execute(
        """
        UPDATE evidence_items
        SET workspace_id = (
                SELECT posts.workspace_id
                FROM claims JOIN posts ON claims.post_id = posts.id
                WHERE claims.id = evidence_items.claim_id
            ),
            source_name = (SELECT source_name FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id),
            source_url = (SELECT source_url FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id),
            archive_url = (SELECT archive_url FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id),
            retrieved_at = (SELECT retrieved_at FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id),
            terms_status = COALESCE((SELECT terms_status FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id), 'manual_review_required'),
            human_status = 'approved',
            reliability_score = COALESCE(
                (SELECT CASE reliability_tier WHEN 'high' THEN 80 WHEN 'medium' THEN 60 ELSE 50 END FROM evidence_sources WHERE evidence_sources.id = evidence_items.evidence_source_id),
                50
            )
        """
    )
    op.create_table(
        "claim_evidence_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("evidence_item_id", sa.Integer(), sa.ForeignKey("evidence_items.id"), nullable=False),
        sa.Column("support_type", sa.String(length=40), nullable=False, server_default="contextualizes"),
        sa.Column("confidence", sa.String(length=40), nullable=False, server_default="medium"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("claim_evidence_links")
    op.alter_column("evidence_items", "evidence_source_id", nullable=False)
    op.alter_column("evidence_items", "claim_id", nullable=False)
    for column in [
        "updated_at",
        "reviewed_by",
        "created_by",
        "human_status",
        "terms_status",
        "reliability_score",
        "retrieved_at",
        "archive_url",
        "source_url",
        "source_name",
        "title",
        "evidence_type",
        "post_id",
        "source_review_item_id",
        "workspace_id",
    ]:
        op.drop_column("evidence_items", column)
