# truth-monitor extension
from __future__ import annotations

import os
from typing import Any

import redis.asyncio as redis


SEEN_KEY = "truth_seen_ids"


def _client() -> redis.Redis:
    """Create an async Redis client for Truth Social post de-duplication."""
    return redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


async def filter_new(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only posts whose IDs have not been marked as seen in Redis."""
    if not posts:
        return []
    client = _client()
    try:
        pipe = client.pipeline()
        for post in posts:
            pipe.sismember(SEEN_KEY, str(post["id"]))
        seen_flags = await pipe.execute()
        return [post for post, seen in zip(posts, seen_flags, strict=False) if not seen]
    finally:
        await client.aclose()


async def mark_seen(posts: list[dict[str, Any]]) -> None:
    """Mark post IDs as seen in Redis."""
    if not posts:
        return
    ids = [str(post["id"]) for post in posts if post.get("id")]
    if not ids:
        return
    client = _client()
    try:
        await client.sadd(SEEN_KEY, *ids)
    finally:
        await client.aclose()

