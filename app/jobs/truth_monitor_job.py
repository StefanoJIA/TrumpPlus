# truth-monitor extension
from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.truth_dedup import filter_new, mark_seen
from app.adapters.truth_downloader import download_media
from app.adapters.truth_fetcher import fetch_latest_posts
from app.adapters.truth_intake_bridge import inject_new_posts_to_intake
from app.notifier.telegram import notify_new_post
from storage.db import save_truth_post


async def run_truth_monitor_job(workspace_id: str) -> dict[str, Any]:
    """Run one Truth Social monitor cycle from fetch through source intake injection."""
    errors: list[str] = []
    downloaded = 0
    fetched_posts: list[dict[str, Any]] = []
    new_posts: list[dict[str, Any]] = []

    try:
        fetched_posts = await fetch_latest_posts()
        new_posts = await filter_new(fetched_posts)
    except Exception as exc:  # noqa: BLE001 - monitor jobs report errors without killing scheduler
        return {"fetched": len(fetched_posts), "new": len(new_posts), "downloaded": downloaded, "injected": 0, "errors": [str(exc)]}

    for post in new_posts:
        try:
            local_media = await download_media(post)
            downloaded += len(local_media)
            await asyncio.to_thread(save_truth_post, post, local_media)
            await notify_new_post(post)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{post.get('id')}: {exc}")

    try:
        await mark_seen(new_posts)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mark_seen: {exc}")

    try:
        injected = await inject_new_posts_to_intake(workspace_id)
    except Exception as exc:  # noqa: BLE001
        injected = 0
        errors.append(f"inject: {exc}")

    return {
        "fetched": len(fetched_posts),
        "new": len(new_posts),
        "downloaded": downloaded,
        "injected": injected,
        "errors": errors,
    }
