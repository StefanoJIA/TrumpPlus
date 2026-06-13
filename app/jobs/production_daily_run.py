from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, Post
from app.services.blocking_reason_aggregator import BlockingReasonAggregator
from app.services.production_policy import ProductionPolicy
from app.services.topic_selector import TopicSelector


def run(dry_run: bool = True, output_root: Path | None = None, explicit_test_mode: bool = False) -> dict:
    if engine.url.drivername.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    policy = ProductionPolicy()
    output_dir = (output_root or Path("exports/production_runs")) / date.today().isoformat()
    db = SessionLocal()
    try:
        promoted_posts = [
            post
            for post in db.scalars(select(Post).order_by(Post.published_at.desc())).all()
            if post.source_policy.get("human_source_review_status") == "promoted"
        ]
        sample_posts = [
            post
            for post in db.scalars(select(Post)).all()
            if post.source_policy.get("evidence", {}).get("sample_data") is True
        ]
        policy_warnings = []
        if sample_posts and not policy.sample_data_allowed(explicit_test_mode=explicit_test_mode):
            policy_warnings.append("sample_data_present_but_blocked_in_production")

        brief_payload = None
        evidence_result = None
        topic_result = None
        if promoted_posts and policy.max_daily_briefs > 0:
            topic_result = TopicSelector().generate_topics(db, output_dir=output_dir if not dry_run else None)
            db.commit()
        blocking = BlockingReasonAggregator().aggregate(db)
        report = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "production_mode": policy.production_mode,
            "automatic_approval": False,
            "automatic_render": False,
            "automatic_publish": False,
            "policy_warnings": policy_warnings,
            "source_summary": {
                "promoted_posts": len(promoted_posts),
                "sample_posts_blocked": len(sample_posts) if not policy.sample_data_allowed(explicit_test_mode) else 0,
            },
            "topic_summary": None
            if topic_result is None
            else {
                "topic_count": len(topic_result["topics"]),
                "report_path": topic_result["report_path"],
                "auto_selected": False,
                "recommended_topics": [
                    {
                        "id": topic.id,
                        "status": topic.status,
                        "title": topic.title,
                        "priority_score": topic.priority_score,
                        "blocking_reasons": topic.rationale.get("blocking_reasons", []),
                    }
                    for topic in topic_result["topics"]
                ],
            },
            "brief_summary": brief_payload,
            "evidence_summary": None
            if evidence_result is None
            else {
                "evidence_pack_count": len(evidence_result["evidence_packs"]),
                "safety_status": evidence_result["safety_review"]["overall_status"],
            },
            "blocking_reasons": blocking,
        }
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "source_summary.json").write_text(json.dumps(report["source_summary"], ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "topic_summary.json").write_text(json.dumps(report["topic_summary"], ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "brief_summary.json").write_text(json.dumps(report["brief_summary"], ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "blocking_reasons.json").write_text(json.dumps(blocking, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "README_RUN.md").write_text(_readme(report), encoding="utf-8")
        return report
    finally:
        db.close()


def _readme(report: dict) -> str:
    return "\n".join(
        [
            "# Daily Truth Brief Production Run",
            "",
            "This run never auto-approves, auto-renders, or auto-publishes political content.",
            "",
            f"Run at: {report['run_at']}",
            f"Dry run: {report['dry_run']}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Truth Brief production daily run")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--test-mode", action="store_true", help="Allow sample data for tests only")
    args = parser.parse_args()
    report = run(dry_run=args.dry_run, explicit_test_mode=args.test_mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
