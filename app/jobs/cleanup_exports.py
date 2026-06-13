from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import shutil
from pathlib import Path

from app.services.production_policy import ProductionPolicy


def cleanup(dry_run: bool = True, exports_dir: Path | None = None, now: datetime | None = None) -> dict:
    policy = ProductionPolicy()
    root = exports_dir or Path("exports")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=policy.export_retention_days)
    candidates = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_dir() and path.name.startswith("brief_"):
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    candidates.append({"path": str(path), "mtime": mtime.isoformat()})
    deleted = []
    if not dry_run:
        for candidate in candidates:
            shutil.rmtree(candidate["path"], ignore_errors=True)
            deleted.append(candidate["path"])
    return {
        "dry_run": dry_run,
        "retention_days": policy.export_retention_days,
        "cutoff": cutoff.isoformat(),
        "candidates": candidates,
        "deleted": deleted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup old Daily Truth Brief export artifacts")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(cleanup(dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
