from __future__ import annotations

import argparse
from datetime import date as dt_date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient

from app.core.environment import security_health
from app.main import app
from app.services.auto_topic_selector import AutoTopicSelector
from app.services.daily_run_index import DailyRunIndexService
from app.services.feed_readiness_validator import FeedReadinessValidator


ROLES = {
    "editor": {"X-User-Name": "DailyRunEditor", "X-User-Role": "editor"},
    "reviewer": {"X-User-Name": "DailyRunReviewer", "X-User-Role": "reviewer"},
    "producer": {"X-User-Name": "DailyRunProducer", "X-User-Role": "producer"},
    "admin": {"X-User-Name": "DailyRunAdmin", "X-User-Role": "admin"},
    "viewer": {"X-User-Name": "DailyRunViewer", "X-User-Role": "viewer"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Truth Brief near-automated daily run")
    parser.add_argument("--date", default="today")
    parser.add_argument("--mode", choices=["dry-run", "local-auto"], default="dry-run")
    parser.add_argument("--feed-mode", choices=["json", "remote"], default="json")
    parser.add_argument("--feed", default="data/feeds/daily_truth_feed.json")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--check-feed-readiness", action="store_true")
    args = parser.parse_args()
    if args.check_feed_readiness:
        if args.feed_mode != "remote":
            raise SystemExit("--check-feed-readiness requires --feed-mode remote")
        target_date = dt_date.today().isoformat() if args.date == "today" else args.date
        report = FeedReadinessValidator().validate_remote_feed_config(args.feed, target_date=target_date)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    report = run_daily(args.date, args.mode, args.feed, args.output_dir, feed_mode=args.feed_mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def run_daily(
    run_date: str = "today",
    mode: str = "dry-run",
    feed_path: str = "data/feeds/daily_truth_feed.json",
    output_dir: str | None = None,
    *,
    feed_mode: str = "json",
) -> dict[str, Any]:
    resolved_date = dt_date.today().isoformat() if run_date == "today" else run_date
    security = security_health()
    if mode == "local-auto" and security["app_env"] not in {"local", "test"}:
        raise SystemExit("local-auto mode is only allowed in APP_ENV local/test")
    if mode == "local-auto" and security.get("platform_publish_api_enabled"):
        raise SystemExit("Unsafe configuration: platform publish API must remain disabled")

    _setup_sqlite_memory_if_needed()
    client = TestClient(app)
    steps: list[dict[str, Any]] = []

    def request(name: str, method: str, path: str, role: str, body: dict | None = None, allow_error: bool = False) -> dict[str, Any]:
        response = client.request(method, path, json=body, headers={**ROLES[role], "X-Request-ID": f"daily-run-{name}-{int(datetime.now().timestamp() * 1000)}"})
        payload = response.json() if response.content else {}
        steps.append({"name": name, "method": method, "path": path, "role": role, "status_code": response.status_code, "request_id": response.headers.get("X-Request-ID")})
        if response.status_code >= 400 and not allow_error:
            raise SystemExit(json.dumps({"failed_step": name, "status_code": response.status_code, "payload": payload, "steps": steps}, ensure_ascii=False, indent=2))
        return payload

    feed_readiness = None
    if feed_mode == "remote":
        feed_readiness = FeedReadinessValidator().validate_remote_feed_config(feed_path, target_date=resolved_date)
        if feed_readiness.get("status") == "blocked":
            report = {
                "date": resolved_date,
                "mode": mode,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "feed_path": feed_path,
                "feed_mode": feed_mode,
                "feed_readiness": feed_readiness,
                "feed_item_count": 0,
                "created_source_count": 0,
                "skipped_source_count": 0,
                "accepted_source_count": 0,
                "rejected_source_count": 0,
                "blocked_source_count": 0,
                "selected_topic": None,
                "brief_id": None,
                "evidence_coverage": [],
                "fact_check_quality_gate_status": None,
                "final_video_path": None,
                "platform_package_path": None,
                "manual_actions_required": ["Fix blocked remote feed readiness issues before source intake."],
                "manual_actions_snapshot": {},
                "final_packages_needing_human_publish_decision": [],
                "publish_readiness": "blocked",
                "blockers": feed_readiness.get("blocking_errors", []),
                "warnings": feed_readiness.get("warnings", []),
                "steps": steps,
                "manual_publish_only": True,
                "platform_publish_api_called": False,
                "truth_social_direct_scraper_used": False,
            }
            _write_report(report, output_dir)
            return report
        ingest = request("remote_feed_ingest", "POST", "/sources/ingest/remote-feed", "editor", {"config_path": feed_path, "run_date": resolved_date})
    else:
        ingest = request("daily_feed_ingest", "POST", "/sources/ingest/daily-feed-json", "editor", {"path": feed_path})
    source_items = list(ingest.get("items", []))
    if mode == "local-auto":
        source_items.extend(
            item
            for item in ingest.get("skipped_items", [])
            if item.get("human_status") in {"pending", "approved"}
        )
    promoted = []
    evidence_ids = []
    selected_topic = None
    brief = None
    gate = {}
    final_video = None
    platform_package = None
    manual_actions_required = []
    blockers = []
    warnings = []

    if mode == "dry-run":
        manual_actions_required.append("Review pending daily feed sources in /sources/review-page or /sources/review-queue.")
    else:
        for item in source_items:
            request("source_approve", "POST", f"/sources/review-queue/{item['id']}/approve", "reviewer", {"reviewer_name": "DailyRunReviewer", "reviewer_note": "local-auto source review for local/test daily run"})
            promoted_item = request(
                "source_promote_to_post_and_evidence",
                "POST",
                f"/sources/review-queue/{item['id']}/promote-to-post-and-evidence",
                "reviewer",
                {"reviewer_name": "DailyRunReviewer", "reviewer_note": "local-auto promote source to post and evidence"},
            )
            promoted.append(promoted_item)
            evidence_ids.append(promoted_item["evidence_item"]["id"])

        topics_payload = request("topics_generate", "POST", "/editorial/topics/generate", "editor", {})
        topic_decision = AutoTopicSelector().select(topics_payload.get("topics", []))
        selected_topic = topic_decision.get("selected_topic")
        if not selected_topic:
            blockers.append(topic_decision.get("blocking_reason"))
        else:
            topic_id = selected_topic["id"]
            request("topic_select", "POST", f"/editorial/topics/{topic_id}/select", "editor", {"reviewer_name": "DailyRunEditor", "reviewer_note": "local-auto selected top topic for local/test"})
            request("topic_schedule", "POST", "/editorial/calendar/schedule", "editor", {"topic_id": topic_id, "reviewer_name": "DailyRunEditor", "reviewer_note": "local-auto schedule"})
            brief = request("start_production", "POST", f"/editorial/topics/{topic_id}/start-production", "editor", {"reviewer_name": "DailyRunEditor", "reviewer_note": "local-auto start production"})
            evidence_ids.extend(_existing_evidence_ids_for_posts(selected_topic.get("selected_post_ids") or []))
            suggestions = request("evidence_link_suggestions", "GET", f"/briefs/{brief['id']}/evidence-link-suggestions", "viewer")
            linked_count = 0
            for suggestion in suggestions.get("suggestions", []):
                if suggestion.get("requires_manual_confirmation"):
                    warnings.append(f"High-risk claim {suggestion.get('claim_id')} requires manual evidence confirmation.")
                    continue
                if suggestion.get("evidence_item_id") not in evidence_ids:
                    continue
                request(
                    "claim_evidence_link",
                    "POST",
                    f"/claims/{suggestion['claim_id']}/evidence-links",
                    "editor",
                    {
                        "evidence_item_id": suggestion["evidence_item_id"],
                        "support_type": suggestion["support_type"],
                        "confidence": suggestion["confidence"],
                        "note": "local-auto daily run evidence suggestion",
                    },
                )
                linked_count += 1
            request("evidence_pack", "POST", f"/briefs/{brief['id']}/evidence-pack/generate", "reviewer", {})
            refreshed = request("brief_after_evidence", "GET", f"/briefs/{brief['id']}", "viewer")
            gate = refreshed.get("fact_check_quality_gate") or {}
            if gate.get("status") == "blocked":
                blockers.append("FactCheckQualityGate blocked brief approval.")
                manual_actions_required.append(f"Strengthen evidence for brief {brief['id']} before approval.")
            else:
                approved = request("brief_approve", "POST", f"/briefs/{brief['id']}/approve", "reviewer", {"reviewer_name": "DailyRunReviewer", "reviewer_note": "local-auto approve after gate passed"})
                request("render_package", "POST", f"/briefs/{brief['id']}/render-package", "producer", {})
                final_video = request("final_video", "POST", f"/briefs/{brief['id']}/final-video", "producer", {})
                platform_package = request("platform_package", "POST", f"/briefs/{brief['id']}/platform-package", "producer", {})
                brief = approved
                manual_actions_required.append("Final platform package requires human publish decision; no platform API was called.")
            if linked_count == 0:
                warnings.append("No evidence links were auto-created; manual evidence linking may be required.")

    manual_actions = request("manual_actions", "GET", f"/daily-runs/{resolved_date}/manual-actions", "viewer", allow_error=True)
    report = {
        "date": resolved_date,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_path": feed_path,
        "feed_mode": feed_mode,
        "feed_readiness": feed_readiness,
        "feed_filter_report": ingest.get("filter_report"),
        "feed_item_count": int(ingest.get("created_count", 0)) + int(ingest.get("skipped_count", 0)),
        "created_source_count": ingest.get("created_count", 0),
        "skipped_source_count": ingest.get("skipped_count", 0),
        "accepted_source_count": len(promoted),
        "rejected_source_count": 0,
        "blocked_source_count": 0,
        "selected_topic": selected_topic,
        "brief_id": brief.get("id") if isinstance(brief, dict) else None,
        "evidence_coverage": gate.get("claim_coverage", []),
        "fact_check_quality_gate_status": gate.get("status"),
        "final_video_path": final_video.get("video_path") if final_video else None,
        "platform_package_path": platform_package.get("package_path") if platform_package else None,
        "manual_actions_required": manual_actions_required,
        "manual_actions_snapshot": manual_actions if isinstance(manual_actions, dict) else {},
        "final_packages_needing_human_publish_decision": [platform_package] if platform_package else [],
        "publish_readiness": "manual_review_required" if platform_package else "not_ready",
        "blockers": [item for item in blockers if item],
        "warnings": warnings,
        "steps": steps,
        "manual_publish_only": True,
        "platform_publish_api_called": False,
        "truth_social_direct_scraper_used": False,
    }
    _write_report(report, output_dir)
    return report


def _write_report(report: dict[str, Any], output_dir: str | None) -> None:
    root = Path(output_dir) if output_dir else Path("exports/daily_runs") / report["date"]
    root.mkdir(parents=True, exist_ok=True)
    (root / "daily_run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "DAILY_RUN_REPORT.md").write_text(_markdown(report), encoding="utf-8")
    if output_dir is None:
        DailyRunIndexService().write_index()


def _existing_evidence_ids_for_posts(post_ids: list[int]) -> list[int]:
    if not post_ids:
        return []
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import EvidenceItem

    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(EvidenceItem.id).where(
                    EvidenceItem.post_id.in_(post_ids),
                    EvidenceItem.human_status == "approved",
                )
            ).all()
        )
    except Exception:  # noqa: BLE001 - optional local-auto enhancement; keep base flow working.
        return []
    finally:
        db.close()


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Daily Run Report",
        "",
        f"Date: {report['date']}",
        f"Mode: {report['mode']}",
        f"Feed mode: {report.get('feed_mode')}",
        f"Feed readiness: {(report.get('feed_readiness') or {}).get('status')}",
        f"Feed items: {report['feed_item_count']}",
        f"Selected topic: {(report.get('selected_topic') or {}).get('title')}",
        f"FactCheckQualityGate: {report.get('fact_check_quality_gate_status')}",
        f"Final video: {report.get('final_video_path')}",
        f"Platform package: {report.get('platform_package_path')}",
        "",
        "## Manual Actions Required",
    ]
    lines.extend([f"- {item}" for item in report.get("manual_actions_required", [])] or ["- Review queue for pending items."])
    lines.extend(["", "## Blockers"])
    lines.extend([f"- {item}" for item in report.get("blockers", [])] or ["- None recorded."])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {item}" for item in report.get("warnings", [])] or ["- None recorded."])
    lines.extend(["", "Manual publish only. No platform publishing API was called. No Truth Social direct scraper was used."])
    return "\n".join(lines) + "\n"


def _setup_sqlite_memory_if_needed() -> None:
    if os.getenv("DATABASE_URL") != "sqlite+pysqlite:///:memory:":
        return
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import get_db
    from app.models import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db: Session = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db


if __name__ == "__main__":
    main()
