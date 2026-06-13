# truth-monitor extension
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


DB_PATH = Path(os.getenv("TRUTH_STORAGE_DB", "data/truth_posts.sqlite3"))


def _connect() -> sqlite3.Connection:
    """Open the Truth monitor SQLite database and ensure the table exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the truth_posts table if it does not already exist."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS truth_posts (
          id TEXT PRIMARY KEY,
          url TEXT,
          text TEXT,
          created_at TEXT,
          media_urls TEXT,
          local_media TEXT,
          fetched_at TEXT,
          injected INTEGER DEFAULT 0
        )
        """
    )
    connection.commit()


def save_truth_post(post: dict[str, Any], local_media: list[str]) -> None:
    """Persist a normalized Truth Social post and local media paths."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO truth_posts
            (id, url, text, created_at, media_urls, local_media, fetched_at, injected)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT injected FROM truth_posts WHERE id = ?), 0))
            """,
            (
                str(post["id"]),
                post.get("url", ""),
                post.get("text", ""),
                post.get("created_at", ""),
                json.dumps(post.get("media_urls", []), ensure_ascii=False),
                json.dumps(local_media, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
                str(post["id"]),
            ),
        )
        connection.commit()


def get_uninjected_posts(limit: int = 20) -> list[dict[str, Any]]:
    """Load posts that have not yet been injected into the source intake queue."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM truth_posts WHERE injected = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_post(row) for row in rows]


def mark_injected(post_id: str) -> None:
    """Mark a stored Truth Social post as injected into source intake."""
    with _connect() as connection:
        connection.execute("UPDATE truth_posts SET injected = 1 WHERE id = ?", (post_id,))
        connection.commit()


def _row_to_post(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite row into a post dictionary."""
    return {
        "id": row["id"],
        "url": row["url"],
        "text": row["text"],
        "created_at": row["created_at"],
        "media_urls": json.loads(row["media_urls"] or "[]"),
        "local_media": json.loads(row["local_media"] or "[]"),
        "fetched_at": row["fetched_at"],
        "injected": row["injected"],
    }

