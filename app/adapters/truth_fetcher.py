# truth-monitor extension
from __future__ import annotations

import asyncio
import os
from typing import Any

from bs4 import BeautifulSoup
import httpx


TRUTH_STATUSES_URL = "https://truthsocial.com/api/v1/accounts/107780257626128497/statuses"


async def fetch_latest_posts() -> list[dict[str, Any]]:
    """Fetch and normalize recent public posts from the configured Truth Social account endpoint."""
    account_id = os.getenv("TRUTH_ACCOUNT_ID", "107780257626128497")
    url = f"https://truthsocial.com/api/v1/accounts/{account_id}/statuses"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    params = {"limit": 40, "exclude_replies": "true"}
    proxy = os.getenv("HTTP_PROXY") or None
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20.0, proxy=proxy, headers=headers) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Truth Social statuses response is not a list")
                return [_normalize_status(item) for item in payload if isinstance(item, dict)]
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(5)

    if last_error is not None:
        raise last_error
    return []


def _normalize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Truth Social status object into the truth-monitor internal shape."""
    media = status.get("media_attachments") or []
    media_urls = []
    for item in media:
        if not isinstance(item, dict):
            continue
        media_url = item.get("url") or item.get("remote_url") or item.get("preview_url")
        if media_url:
            media_urls.append(str(media_url))
    return {
        "id": str(status.get("id") or ""),
        "url": str(status.get("url") or status.get("uri") or ""),
        "text": _html_to_text(str(status.get("content") or "")),
        "created_at": str(status.get("created_at") or ""),
        "media_urls": media_urls,
    }


def _html_to_text(html: str) -> str:
    """Convert Truth Social HTML content into plain text."""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

