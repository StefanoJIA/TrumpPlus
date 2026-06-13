# truth-monitor extension
from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.truth_monitor_job import run_truth_monitor_job


scheduler: AsyncIOScheduler | None = None


def configure_logging() -> None:
    """Configure console and rotating file logging for truth-monitor jobs."""
    Path("logs").mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [truth-monitor] [%(levelname)s] %(message)s")
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler("logs/truth_monitor.log", mode="a", encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=3),
    ]
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


async def _run_safely(workspace_id: str) -> None:
    """Run the truth monitor job and log exceptions without stopping the scheduler."""
    try:
        result = await run_truth_monitor_job(workspace_id)
        logging.info(
            "[job done] fetched=%s new=%s downloaded=%s injected=%s errors=%s",
            result.get("fetched", 0),
            result.get("new", 0),
            result.get("downloaded", 0),
            result.get("injected", 0),
            len(result.get("errors", [])),
        )
    except Exception:  # noqa: BLE001
        logging.exception("truth monitor job failed")


async def main() -> None:
    """Start the every-15-minutes Truth Social monitor scheduler."""
    global scheduler
    configure_logging()
    workspace_id = os.getenv("DEFAULT_WORKSPACE_ID", "default")
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_safely,
        "interval",
        minutes=15,
        args=[workspace_id],
        id="truth_monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    await _run_safely(workspace_id)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
