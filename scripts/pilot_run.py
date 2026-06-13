from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.editorial_qa_reporter import EditorialQAReporter

TEST_CLIENT = None


def request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    role: str,
    user: str,
    workspace: str | None = None,
    body: dict | None = None,
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-User-Name": user,
        "X-User-Role": role,
        "X-Request-ID": f"pilot-run-{int(time.time() * 1000)}",
    }
    if workspace:
        headers["X-Workspace-ID"] = workspace
    if base_url.startswith("testclient://"):
        response = TEST_CLIENT.request(method, path, json=body, headers=headers)
        payload = response.json() if response.content else {}
        return {"status_code": response.status_code, "body": payload, "request_id": response.headers.get("X-Request-ID")}
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(base_url.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=240) as response:
            payload = response.read().decode("utf-8")
            return {"status_code": response.status, "body": json.loads(payload) if payload else {}, "request_id": response.headers.get("X-Request-ID")}
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        return {"status_code": exc.code, "body": json.loads(payload) if payload else {}, "request_id": exc.headers.get("X-Request-ID")}


def load_pilot_input(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Pilot input not found: {path}. Copy data/pilot/pilot_input_template.json to data/pilot/pilot_input.json and fill it with reviewed source metadata.")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SystemExit("Pilot input must contain a non-empty sources array.")
    for index, item in enumerate(sources, start=1):
        for field in ["source_name", "source_url", "short_excerpt", "source_type"]:
            if not item.get(field):
                raise SystemExit(f"Pilot source #{index} is missing {field}.")
        if len(item["short_excerpt"]) > 500:
            raise SystemExit(f"Pilot source #{index} short_excerpt exceeds 500 characters.")
        if "sample" in item["source_name"].lower() or "fake" in item["source_name"].lower():
            raise SystemExit(f"Pilot source #{index} appears to be sample/fake data; do not use it as real pilot input.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a compliant Daily Truth Brief pilot production flow")
    parser.add_argument("--base-url", default="http://localhost:8015")
    parser.add_argument("--input", default="data/pilot/pilot_input.json")
    parser.add_argument("--workspace", default="daily-truth-brief-dev")
    parser.add_argument("--editor-name", default="PilotEditor")
    parser.add_argument("--reviewer-name", default="PilotReviewer")
    parser.add_argument("--producer-name", default="PilotProducer")
    parser.add_argument("--auto-approve-sources-for-local-test", action="store_true")
    parser.add_argument("--auto-link-evidence-for-local-test", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.base_url.startswith("testclient://"):
        _setup_test_client()

    pilot_input = load_pilot_input(Path(args.input))
    steps: list[dict] = []

    def step(name: str, method: str, path: str, *, role: str, user: str, body: dict | None = None, allow_error: bool = False) -> dict:
        result = request_json(args.base_url, method, path, role=role, user=user, workspace=args.workspace, body=body)
        steps.append(
            {
                "name": name,
                "method": method,
                "path": path,
                "role": role,
                "status_code": result["status_code"],
                "request_id": result["request_id"],
            }
        )
        if result["status_code"] >= 400 and not allow_error:
            raise SystemExit(json.dumps({"failed_step": name, "result": result, "steps": steps}, ensure_ascii=False, indent=2))
        return result["body"]

    security = step("security_health", "GET", "/health/security", role="admin", user=args.reviewer_name)
    app_env = security.get("app_env")
    if app_env not in {"local", "test"} and (args.auto_approve_sources_for_local_test or args.auto_link_evidence_for_local_test):
        raise SystemExit("Auto-approve and auto-link flags are only allowed when /health/security reports APP_ENV local/test.")
    if not security.get("manual_publish_only") or security.get("platform_publish_api_enabled"):
        raise SystemExit("Unsafe publishing configuration detected; pilot run requires manual_publish_only and no platform publish API.")

    workspace = step("workspace_current", "GET", "/workspaces/current", role="viewer", user=args.editor_name)
    source_review_items = []
    promoted_items = []
    evidence_ids = []
    for source in pilot_input["sources"]:
        ingest = step(
            "manual_url_ingest",
            "POST",
            "/sources/ingest/manual-url",
            role="editor",
            user=args.editor_name,
            body={
                "source_url": source["source_url"],
                "archive_url": source.get("archive_url"),
                "source_name": source["source_name"],
                "short_excerpt": source["short_excerpt"],
            },
        )
        source_review_items.append(ingest)
        item_id = ingest["id"]
        if args.auto_approve_sources_for_local_test:
            step(
                "source_approve",
                "POST",
                f"/sources/review-queue/{item_id}/approve",
                role="reviewer",
                user=args.reviewer_name,
                body={"reviewer_name": args.reviewer_name, "reviewer_note": "local/test pilot source approval"},
            )
            promoted = step(
                "source_promote_to_post_and_evidence",
                "POST",
                f"/sources/review-queue/{item_id}/promote-to-post-and-evidence",
                role="reviewer",
                user=args.reviewer_name,
                body={"reviewer_name": args.reviewer_name, "reviewer_note": "local/test pilot promote to post and evidence"},
            )
            promoted_items.append(promoted)
            evidence_ids.append(promoted["evidence_item"]["id"])

    if not promoted_items:
        report = _base_report("needs_source_review", args, security, workspace, pilot_input, steps)
        _write_report(report, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    topics = step("topics_generate", "POST", "/editorial/topics/generate", role="editor", user=args.editor_name, body={})
    topic = next((item for item in topics["topics"] if item["status"] == "pending"), topics["topics"][0])
    topic_id = topic["id"]
    step("topic_select", "POST", f"/editorial/topics/{topic_id}/select", role="editor", user=args.editor_name, body={"reviewer_name": args.editor_name, "reviewer_note": "pilot topic selected"})
    step(
        "topic_schedule",
        "POST",
        "/editorial/calendar/schedule",
        role="editor",
        user=args.editor_name,
        body={"topic_id": topic_id, "reviewer_name": args.editor_name, "reviewer_note": "pilot topic scheduled"},
    )
    brief = step(
        "start_production",
        "POST",
        f"/editorial/topics/{topic_id}/start-production",
        role="editor",
        user=args.editor_name,
        body={"reviewer_name": args.editor_name, "reviewer_note": "pilot production started"},
    )
    brief_id = brief["id"]
    suggestions = _suggest_links(brief, evidence_ids)
    linked = []
    if args.auto_link_evidence_for_local_test:
        for suggestion in suggestions:
            if suggestion["requires_manual_confirmation"]:
                continue
            response = step(
                "claim_evidence_link",
                "POST",
                f"/claims/{suggestion['claim_id']}/evidence-links",
                role="editor",
                user=args.editor_name,
                body={
                    "evidence_item_id": suggestion["evidence_item_id"],
                    "support_type": suggestion["support_type"],
                    "confidence": suggestion["confidence"],
                    "note": "local/test pilot auto-link suggestion",
                },
            )
            linked.append(response)

    step("evidence_pack", "POST", f"/briefs/{brief_id}/evidence-pack/generate", role="reviewer", user=args.reviewer_name, body={})
    refreshed = step("brief_get_after_evidence", "GET", f"/briefs/{brief_id}", role="viewer", user=args.editor_name)
    gate = refreshed.get("fact_check_quality_gate") or {}
    if gate.get("status") == "blocked":
        report = _base_report("blocked_by_fact_check_quality_gate", args, security, workspace, pilot_input, steps)
        report.update({"brief_id": brief_id, "claims": refreshed.get("claims", []), "evidence_linking_suggestions": suggestions, "fact_check_quality_gate": gate})
        qa = EditorialQAReporter().build(refreshed, None)
        report.update(qa)
        _write_report(report, args.output, brief_id)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    approved = step("brief_approve", "POST", f"/briefs/{brief_id}/approve", role="reviewer", user=args.reviewer_name, body={"reviewer_name": args.reviewer_name, "reviewer_note": "pilot approved after evidence quality gate"})
    render = step("producer_render", "POST", f"/briefs/{brief_id}/render-package", role="producer", user=args.producer_name, body={})
    final = step("producer_final", "POST", f"/briefs/{brief_id}/final-video", role="producer", user=args.producer_name, body={})
    platform = step("producer_platform", "POST", f"/briefs/{brief_id}/platform-package", role="producer", user=args.producer_name, body={})
    qa = EditorialQAReporter().build(step("brief_get_final", "GET", f"/briefs/{brief_id}", role="viewer", user=args.editor_name), platform)
    report = _base_report("passed", args, security, workspace, pilot_input, steps)
    report.update(
        {
            "brief_id": brief_id,
            "topic_id": topic_id,
            "claims": approved.get("claims", []),
            "evidence_linking_suggestions": suggestions,
            "linked_evidence": linked,
            "fact_check_quality_gate": approved.get("fact_check_quality_gate"),
            "render_package": render,
            "final_video": final,
            "platform_package": platform,
            **qa,
        }
    )
    _write_report(report, args.output, brief_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _suggest_links(brief: dict, evidence_ids: list[int]) -> list[dict]:
    suggestions = []
    for claim in brief.get("claims", []):
        text = (claim.get("claim_text") or "").lower()
        high_risk = claim.get("claim_type") in {"accusation", "legal", "election", "economy"} or any(
            term in text for term in ["accuse", "fraud", "illegal", "court", "election", "economy", "spending", "jobs"]
        )
        for evidence_id in evidence_ids:
            suggestions.append(
                {
                    "claim_id": claim["id"],
                    "evidence_item_id": evidence_id,
                    "support_type": "supports" if claim.get("claim_type") != "opinion" else "contextualizes",
                    "confidence": "high" if not high_risk else "medium",
                    "requires_manual_confirmation": high_risk,
                    "auto_approved": False,
                    "note": "Pilot runner suggestion only; human reviewer remains responsible for approval.",
                }
            )
    return suggestions


def _base_report(status: str, args: argparse.Namespace, security: dict, workspace: dict, pilot_input: dict, steps: list[dict]) -> dict:
    return {
        "status": status,
        "input_path": args.input,
        "workspace": workspace.get("workspace"),
        "security": security,
        "source_count": len(pilot_input.get("sources") or []),
        "steps": steps,
        "manual_publish_only": True,
        "platform_publish_api_called": False,
        "truth_social_direct_scraper_used": False,
    }


def _write_report(report: dict, output: str | None, brief_id: int | None = None) -> None:
    if output:
        path = Path(output)
    elif brief_id:
        output_dir = Path("exports/pilot_runs") / f"brief_{brief_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "pilot_run_report.json"
    else:
        path = Path("exports/pilot_runs") / "pilot_run_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _setup_test_client() -> None:
    global TEST_CLIENT
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import get_db
    from app.main import app
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
    TEST_CLIENT = TestClient(app)


if __name__ == "__main__":
    main()
