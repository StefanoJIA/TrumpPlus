# truth-monitor extension
from __future__ import annotations

import os
from typing import Any

import httpx


async def notify_new_post(post: dict[str, Any]) -> None:
    """Send a Telegram notification for a new post, or silently skip when not configured."""
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    text = (
        f"\u65b0\u5e16 {post.get('created_at', '')}\n"
        f"{str(post.get('text', ''))[:300]}\n"
        f"{post.get('url', '')}\n"
        f"\u5a92\u4f53: {len(post.get('media_urls', []))} \u4e2a\u6587\u4ef6"
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
