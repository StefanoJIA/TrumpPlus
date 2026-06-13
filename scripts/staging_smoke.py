from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TEST_CLIENT = None
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def request_json(base_url: str, method: str, path: str, *, role: str = "admin", user: str | None = None, body: dict | None = None) -> dict:
    if base_url.startswith("testclient://"):
        response = TEST_CLIENT.request(
            method,
            path,
            json=body,
            headers={
                "X-User-Name": user or f"smoke-{role}",
                "X-User-Role": role,
                "X-Request-ID": f"staging-smoke-{int(time.time() * 1000)}",
            },
        )
        return {"status_code": response.status_code, "body": response.json() if response.content else {}, "request_id": response.headers.get("X-Request-ID")}
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-User-Name": user or f"smoke-{role}",
            "X-User-Role": role,
            "X-Request-ID": f"staging-smoke-{int(time.time() * 1000)}",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            payload = response.read().decode("utf-8")
            return {"status_code": response.status, "body": json.loads(payload) if payload else {}, "request_id": response.headers.get("X-Request-ID")}
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        return {"status_code": exc.code, "body": json.loads(payload) if payload else {}, "request_id": exc.headers.get("X-Request-ID")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Truth Brief staging smoke check")
    parser.add_argument("--base-url", default="http://localhost:8015")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--output", default="staging_smoke_report.json")
    args = parser.parse_args()
    if args.base_url.startswith("testclient://"):
        _setup_test_client()

    stamp = int(time.time())
    steps: list[dict] = []

    def step(name: str, method: str, path: str, *, role: str = "admin", user: str | None = None, body: dict | None = None) -> dict:
        result = request_json(args.base_url, method, path, role=role, user=user, body=body)
        steps.append({"name": name, "method": method, "path": path, "role": role, "status_code": result["status_code"], "request_id": result["request_id"]})
        if result["status_code"] >= 400:
            raise SystemExit(json.dumps({"failed_step": name, "result": result, "steps": steps}, ensure_ascii=False, indent=2))
        return result["body"]

    health = step("health", "GET", "/health")
    security = step("security_health", "GET", "/health/security")
    workspace = step("workspace_current", "GET", "/workspaces/current", role="viewer", user="smoke-viewer")
    team = step("workspace_team", "GET", "/workspaces/current/team", role="admin")
    invite = step(
        "workspace_invite_create",
        "POST",
        "/workspaces/current/invites",
        role="admin",
        body={"email_or_name": f"smoke-invite-{stamp}", "role": "reviewer"},
    )
    step("workspace_invite_revoke", "POST", f"/workspaces/current/invites/{invite['id']}/revoke", role="admin")
    matrix = step("permissions_matrix", "GET", "/admin/permissions/matrix", role="admin")
    ingest = step(
        "manual_url_ingest",
        "POST",
        "/sources/ingest/manual-url",
        role="editor",
        user="smoke-editor",
        body={
            "source_url": f"https://example.org/staging-smoke/source-{stamp}",
            "archive_url": f"https://example.org/staging-smoke/archive-{stamp}",
            "source_name": "staging-smoke-source",
            "short_excerpt": "Human-entered staging smoke excerpt for neutral public information review.",
        },
    )
    item_id = ingest["id"]
    step("source_approve", "POST", f"/sources/review-queue/{item_id}/approve", role="reviewer", body={"reviewer_name": "Smoke Reviewer", "reviewer_note": "staging smoke source approval"})
    promoted = step("source_promote", "POST", f"/sources/review-queue/{item_id}/promote-to-post-and-evidence", role="reviewer", body={"reviewer_name": "Smoke Reviewer", "reviewer_note": "staging smoke promote"})
    evidence_id = promoted["evidence_item"]["id"]
    topics = step("topics_generate", "POST", "/editorial/topics/generate", role="editor", user="smoke-editor", body={})
    topic = next((item for item in topics["topics"] if item["status"] == "pending"), topics["topics"][0])
    topic_id = topic["id"]
    step("topic_select", "POST", f"/editorial/topics/{topic_id}/select", role="editor", user="smoke-editor", body={"reviewer_name": "Smoke Editor", "reviewer_note": "staging smoke select"})
    step("topic_schedule", "POST", "/editorial/calendar/schedule", role="editor", user="smoke-editor", body={"topic_id": topic_id, "reviewer_name": "Smoke Editor", "reviewer_note": "staging smoke schedule"})
    brief = step("start_production", "POST", f"/editorial/topics/{topic_id}/start-production", role="editor", user="smoke-editor", body={"reviewer_name": "Smoke Editor", "reviewer_note": "staging smoke start production"})
    brief_id = brief["id"]
    for claim in brief.get("claims", []):
        step(
            "claim_evidence_link",
            "POST",
            f"/claims/{claim['id']}/evidence-links",
            role="editor",
            user="smoke-editor",
            body={"evidence_item_id": evidence_id, "support_type": "supports", "confidence": "high", "note": "staging smoke evidence link"},
        )
    step("evidence_pack", "POST", f"/briefs/{brief_id}/evidence-pack/generate", role="reviewer", body={})
    step("brief_approve", "POST", f"/briefs/{brief_id}/approve", role="reviewer", user="smoke-reviewer", body={"reviewer_name": "Smoke Reviewer", "reviewer_note": "staging smoke approve"})
    render = step("producer_render", "POST", f"/editorial/briefs/{brief_id}/run-next-step", role="producer", body={})
    tts = step("producer_tts", "POST", f"/editorial/briefs/{brief_id}/run-next-step", role="producer", body={})
    final = step("producer_final", "POST", f"/editorial/briefs/{brief_id}/run-next-step", role="producer", body={})
    platform = step("producer_platform", "POST", f"/editorial/briefs/{brief_id}/run-next-step", role="producer", body={})
    audit = step("audit_export", "GET", "/ops/audit-log/export?format=json", role="admin")
    invariants = step("invariants", "GET", "/admin/invariants", role="admin")

    report = {
        "status": "passed" if invariants["overall_status"] == "passed" else "failed",
        "dry_run": True,
        "test_mode": args.test_mode,
        "health": health,
        "security": security,
        "workspace": workspace.get("workspace"),
        "current_user": workspace.get("current_user"),
        "team_count": len(team.get("members", [])),
        "permissions_matrix_roles": list(matrix["matrix"].keys()),
        "brief_id": brief_id,
        "render_action": render.get("executed_action"),
        "tts_action": tts.get("executed_action"),
        "final_action": final.get("executed_action"),
        "platform_action": platform.get("executed_action"),
        "audit_count": len(audit.get("audit_logs", [])),
        "invariants": invariants,
        "steps": steps,
        "manual_publish_only": True,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


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
