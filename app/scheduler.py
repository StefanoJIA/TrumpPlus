import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.environment import load_environment
from app.jobs.daily_run_orchestrator import run_daily


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    enabled = os.getenv("DAILY_RUN_ENABLED", "false").strip().lower() == "true"
    mode = os.getenv("DAILY_RUN_MODE", "dry-run").strip().lower()
    hour = int(os.getenv("DAILY_RUN_HOUR", "8"))
    config = load_environment()
    if enabled:
        if mode == "local-auto" and config.app_env in {"staging", "production"}:
            raise RuntimeError("DAILY_RUN_MODE=local-auto is forbidden in staging/production")
        scheduler.add_job(
            run_daily,
            "cron",
            hour=hour,
            minute=0,
            kwargs={"run_date": "today", "mode": mode},
            id="daily_truth_brief_dry_run",
            replace_existing=True,
        )
    return scheduler
