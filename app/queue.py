from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueueJob:
    name: str
    payload: dict[str, Any]


class CeleryQueuePlaceholder:
    """Stable interface to replace with Celery when background processing is needed."""

    def enqueue(self, job: QueueJob) -> dict[str, str]:
        return {"status": "not_configured", "job": job.name}

