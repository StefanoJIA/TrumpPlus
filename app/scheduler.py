from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    # Daily ingest/generate jobs are intentionally not auto-started in the MVP.
    # Operators must choose compliant source files and human review remains required.
    return scheduler

