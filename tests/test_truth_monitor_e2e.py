# truth-monitor extension
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.adapters import truth_dedup, truth_downloader, truth_fetcher
from app.jobs import truth_monitor_job
from app.notifier import telegram
from storage import db as storage_db


@pytest.mark.asyncio
async def test_fetch_returns_standard_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_latest_posts returns normalized fields and strips status HTML."""

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": "123",
                    "url": "https://truthsocial.com/@realDonaldTrump/posts/123",
                    "content": "<p>Hello <strong>world</strong></p>",
                    "created_at": "2026-06-13T12:00:00Z",
                    "media_attachments": [{"url": "https://cdn.example/img.jpg"}],
                }
            ]

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.setattr(truth_fetcher.httpx, "AsyncClient", FakeClient)

    posts = await truth_fetcher.fetch_latest_posts()

    assert isinstance(posts, list)
    assert posts[0]["id"] == "123"
    assert posts[0]["url"].endswith("/123")
    assert posts[0]["text"] == "Hello world"
    assert posts[0]["created_at"] == "2026-06-13T12:00:00Z"
    assert posts[0]["media_urls"] == ["https://cdn.example/img.jpg"]


@pytest.mark.asyncio
async def test_dedup_filters_seen_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    """filter_new removes posts whose IDs are already in Redis."""

    class FakePipeline:
        def __init__(self) -> None:
            self.ids: list[str] = []

        def sismember(self, key: str, value: str) -> "FakePipeline":
            self.ids.append(value)
            return self

        async def execute(self) -> list[bool]:
            return [True, False]

    class FakeRedis:
        def pipeline(self) -> FakePipeline:
            return FakePipeline()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(truth_dedup.redis, "from_url", lambda *args, **kwargs: FakeRedis())
    posts = [{"id": "seen"}, {"id": "new"}]

    assert await truth_dedup.filter_new(posts) == [{"id": "new"}]


@pytest.mark.asyncio
async def test_download_skips_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """download_media does not request media URLs whose local files already exist."""

    media_dir = tmp_path / "media"
    existing = media_dir / "2026-06-13" / "post-1" / "img.jpg"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already-here")
    calls = {"get": 0}

    class FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        def get(self, url: str) -> None:
            calls["get"] += 1
            raise AssertionError("existing media should not be requested")

    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    monkeypatch.setattr(truth_downloader.aiohttp, "ClientSession", FakeSession)
    post = {
        "id": "post-1",
        "created_at": "2026-06-13T12:00:00Z",
        "media_urls": ["https://cdn.example/path/img.jpg"],
    }

    paths = await truth_downloader.download_media(post)

    assert paths == [str(existing)]
    assert calls["get"] == 0


def test_save_and_get_uninjected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """truth_posts storage saves, loads, and marks injected rows."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "truth.sqlite3")
    post = {
        "id": "post-1",
        "url": "https://truthsocial.com/@realDonaldTrump/posts/post-1",
        "text": "plain text",
        "created_at": "2026-06-13T12:00:00Z",
        "media_urls": ["https://cdn.example/img.jpg"],
    }

    storage_db.save_truth_post(post, ["./data/media/test/img.jpg"])
    rows = storage_db.get_uninjected_posts()
    assert len(rows) == 1
    assert rows[0]["id"] == "post-1"
    assert rows[0]["local_media"] == ["./data/media/test/img.jpg"]

    storage_db.mark_injected("post-1")
    assert storage_db.get_uninjected_posts() == []


@pytest.mark.asyncio
async def test_monitor_job_full_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_truth_monitor_job wires fetch, dedup, media, storage, notification, seen mark, and intake."""
    fetched = [
        {"id": "old", "url": "https://example/old", "text": "old", "created_at": "2026-06-13T12:00:00Z", "media_urls": []},
        {"id": "new", "url": "https://example/new", "text": "new", "created_at": "2026-06-13T12:05:00Z", "media_urls": ["https://cdn/img.jpg"]},
    ]
    mark_seen_calls: list[list[dict[str, Any]]] = []
    saved: list[tuple[dict[str, Any], list[str]]] = []

    async def fake_fetch() -> list[dict[str, Any]]:
        return fetched

    async def fake_filter(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [posts[1]]

    async def fake_download(post: dict[str, Any]) -> list[str]:
        return ["./data/media/test/img.jpg"]

    def fake_save(post: dict[str, Any], local_media: list[str]) -> None:
        saved.append((post, local_media))

    async def fake_notify(post: dict[str, Any]) -> None:
        return None

    async def fake_mark_seen(posts: list[dict[str, Any]]) -> None:
        mark_seen_calls.append(posts)

    async def fake_inject(workspace_id: str) -> int:
        assert workspace_id == "test-workspace"
        return 1

    monkeypatch.setattr(truth_monitor_job, "fetch_latest_posts", fake_fetch)
    monkeypatch.setattr(truth_monitor_job, "filter_new", fake_filter)
    monkeypatch.setattr(truth_monitor_job, "download_media", fake_download)
    monkeypatch.setattr(truth_monitor_job, "save_truth_post", fake_save)
    monkeypatch.setattr(truth_monitor_job, "notify_new_post", fake_notify)
    monkeypatch.setattr(truth_monitor_job, "mark_seen", fake_mark_seen)
    monkeypatch.setattr(truth_monitor_job, "inject_new_posts_to_intake", fake_inject)

    result = await truth_monitor_job.run_truth_monitor_job("test-workspace")

    assert result["fetched"] == 2
    assert result["new"] == 1
    assert result["injected"] >= 0
    assert result["downloaded"] == 1
    assert result["errors"] == []
    assert len(mark_seen_calls) == 1
    assert saved[0][1] == ["./data/media/test/img.jpg"]


@pytest.mark.asyncio
async def test_telegram_silent_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """notify_new_post silently skips when Telegram credentials are empty."""
    calls = {"client": 0}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls["client"] += 1

    monkeypatch.setenv("TELEGRAM_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(telegram.httpx, "AsyncClient", FakeClient)

    await telegram.notify_new_post({"created_at": "now", "text": "hello", "url": "https://example", "media_urls": []})

    assert calls["client"] == 0
