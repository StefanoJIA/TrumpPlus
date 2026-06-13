"""phase 1.1 review state

Revision ID: 0002_phase_1_1
Revises: 0001_initial
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_phase_1_1"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("source_review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("posts", sa.Column("source_policy", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("brief_scripts", sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"))
    op.add_column("safety_reviews", sa.Column("reviewer_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("safety_reviews", "reviewer_name")
    op.drop_column("brief_scripts", "status")
    op.drop_column("posts", "source_policy")
    op.drop_column("posts", "source_review_required")
