import argparse
import json

from app.api.routes import GenerateBriefRequest, ManualIngestRequest, generate_brief, ingest_manual
from app.auth.current_user import CurrentUser
from app.core.request_context import set_current_user, set_request_id
from app.db import SessionLocal, engine
from app.models import Base
from app.services.workspace_service import WorkspaceService


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Truth Brief job runner")
    parser.add_argument("--dry-run", action="store_true", help="Generate a review draft without export or publishing")
    parser.add_argument("--path", default="data/sample_posts.json", help="Manual archive JSON path")
    args = parser.parse_args()
    if not args.dry_run:
        raise SystemExit("Only --dry-run is supported in Phase 1.1")

    if engine.url.drivername.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        workspace = WorkspaceService().ensure_default_workspace(db)
        account = WorkspaceService().ensure_user_and_membership(db, "daily_brief_job", "admin", workspace)
        db.commit()
        set_request_id("daily-brief-dry-run")
        job_user = CurrentUser(
            user_id=account.id,
            user_name="daily_brief_job",
            display_name="Daily Brief Job",
            role="admin",
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            auth_mode="header_stub",
            is_authenticated=True,
            is_stub=True,
            request_id="daily-brief-dry-run",
        )
        set_current_user(job_user)
        ingest_manual(ManualIngestRequest(path=args.path), db, job_user)
        brief = generate_brief(GenerateBriefRequest(limit=3), db, job_user)
        output = {
            "brief_id": brief["id"],
            "status": brief["status"],
            "top_posts": [
                {"post_id": post["post_id"], "topic": post["topic"], "score": post["ranking_score"]}
                for post in brief["ranked_posts"]
            ],
            "safety_status": brief["safety_review"]["overall_status"],
            "exported": False,
            "published": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
