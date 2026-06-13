# truth-monitor extension
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters import truth_dedup
from app.adapters.truth_fetcher import fetch_latest_posts
from app.adapters.truth_intake_bridge import inject_new_posts_to_intake
from storage.db import save_truth_post


class _FakePipeline:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def sismember(self, key: str, value: str) -> "_FakePipeline":
        """Record an in-memory SISMEMBER check for dry-run mode."""
        self.ids.append(value)
        return self

    async def execute(self) -> list[bool]:
        """Return all items as unseen for dry-run mode."""
        return [False for _ in self.ids]


class _FakeRedis:
    def pipeline(self) -> _FakePipeline:
        """Return a fake Redis pipeline."""
        return _FakePipeline()

    async def aclose(self) -> None:
        """Close the fake Redis client."""
        return None


def _mock_posts() -> list[dict[str, Any]]:
    """Build local mock Truth Social post dictionaries for offline dry-run validation."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"id": "mock-1", "url": "https://truthsocial.example/mock-1", "text": "Mock Truth post one", "created_at": now, "media_urls": []},
        {"id": "mock-2", "url": "https://truthsocial.example/mock-2", "text": "Mock Truth post two", "created_at": now, "media_urls": []},
        {"id": "mock-3", "url": "https://truthsocial.example/mock-3", "text": "Mock Truth post three", "created_at": now, "media_urls": []},
    ]


async def run_mock(workspace_id: str) -> dict[str, int]:
    """Run an offline dry-run through dedup, storage, and intake injection."""
    truth_dedup._client = lambda: _FakeRedis()  # type: ignore[attr-defined]
    posts = _mock_posts()
    print(f"[dryrun] mock fetched {len(posts)} posts")
    new_posts = await truth_dedup.filter_new(posts)
    print(f"[dryrun] dedup new={len(new_posts)}")
    errors = 0
    for post in new_posts:
        try:
            save_truth_post(post, [])
            print(f"[dryrun] saved post_id={post['id']}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"[dryrun] save error post_id={post.get('id')}: {exc}")
    try:
        injected = await inject_new_posts_to_intake(workspace_id)
        print(f"[dryrun] injected={injected}")
    except Exception as exc:  # noqa: BLE001
        injected = 0
        errors += 1
        print(f"[dryrun] inject error: {exc}")
    return {"fetched": len(posts), "new": len(new_posts), "injected": injected, "errors": errors}


async def run_live() -> dict[str, int]:
    """Run a live fetch-only network/API check without storage or notifications."""
    errors = 0
    try:
        posts = await fetch_latest_posts()
        print(f"[dryrun] live fetched {len(posts)} posts")
        if posts:
            print(f"[dryrun] first text preview: {posts[0].get('text', '')[:100]}")
    except Exception as exc:  # noqa: BLE001
        posts = []
        errors += 1
        print(f"[dryrun] live fetch error: {exc}")
    return {"fetched": len(posts), "new": 0, "injected": 0, "errors": errors}


async def main() -> None:
    """Parse CLI arguments and run the requested dry-run mode."""
    parser = argparse.ArgumentParser(description="Truth monitor dry-run helper")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true", help="Run offline mock mode")
    group.add_argument("--live", action="store_true", help="Run live fetch-only mode")
    parser.add_argument("--workspace-id", default="default")
    args = parser.parse_args()
    summary = await run_live() if args.live else await run_mock(args.workspace_id)
    print(f"[dryrun] fetched={summary['fetched']} new={summary['new']} injected={summary['injected']} errors={summary['errors']}")


if __name__ == "__main__":
    asyncio.run(main())
