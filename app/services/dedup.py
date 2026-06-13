from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Post


class DedupService:
    def __init__(self, db: Session):
        self.db = db

    def find_duplicate(self, normalized_post: dict[str, Any]) -> str | None:
        duplicate = self.db.scalar(
            select(Post).where(
                or_(
                    Post.source_url == normalized_post["source_url"],
                    Post.post_id == normalized_post["post_id"],
                    Post.text_hash == normalized_post["text_hash"],
                )
            )
        )
        if duplicate is None:
            return None
        if duplicate.source_url == normalized_post["source_url"]:
            return "source_url"
        if duplicate.post_id == normalized_post["post_id"]:
            return "post_id"
        return "text_hash"

