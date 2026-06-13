# truth-monitor extension
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiofiles
import aiofiles.os
import aiohttp


async def download_media(post: dict[str, Any]) -> list[str]:
    """Download media attachments for a post and return local file paths."""
    media_urls = [str(url) for url in post.get("media_urls", []) if url]
    if not media_urls:
        return []
    post_id = str(post["id"])
    day = _post_day(post)
    base_dir = Path(os.getenv("MEDIA_DIR", "./data/media")) / day / post_id
    await aiofiles.os.makedirs(base_dir, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(
            *[_download_one(session, media_url, base_dir, index) for index, media_url in enumerate(media_urls)],
            return_exceptions=True,
        )
    return [str(result) for result in results if isinstance(result, Path)]


async def _download_one(session: aiohttp.ClientSession, media_url: str, base_dir: Path, index: int) -> Path | None:
    """Download a single media URL if the local file does not already exist."""
    filename = _filename(media_url, index)
    target = base_dir / filename
    if await aiofiles.os.path.exists(target):
        return target
    async with session.get(media_url) as response:
        response.raise_for_status()
        async with aiofiles.open(target, "wb") as file:
            async for chunk in response.content.iter_chunked(1024 * 256):
                await file.write(chunk)
    return target


def _filename(media_url: str, index: int) -> str:
    """Build a stable media filename from a URL."""
    path_name = Path(urlparse(media_url).path).name
    if path_name:
        return path_name
    return f"media_{index + 1}.bin"


def _post_day(post: dict[str, Any]) -> str:
    """Return YYYY-MM-DD from post.created_at, falling back to the current UTC date."""
    value = str(post.get("created_at") or "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now(timezone.utc).date().isoformat()

