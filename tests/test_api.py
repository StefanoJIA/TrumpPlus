import io
import json
import os
import pytest
import shutil
import subprocess
import sys
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

from jsonschema import validate
from PIL import Image

from app.services.compliance_copy_checker import ComplianceCopyChecker
from app.services.auto_topic_selector import AutoTopicSelector
from app.services.daily_run_index import DailyRunIndexService
from app.services.editorial_qa_reporter import EditorialQAReporter
from app.services.evidence_link_suggester import EvidenceLinkSuggester
from app.services.feed_readiness_validator import FeedReadinessValidator
from app.services.script_writer import ScriptWriter
from app.services.script_readability_qa import ScriptReadabilityQA
from app.services.safety_checker import SafetyChecker
from app.services.subtitle_timing_qa import SubtitleTimingQA
from app.services.source_policy import SourcePolicy
from app.services.visual_template_qa import VisualTemplateQA
from app.services.video_qa_analyzer import VideoQAAnalyzer
from app.evidence.registry import default_registry
from app.external_search.registry import ExternalSearchProviderRegistry
from app.jobs.cleanup_exports import cleanup
from app.jobs import production_daily_run
from app.db import get_db
from app.main import app
from app.models import ApprovalRecord, AuditLog, Base, BriefScript, Claim, ClaimEvidenceLink, EditorialTopic, EvidenceItem, EvidencePack, Post, RenderPackage, Source, Workspace
from app.core.environment import load_environment
from app.services.blocking_reason_aggregator import BlockingReasonAggregator
from app.services.evidence_query_builder import EvidenceQueryBuilder
from app.services.production_policy import ProductionPolicy
from app.services.tts_policy import TTSPolicy
from app.services.voice_qa import VoiceQA
from app.sources.manual_url import ManualUrlAdapter
from app.sources.daily_feed_json import DailyFeedJsonAdapter
from app.sources.remote_feed import RemoteFeedAdapter
from app.sources.registry import SourceAdapterRegistry
from app.tts.local_stub import LocalStubTTSProvider
from app.tts.openai_provider import OpenAITTSProvider
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def load_schema(name: str) -> dict:
    return json.loads(Path("schemas", name).read_text(encoding="utf-8"))


def generate_sample_brief(client) -> dict:
    ingest_response = client.post("/ingest/manual", json={"path": "data/sample_posts.json"})
    assert ingest_response.status_code == 200
    assert ingest_response.json()["created_count"] == 3
    brief_response = client.post("/briefs/generate", json={"limit": 3})
    assert brief_response.status_code == 200
    return brief_response.json()


def role_headers(username: str, role: str) -> dict[str, str]:
    return {"X-User-Name": username, "X-User-Role": role}


def promote_manual_source(client, *, source_url: str, excerpt: str, source_name: str = "Reviewed Public Archive") -> dict:
    ingest = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": source_url,
            "archive_url": source_url + "/archive",
            "short_excerpt": excerpt,
            "source_name": source_name,
        },
    )
    assert ingest.status_code == 200
    item_id = ingest.json()["id"]
    approve = client.post(
        f"/sources/review-queue/{item_id}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "source terms and excerpt reviewed"},
    )
    assert approve.status_code == 200
    promote = client.post(
        f"/sources/review-queue/{item_id}/promote-to-post",
        json={"reviewer_name": "Editor A", "reviewer_note": "promoted for editorial topic selection"},
    )
    assert promote.status_code == 200
    return promote.json()["post"]


def generate_selected_topic_brief(client, *, source_url: str = "https://example.org/editorial/production-helper") -> tuple[dict, dict]:
    promote_manual_source(
        client,
        source_url=source_url,
        excerpt="A reviewed public source describes a public policy messaging topic for neutral production.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    select = client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor A", "reviewer_note": "selected for production helper"},
    )
    assert select.status_code == 200
    brief = client.post(
        f"/editorial/topics/{topic['id']}/start-production",
        json={"reviewer_name": "Editor A", "reviewer_note": "start production helper"},
    )
    assert brief.status_code == 200
    return topic, brief.json()


def generate_approved_final_video(client) -> tuple[dict, dict]:
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved for platform package"},
    )
    assert approve_response.status_code == 200
    render_response = client.post(f"/briefs/{brief['id']}/render-package")
    assert render_response.status_code == 200
    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 200
    return approve_response.json(), final_response.json()


def first_claim(brief: dict, claim_type: str | None = None) -> dict:
    for claim in brief["claims"]:
        if claim_type is None or claim["claim_type"] == claim_type:
            return claim
    raise AssertionError(f"Claim not found: {claim_type}")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_manual_ingest_generate_review_report_and_schemas(client):
    brief = generate_sample_brief(client)
    assert brief["status"] == "needs_review"
    assert len(brief["ranked_posts"]) == 3
    assert brief["claims"]
    assert brief["fact_checks"]
    assert "sources" in brief["script"]
    assert brief["script"]["sources"]
    assert brief["visual_plan"]["cards"]
    assert brief["safety_review"]["overall_status"] in {"passed", "warning"}
    assert brief["video_asset"]["status"] == "pending_human_review"
    assert brief["video_asset"]["export_allowed"] is False
    assert all(post["source_review_required"] for post in brief["ranked_posts"])

    validate(brief["safety_review"], load_schema("safety_review.schema.json"))
    validate(brief["video_asset"], load_schema("video_asset.schema.json"))

    report_response = client.get(f"/briefs/{brief['id']}/review-report")
    assert report_response.status_code == 200
    assert report_response.json()["safety_review"]["rules"]

    review_page_response = client.get(f"/briefs/{brief['id']}/review-page")
    assert review_page_response.status_code == 200
    assert "Safety Rules" in review_page_response.text


def test_unknown_non_manual_source_blocked_by_policy():
    result = SourcePolicy().validate_source(
        {"source_url": "https://unknown.example/archive/1", "short_excerpt": "short"},
        {"name": "unknown-feed", "manual_input": False, "sample_data": False},
    )
    assert result.allowed is False
    assert "unknown_source_not_manual_input" in result.reasons


def test_manual_url_creates_pending_source_review_item(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/manual/source-001",
            "archive_url": "https://example.org/archive/source-001",
            "source_name": "manual-editor-link",
            "short_excerpt": "A public archive excerpt manually entered for review.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["adapter_name"] == "manual_url"
    assert payload["terms_status"] == "manual_review_required"
    assert payload["human_status"] == "pending"

    queue = client.get("/sources/review-queue?status=pending")
    assert queue.status_code == 200
    assert queue.json()["count"] == 1


def test_public_archive_json_creates_review_items(client):
    response = client.post("/sources/ingest/public-archive-json", json={"path": "data/public_archive_sample.json"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert all(item["adapter_name"] == "public_archive_json" for item in payload["items"])
    assert all(item["human_status"] == "pending" for item in payload["items"])


def test_unknown_adapter_blocked():
    registry = SourceAdapterRegistry()
    registry.register_adapter("manual_url", ManualUrlAdapter())
    try:
        registry.get_adapter("unknown")
    except KeyError as exc:
        assert "Unknown source adapter" in str(exc)
    else:
        raise AssertionError("Unknown adapter should be blocked")


def test_blocked_source_cannot_promote_to_post(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://truthsocial.com/@sample/posts/1",
            "source_name": "blocked-direct-source",
            "short_excerpt": "Manual excerpt from a blocked direct domain.",
        },
    )
    assert response.status_code == 200
    item = response.json()
    assert item["terms_status"] == "blocked"
    approve = client.post(
        f"/sources/review-queue/{item['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "attempt approval"},
    )
    assert approve.status_code == 200
    promote = client.post(
        f"/sources/review-queue/{item['id']}/promote-to-post",
        json={"reviewer_name": "Editor A", "reviewer_note": "attempt promote"},
    )
    assert promote.status_code == 409
    assert "Blocked" in promote.json()["detail"]


def test_pending_source_cannot_promote_to_post(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/manual/source-002",
            "source_name": "manual-editor-link",
            "short_excerpt": "Pending source review item.",
        },
    )
    item = response.json()
    promote = client.post(
        f"/sources/review-queue/{item['id']}/promote-to-post",
        json={"reviewer_name": "Editor A", "reviewer_note": "not approved yet"},
    )
    assert promote.status_code == 409
    assert "approved" in promote.json()["detail"]


def test_approved_source_can_promote_to_post_and_audit_logs(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/manual/source-003",
            "archive_url": "https://example.org/archive/source-003",
            "source_name": "manual-editor-link",
            "short_excerpt": "A manually reviewed public source discusses a policy schedule.",
        },
    )
    item = response.json()
    approve = client.post(
        f"/sources/review-queue/{item['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "archive link and excerpt reviewed"},
    )
    assert approve.status_code == 200
    promote = client.post(
        f"/sources/review-queue/{item['id']}/promote-to-post",
        json={"reviewer_name": "Editor A", "reviewer_note": "promote after review"},
    )
    assert promote.status_code == 200
    post = promote.json()["post"]
    assert post["source_policy"]["human_source_review_status"] == "promoted"
    assert post["source_review_required"] is False

    detail = client.get(f"/sources/review-queue/{item['id']}")
    actions = [log["action"] for log in detail.json()["audit_logs"]]
    assert "source_approved" in actions
    assert "promote_to_post" in actions


def test_brief_generation_ignores_unpromoted_source_review_items(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/manual/source-004",
            "source_name": "manual-editor-link",
            "short_excerpt": "This item is pending and must not enter brief generation.",
        },
    )
    assert response.status_code == 200
    brief_response = client.post("/briefs/generate", json={"limit": 3})
    assert brief_response.status_code == 400
    assert "promote" in brief_response.json()["detail"]


def test_long_excerpt_blocks_safety_review():
    review = SafetyChecker().review(
        ranked_posts=[
            {
                "short_excerpt": "x" * 501,
                "source_url": "https://example.org/archive/1",
                "post_id": "sample",
            }
        ],
        script={"text": "Neutral script.", "sources": [{"url": "https://example.org/archive/1"}]},
        visual_plan={"cards": [{"ai_label": "AI 生成示意图"}], "prohibited": ["fake_screenshot", "lip_sync"]},
        fact_checks=[],
        claims=[],
    )
    assert review["overall_status"] == "blocked"
    assert review["checks"]["excerpt_length_within_limit"] is False


def test_blocked_safety_cannot_approve_or_export(client, tmp_path):
    unsafe_sample = tmp_path / "unsafe_sample.json"
    unsafe_sample.write_text(
        json.dumps(
            {
                "sample_data": True,
                "source": {
                    "name": "unsafe-sample-manual-public-archive",
                    "base_url": "https://example.org/unsafe",
                    "public_archive_url": "https://example.org/unsafe",
                    "direct_truth_social_scrape": False,
                },
                "posts": [
                    {
                        "post_id": "sample-unsafe-001",
                        "published_at": "2026-06-10T13:00:00Z",
                        "source_url": "https://example.org/archive/sample-unsafe-001",
                        "text": "SAMPLE FAKE POST: A public figure accuse opponents of illegal conduct without evidence.",
                        "short_excerpt": "SAMPLE FAKE POST: A fictional accusation without evidence.",
                        "summary": "A fictional public post accuse opponents of illegal conduct without evidence.",
                        "topic": "sample accusation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ingest = client.post("/ingest/manual", json={"path": str(unsafe_sample)})
    assert ingest.status_code == 200
    brief = client.post("/briefs/generate", json={"limit": 3}).json()
    assert brief["status"] == "blocked"
    assert brief["safety_review"]["overall_status"] == "blocked"
    assert brief["video_asset"]["status"] == "blocked"
    assert brief["video_asset"]["export_allowed"] is False

    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "attempt approval"},
    )
    assert approve_response.status_code == 409

    export_response = client.get(f"/briefs/{brief['id']}/export-package")
    assert export_response.status_code == 409


def test_unapproved_brief_cannot_export(client):
    brief = generate_sample_brief(client)
    export_response = client.get(f"/briefs/{brief['id']}/export-package")
    assert export_response.status_code == 409
    assert "approved" in export_response.json()["detail"]

    render_response = client.post(f"/briefs/{brief['id']}/render-package")
    assert render_response.status_code == 409
    assert "approved" in render_response.json()["detail"]

    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 409
    assert "approved" in final_response.json()["detail"]

    platform_response = client.post(f"/briefs/{brief['id']}/platform-package")
    assert platform_response.status_code == 409
    assert "approved" in platform_response.json()["detail"]


def test_approved_brief_can_export_zip(client):
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "source links checked"},
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["video_asset"]["export_allowed"] is True

    export_response = client.get(f"/briefs/{brief['id']}/export-package")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"

    with ZipFile(io.BytesIO(export_response.content)) as archive:
        names = set(archive.namelist())
        assert {
            "script.txt",
            "script.json",
            "title_options.json",
            "visual_plan.json",
            "video_asset.json",
            "sources.json",
            "fact_checks.json",
            "safety_review.json",
            "README_EXPORT.md",
        }.issubset(names)
        export_manifest = {
            "brief_id": brief["id"],
            "status": "approved",
            "title_options": json.loads(archive.read("title_options.json")),
            "script": json.loads(archive.read("script.json")),
            "visual_plan": json.loads(archive.read("visual_plan.json")),
            "video_asset": json.loads(archive.read("video_asset.json")),
            "sources": json.loads(archive.read("sources.json")),
            "fact_checks": json.loads(archive.read("fact_checks.json")),
            "safety_review": json.loads(archive.read("safety_review.json")),
            "ranked_posts": approved["ranked_posts"],
            "claims": approved["claims"],
            "export_notes": {
                "mp4_rendered": False,
                "automatic_publishing": False,
                "ai_visuals_label_required": "AI 生成示意图",
            },
        }
        validate(export_manifest, load_schema("brief_export.schema.json"))
        assert json.loads(archive.read("sources.json"))
        assert b"automatic" in archive.read("README_EXPORT.md")


def test_blocked_brief_cannot_generate_render_package(client, tmp_path):
    unsafe_sample = tmp_path / "unsafe_render_sample.json"
    unsafe_sample.write_text(
        json.dumps(
            {
                "sample_data": True,
                "source": {
                    "name": "unsafe-render-sample",
                    "base_url": "https://example.org/unsafe-render",
                    "public_archive_url": "https://example.org/unsafe-render",
                    "direct_truth_social_scrape": False,
                },
                "posts": [
                    {
                        "post_id": "sample-unsafe-render-001",
                        "published_at": "2026-06-10T13:00:00Z",
                        "source_url": "https://example.org/archive/sample-unsafe-render-001",
                        "text": "SAMPLE FAKE POST: A public figure accuse opponents of illegal conduct without evidence.",
                        "short_excerpt": "SAMPLE FAKE POST: A fictional accusation without evidence.",
                        "summary": "A fictional public post accuse opponents of illegal conduct without evidence.",
                        "topic": "sample accusation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert client.post("/ingest/manual", json={"path": str(unsafe_sample)}).status_code == 200
    brief = client.post("/briefs/generate", json={"limit": 3}).json()
    assert brief["status"] == "blocked"
    response = client.post(f"/briefs/{brief['id']}/render-package")
    assert response.status_code == 409
    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 409
    platform_response = client.post(f"/briefs/{brief['id']}/platform-package")
    assert platform_response.status_code == 409


def test_approved_brief_can_generate_render_package(client):
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "ready for render package"},
    )
    assert approve_response.status_code == 200

    render_response = client.post(f"/briefs/{brief['id']}/render-package")
    assert render_response.status_code == 200
    render_payload = render_response.json()
    assert render_payload["status"] == "generated"
    validate(render_payload["manifest"], load_schema("render_manifest.schema.json"))
    assert render_payload["readiness_report"]["ready"] is True

    output_dir = Path(render_payload["output_dir"])
    required = {
        "manifest.json",
        "script.txt",
        "subtitles.srt",
        "subtitles.json",
        "cover.png",
        "card_01_topic.png",
        "card_02_fact_check.png",
        "card_03_timeline.png",
        "card_04_sources.png",
        "sources.json",
        "safety_review.json",
        "README_RENDER.md",
        "readiness_report.json",
    }
    assert required.issubset({path.name for path in output_dir.iterdir()})

    srt = (output_dir / "subtitles.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 -->" in srt
    subtitle_items = json.loads((output_dir / "subtitles.json").read_text(encoding="utf-8"))
    assert subtitle_items
    assert all(len(item["text"]) <= 18 for item in subtitle_items)

    for filename in ["cover.png", "card_01_topic.png", "card_02_fact_check.png", "card_03_timeline.png", "card_04_sources.png"]:
        with Image.open(output_dir / filename) as image:
            assert image.format == "PNG"
            assert image.size == (1080, 1920)

    readiness = json.loads((output_dir / "readiness_report.json").read_text(encoding="utf-8"))
    assert readiness["ready"] is True
    assert readiness["mp4_rendered"] is False

    download_response = client.get(f"/briefs/{brief['id']}/render-package/download")
    assert download_response.status_code == 200
    with ZipFile(io.BytesIO(download_response.content)) as archive:
        names = set(archive.namelist())
        assert required.issubset(names)


def test_tts_voice_policy_blocks_impersonation_names(tmp_path):
    provider = LocalStubTTSProvider()
    for voice in ["trump", "donald_trump", "celebrity_clone", "impersonation_voice"]:
        try:
            provider.synthesize("test", tmp_path / "audio.wav", voice=voice)
        except ValueError as exc:
            assert "Voice policy blocked" in str(exc) or "Only neutral_zh" in str(exc)
        else:
            raise AssertionError(f"Voice should have been blocked: {voice}")


def test_tts_policy_allows_neutral_voices_and_blocks_external_by_default():
    policy = TTSPolicy()
    for voice in ["neutral_zh", "neutral_zh_female", "neutral_zh_male"]:
        policy.validate_voice_name(voice)
    try:
        policy.validate_provider("openai_tts", production=True)
    except ValueError as exc:
        assert "External TTS is disabled" in str(exc)
    else:
        raise AssertionError("External TTS should be disabled by default")


def test_openai_tts_provider_does_not_call_external_api_when_policy_disabled(tmp_path):
    class FakeClient:
        called = False

        def synthesize(self, text, voice, model):
            self.called = True
            return b"fake-audio"

    fake = FakeClient()
    provider = OpenAITTSProvider(client=fake)
    try:
        provider.synthesize("测试文本", tmp_path / "audio.mp3", voice="neutral_zh")
    except ValueError as exc:
        assert "External TTS is disabled" in str(exc)
    else:
        raise AssertionError("OpenAI TTS should be blocked when allow_external_tts=false")
    assert fake.called is False


def test_approved_brief_can_generate_local_stub_tts_and_download(client):
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved for tts"},
    )
    assert approve_response.status_code == 200
    response = client.post(f"/briefs/{brief['id']}/tts/generate", json={"provider": "local_stub", "voice": "neutral_zh"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["metadata"]["provider"] == "local_stub"
    assert payload["voice_qa"]["status"] in {"passed", "warning"}

    status_response = client.get(f"/briefs/{brief['id']}/tts/status")
    assert status_response.status_code == 200
    assert status_response.json()["audio_path"].endswith("audio.wav")

    download_response = client.get(f"/briefs/{brief['id']}/tts/download")
    assert download_response.status_code == 200
    assert "audio" in download_response.headers["content-type"]
    assert len(download_response.content) > 0


def test_unapproved_brief_cannot_generate_external_tts(client):
    brief = generate_sample_brief(client)
    response = client.post(f"/briefs/{brief['id']}/tts/generate", json={"provider": "openai_tts", "voice": "neutral_zh"})
    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_external_tts_blocked_when_policy_disabled_for_approved_brief(client):
    brief = generate_sample_brief(client)
    assert client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved for external tts policy check"},
    ).status_code == 200
    response = client.post(f"/briefs/{brief['id']}/tts/generate", json={"provider": "openai_tts", "voice": "neutral_zh"})
    assert response.status_code == 409
    assert "External TTS is disabled" in response.json()["detail"]


def test_voice_qa_blocks_bad_metadata(tmp_path):
    audio_path = tmp_path / "audio.wav"
    LocalStubTTSProvider().synthesize("test", audio_path, voice="neutral_zh")
    metadata = {
        "provider": "local_stub",
        "voice": "trump_impersonation",
        "voice_policy": "voice clone impersonation",
        "disclosure": "",
    }
    report = VoiceQA().review(audio_path, metadata)
    assert report["status"] == "blocked"
    assert "voice_allowed" in report["blocking_reasons"]
    assert "no_blocked_voice_terms" in report["blocking_reasons"]


def test_approved_without_render_package_cannot_render_final_video(client):
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved but no render package"},
    )
    assert approve_response.status_code == 200
    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 409
    assert "render package" in final_response.json()["detail"].lower()

    platform_response = client.post(f"/briefs/{brief['id']}/platform-package")
    assert platform_response.status_code == 409
    assert "final video" in platform_response.json()["detail"].lower()


def test_approved_with_render_package_can_render_and_download_final_video(client):
    brief = generate_sample_brief(client)
    approve_response = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved for final render"},
    )
    assert approve_response.status_code == 200
    render_response = client.post(f"/briefs/{brief['id']}/render-package")
    assert render_response.status_code == 200

    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 200
    final_payload = final_response.json()
    assert final_payload["status"] == "rendered"
    assert final_payload["tts_provider"] == "local_stub"
    assert final_payload["duration_seconds"] >= 45
    video_path = Path(final_payload["video_path"])
    assert video_path.exists()
    assert video_path.stat().st_size > 0

    output_dir = video_path.parent
    required = {
        "final_video.mp4",
        "narration.txt",
        "narration_segments.json",
        "audio.wav",
        "tts_metadata.json",
        "render_report.json",
        "README_FINAL_VIDEO.md",
    }
    assert required.issubset({path.name for path in output_dir.iterdir()})
    report = json.loads((output_dir / "render_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "rendered"
    assert report["duration_seconds"] >= 45
    assert report["video_size_bytes"] > 0
    assert report["files"]["final_video"].endswith("final_video.mp4")
    assert report["subtitles_burned_in"] is True
    assert report["automatic_publishing"] is False
    tts_metadata = json.loads((output_dir / "tts_metadata.json").read_text(encoding="utf-8"))
    assert tts_metadata["voice"] == "neutral_zh"
    assert tts_metadata["external_api_called"] is False

    get_response = client.get(f"/briefs/{brief['id']}/final-video")
    assert get_response.status_code == 200
    assert get_response.json()["render_report"]["mp4_rendered"] is True

    download_response = client.get(f"/briefs/{brief['id']}/final-video/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "video/mp4"
    assert len(download_response.content) > 0


def test_final_video_uses_generated_tts_when_available(client):
    brief = generate_sample_brief(client)
    assert client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved for generated tts final render"},
    ).status_code == 200
    assert client.post(f"/briefs/{brief['id']}/render-package").status_code == 200
    tts_response = client.post(f"/briefs/{brief['id']}/tts/generate", json={"provider": "local_stub", "voice": "neutral_zh_female"})
    assert tts_response.status_code == 200
    final_response = client.post(f"/briefs/{brief['id']}/final-video")
    assert final_response.status_code == 200
    report = final_response.json()["render_report"]
    assert report["tts_source"] == "generated_tts"
    assert report["voice"] == "neutral_zh_female"
    assert report["voice_qa_status"] in {"passed", "warning"}


def test_approved_with_final_video_can_generate_platform_package_and_download(client):
    brief, final_payload = generate_approved_final_video(client)
    response = client.post(f"/briefs/{brief['id']}/platform-package")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "generated"
    assert payload["manual_publish_only"] is True
    assert payload["qa_report"]["video_codec"] == "h264"
    assert payload["qa_report"]["audio_codec"] == "aac"
    assert payload["qa_report"]["has_video"] is True
    assert payload["qa_report"]["has_audio"] is True
    assert payload["copy_compliance_report"]["overall_status"] == "passed"
    assert Path(payload["package_path"]).exists()
    assert Path(payload["package_path"]).stat().st_size > 0

    output_dir = Path(payload["output_dir"])
    required = {
        "final_video.mp4",
        "bilibili.json",
        "xiaohongshu.json",
        "douyin.json",
        "youtube_shorts.json",
        "qa_report.json",
        "copy_compliance_report.json",
        "sources.json",
        "safety_review.json",
        "MANUAL_PUBLISH_CHECKLIST.md",
        "README_PLATFORM_PACKAGE.md",
        "platform_package.zip",
    }
    assert required.issubset({path.name for path in output_dir.iterdir()})

    for platform in ["bilibili", "xiaohongshu", "douyin", "youtube_shorts"]:
        platform_copy = json.loads((output_dir / f"{platform}.json").read_text(encoding="utf-8"))
        assert len(platform_copy["title_options"]) >= 3
        assert "Sources:" in platform_copy["source_disclosure"]
        assert "AI 辅助整理" in platform_copy["ai_disclosure"]
        assert "Manual publish only" in "\n".join(platform_copy["manual_publish_checklist"])

    qa = json.loads((output_dir / "qa_report.json").read_text(encoding="utf-8"))
    assert qa["duration_seconds"] > 0
    assert qa["file_size"] > 0
    assert qa["platform_fit"]["youtube_shorts"]["warnings"] or qa["platform_fit"]["youtube_shorts"]["passed"]

    get_response = client.get(f"/briefs/{brief['id']}/platform-package")
    assert get_response.status_code == 200
    assert set(get_response.json()["platform_copies"]) == {"bilibili", "xiaohongshu", "douyin", "youtube_shorts"}

    download_response = client.get(f"/briefs/{brief['id']}/platform-package/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(download_response.content)) as archive:
        names = set(archive.namelist())
        assert {"bilibili.json", "xiaohongshu.json", "douyin.json", "youtube_shorts.json"}.issubset(names)
        assert "final_video.mp4" in names
        assert "manual publish only" in archive.read("README_PLATFORM_PACKAGE.md").decode("utf-8").lower()

    assert Path(final_payload["video_path"]).exists()


def test_video_qa_analyzer_detects_h264_aac_mp4(client):
    _, final_payload = generate_approved_final_video(client)
    profiles = {
        "youtube_shorts": {
            "preferred_aspect_ratio": ["9:16"],
            "preferred_duration_min": 15,
            "preferred_duration_max": 60,
        }
    }
    report = VideoQAAnalyzer().analyze(final_payload["video_path"], profiles)
    assert report["video_codec"] == "h264"
    assert report["audio_codec"] == "aac"
    assert report["has_video"] is True
    assert report["has_audio"] is True


def test_copy_checker_blocks_clickbait_and_requires_sources_ai_disclosure():
    checker = ComplianceCopyChecker()
    bad_copy = {
        "bilibili": {
            "title_options": ["震惊：彻底完了"],
            "description": "No source and no disclosure.",
            "pinned_comment": "",
            "tags": [],
            "source_disclosure": "",
            "ai_disclosure": "",
            "manual_publish_checklist": ["Manual publish only: checked"],
        }
    }
    report = checker.check_all(bad_copy)
    assert report["overall_status"] == "blocked"
    errors = report["platforms"]["bilibili"]["blocking_errors"]
    assert "no_clickbait_extreme_terms" in errors
    assert "sources_present" in errors
    assert "ai_disclosure_present" in errors


def test_generated_copy_contains_manual_publish_only(client):
    brief, _ = generate_approved_final_video(client)
    response = client.post(f"/briefs/{brief['id']}/platform-package")
    assert response.status_code == 200
    copies = response.json()["platform_copies"]
    for payload in copies.values():
        text = json.dumps(payload, ensure_ascii=False)
        assert "Manual publish only" in text
        assert "AI 辅助整理" in text
        assert "Sources:" in text


def test_daily_dry_run_succeeds(tmp_path):
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path / 'dry_run.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "app.jobs.daily_brief", "--dry-run"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["brief_id"] >= 1
    assert payload["status"] in {"needs_review", "blocked"}
    assert payload["top_posts"]
    assert payload["safety_status"] in {"passed", "warning", "blocked"}
    assert payload["exported"] is False
    assert payload["published"] is False


def test_manual_evidence_attach(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief)
    response = client.post(
        f"/claims/{claim['id']}/evidence/manual",
        json={
            "source_name": "Manual official source",
            "source_url": "https://example.org/evidence/manual-001",
            "archive_url": "https://example.org/evidence/archive/manual-001",
            "publisher_type": "official",
            "reliability_tier": "high",
            "terms_status": "allowed",
            "excerpt": "Manual evidence excerpt supports the reviewed public claim.",
            "summary": "Manual source summary.",
            "supports_claim": "supports",
            "confidence": 0.9,
            "reviewer_note": "Editor attached manual evidence.",
        },
    )
    assert response.status_code == 200
    pack = response.json()
    assert pack["evidence_count"] == 1
    assert pack["verdict"] == "confirmed"
    assert pack["evidence_items"][0]["source"]["reliability_tier"] == "high"


def test_blocked_evidence_domain_rejected(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief)
    response = client.post(
        f"/claims/{claim['id']}/evidence/manual",
        json={
            "source_name": "Blocked direct source",
            "source_url": "https://truthsocial.com/@sample/posts/1",
            "excerpt": "Blocked direct-domain evidence excerpt.",
            "supports_claim": "supports",
        },
    )
    assert response.status_code == 409
    assert "Blocked evidence source domain" in response.json()["detail"]


def test_unsupported_factual_claim_creates_insufficient_pack(client):
    brief = generate_sample_brief(client)
    factual = first_claim(brief, "fact")
    response = client.get(f"/claims/{factual['id']}/evidence-pack")
    assert response.status_code == 200
    pack = response.json()
    assert pack["status"] == "insufficient"
    assert pack["verdict"] == "unclear"
    assert pack["evidence_count"] == 0


def test_opinion_claim_no_evidence_required(client):
    brief = generate_sample_brief(client)
    opinion = first_claim(brief, "opinion")
    response = client.get(f"/claims/{opinion['id']}/evidence-pack")
    assert response.status_code == 200
    pack = response.json()
    assert pack["status"] == "sufficient"
    assert pack["verdict"] == "opinion"
    assert pack["evidence_count"] == 0


def test_accusation_without_evidence_blocks_safety(client, tmp_path):
    unsafe_sample = tmp_path / "unsafe_evidence_sample.json"
    unsafe_sample.write_text(
        json.dumps(
            {
                "sample_data": True,
                "source": {
                    "name": "unsafe-evidence-sample",
                    "base_url": "https://example.org/unsafe-evidence",
                    "public_archive_url": "https://example.org/unsafe-evidence",
                    "direct_truth_social_scrape": False,
                },
                "posts": [
                    {
                        "post_id": "sample-unsafe-evidence-001",
                        "published_at": "2026-06-10T13:00:00Z",
                        "source_url": "https://example.org/archive/sample-unsafe-evidence-001",
                        "text": "SAMPLE FAKE POST: A public figure accuse opponents of illegal conduct without evidence.",
                        "short_excerpt": "SAMPLE FAKE POST: A fictional accusation without evidence.",
                        "summary": "A fictional public post accuse opponents of illegal conduct without evidence.",
                        "topic": "sample accusation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert client.post("/ingest/manual", json={"path": str(unsafe_sample)}).status_code == 200
    brief = client.post("/briefs/generate", json={"limit": 3}).json()
    assert brief["status"] == "blocked"
    assert any(rule["rule_id"] == "high_risk_claims_have_evidence" and not rule["passed"] for rule in brief["safety_review"]["rules"])


def test_disputed_evidence_creates_disputed_verdict(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief)
    response = client.post(
        f"/claims/{claim['id']}/evidence/manual",
        json={
            "source_name": "Contradicting source",
            "source_url": "https://example.org/evidence/disputed-001",
            "publisher_type": "government",
            "reliability_tier": "high",
            "terms_status": "allowed",
            "excerpt": "Manual evidence excerpt contradicts the reviewed claim.",
            "summary": "Contradicting source summary.",
            "supports_claim": "contradicts",
            "confidence": 0.85,
            "reviewer_note": "Contradiction found.",
        },
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == "disputed"
    assert response.json()["status"] == "needs_review"


def test_evidence_report_generated_and_endpoint_works(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief)
    attach = client.post(
        f"/claims/{claim['id']}/evidence/from-json",
        json={"path": "data/sample_evidence.json"},
    )
    assert attach.status_code == 200
    response = client.post(f"/briefs/{brief['id']}/evidence-pack/generate")
    assert response.status_code == 200
    payload = response.json()
    output_dir = Path(payload["report"]["output_dir"])
    assert (output_dir / "evidence_report.json").exists()
    assert (output_dir / "evidence_report.md").exists()
    assert (output_dir / "claims_matrix.csv").exists()
    assert (output_dir / "sources.json").exists()
    assert (output_dir / "README_EVIDENCE.md").exists()

    get_response = client.get(f"/briefs/{brief['id']}/evidence-pack/report")
    assert get_response.status_code == 200
    assert get_response.json()["brief_id"] == brief["id"]


def test_mock_provider_blocked_in_production():
    registry = default_registry(environment="production")
    try:
        registry.get_provider("mock")
    except ValueError as exc:
        assert "blocked in production" in str(exc)
    else:
        raise AssertionError("Mock evidence provider should be blocked in production")


def test_unknown_evidence_provider_blocked():
    registry = default_registry(environment="production")
    try:
        registry.get_provider("unknown")
    except KeyError as exc:
        assert "Unknown evidence provider" in str(exc)
    else:
        raise AssertionError("Unknown evidence provider should be blocked")


def test_external_search_disabled_by_default(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief)
    response = client.post(f"/claims/{claim['id']}/evidence/search", json={"provider": "controlled_search"})
    assert response.status_code == 409
    assert "External search is disabled" in response.json()["detail"]


def test_fake_search_blocked_in_production():
    registry = ExternalSearchProviderRegistry(production=True)
    try:
        registry.get_provider("fake_search")
    except ValueError as exc:
        assert "fake_search provider is blocked in production" in str(exc)
    else:
        raise AssertionError("fake_search should be blocked in production")


def test_unknown_external_search_provider_blocked():
    registry = ExternalSearchProviderRegistry(production=True)
    try:
        registry.get_provider("unknown")
    except KeyError as exc:
        assert "Unknown external search provider" in str(exc)
    else:
        raise AssertionError("Unknown external search provider should be blocked")


def test_search_creates_candidates_not_evidence_items(client, monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_SEARCH", "true")
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    before = client.get(f"/claims/{claim['id']}/evidence-pack").json()
    assert before["evidence_count"] == 0

    response = client.post(f"/claims/{claim['id']}/evidence/search", json={"provider": "controlled_search"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["status"] == "pending"

    candidates = client.get(f"/claims/{claim['id']}/evidence/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["count"] == 1
    after = client.get(f"/claims/{claim['id']}/evidence-pack").json()
    assert after["evidence_count"] == 0
    assert after["status"] == "insufficient"


def test_blocked_candidate_cannot_accept(client, monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_SEARCH", "true")
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    search = client.post(f"/claims/{claim['id']}/evidence/search", json={"provider": "controlled_search"}).json()
    candidate_id = search["candidates"][0]["id"]
    action = {"reviewer_name": "Editor A", "reviewer_note": "blocked candidate after review"}
    assert client.post(f"/evidence/candidates/{candidate_id}/block", json=action).status_code == 200
    accept = client.post(f"/evidence/candidates/{candidate_id}/accept", json={**action, "supports_claim": "supports", "confidence": 0.8})
    assert accept.status_code == 409
    assert "Blocked evidence candidate" in accept.json()["detail"]


def test_accept_requires_reviewer_note_and_creates_evidence_item(client, monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_SEARCH", "true")
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    search = client.post(f"/claims/{claim['id']}/evidence/search", json={"provider": "controlled_search"}).json()
    candidate_id = search["candidates"][0]["id"]

    missing = client.post(f"/evidence/candidates/{candidate_id}/accept", json={"reviewer_name": "Editor A"})
    assert missing.status_code == 422

    accepted = client.post(
        f"/evidence/candidates/{candidate_id}/accept",
        json={"reviewer_name": "Editor A", "reviewer_note": "accepted after source review", "supports_claim": "supports", "confidence": 0.8},
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["candidate"]["status"] == "accepted"
    assert payload["evidence_pack"]["evidence_count"] == 1
    assert payload["evidence_pack"]["verdict"] == "confirmed"


def test_query_builder_neutralizes_accusation_wording():
    claim = Claim(id=1, post_id=1, claim_text="A public figure accuse opponents of illegal crime", claim_type="accusation", requires_fact_check=True)
    queries = EvidenceQueryBuilder().build(claim)
    combined = " ".join(queries).lower()
    assert "neutral verification" in combined
    assert "claim about" in combined
    assert "legal status" in combined or "legal allegation" in combined
    assert "accuse opponents" not in combined


def test_pack_stays_insufficient_until_candidate_accepted(client, monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_SEARCH", "true")
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    search = client.post(f"/claims/{claim['id']}/evidence/search", json={"provider": "controlled_search"}).json()
    candidate_id = search["candidates"][0]["id"]
    pack = client.get(f"/claims/{claim['id']}/evidence-pack").json()
    assert pack["status"] == "insufficient"
    assert pack["evidence_count"] == 0
    client.post(
        f"/evidence/candidates/{candidate_id}/accept",
        json={"reviewer_name": "Editor A", "reviewer_note": "accepted after review", "supports_claim": "supports", "confidence": 0.8},
    )
    updated = client.get(f"/claims/{claim['id']}/evidence-pack").json()
    assert updated["evidence_count"] == 1


def _seed_post(db, *, promoted: bool, sample: bool = False, post_id: str = "prod-post-001"):
    source = Source(
        name=f"prod-source-{post_id}",
        kind="manual_url",
        base_url="https://example.org/prod",
        terms_safe=True,
        metadata_json={"manual_input": True, "sample_data": sample},
    )
    db.add(source)
    db.flush()
    policy = {"allowed": True, "evidence": {"sample_data": sample}}
    if promoted:
        policy["human_source_review_status"] = "promoted"
    post = Post(
        source_id=source.id,
        post_id=post_id,
        published_at=datetime.now(timezone.utc),
        source_url=f"https://example.org/archive/{post_id}",
        short_excerpt="A reviewed public source says official figures should be checked.",
        summary="A reviewed public source says official figures should be checked.",
        topic="production policy",
        text_hash=f"hash-{post_id}",
        source_review_required=not promoted,
        source_policy=policy,
    )
    db.add(post)
    db.commit()
    return post


def _patch_production_job_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(production_daily_run, "engine", engine)
    monkeypatch.setattr(production_daily_run, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def test_production_mode_blocks_sample_data_unless_explicit_test_mode(monkeypatch, tmp_path):
    SessionLocal = _patch_production_job_db(monkeypatch)
    db = SessionLocal()
    try:
        _seed_post(db, promoted=False, sample=True, post_id="sample-prod-blocked")
    finally:
        db.close()
    policy = ProductionPolicy()
    assert policy.sample_data_allowed() is False
    assert policy.sample_data_allowed(explicit_test_mode=True) is True

    report = production_daily_run.run(dry_run=False, output_root=tmp_path)
    assert report["source_summary"]["promoted_posts"] == 0
    assert report["source_summary"]["sample_posts_blocked"] == 1
    assert report["brief_summary"] is None


def test_production_run_creates_run_report_and_does_not_auto_approve(monkeypatch, tmp_path):
    SessionLocal = _patch_production_job_db(monkeypatch)
    db = SessionLocal()
    try:
        _seed_post(db, promoted=True, post_id="promoted-prod-001")
    finally:
        db.close()

    report = production_daily_run.run(dry_run=False, output_root=tmp_path)
    run_dir = tmp_path / datetime.now().date().isoformat()
    assert (run_dir / "run_report.json").exists()
    assert (run_dir / "source_summary.json").exists()
    assert (run_dir / "topic_summary.json").exists()
    assert (run_dir / "brief_summary.json").exists()
    assert (run_dir / "blocking_reasons.json").exists()
    assert (run_dir / "README_RUN.md").exists()
    assert report["automatic_approval"] is False
    assert report["automatic_render"] is False
    assert report["automatic_publish"] is False
    assert report["topic_summary"]["auto_selected"] is False
    assert report["brief_summary"] is None


def test_ops_summary_returns_counts(client):
    brief = generate_sample_brief(client)
    response = client.get("/ops/summary")
    assert response.status_code == 200
    payload = response.json()
    assert "pending_source_reviews" in payload
    assert "briefs_needs_review" in payload
    assert payload["briefs_needs_review"] >= 1
    assert brief["id"] >= 1


def test_blocking_reason_aggregator_works(client, tmp_path):
    unsafe_sample = tmp_path / "unsafe_ops_sample.json"
    unsafe_sample.write_text(
        json.dumps(
            {
                "sample_data": True,
                "source": {
                    "name": "unsafe-ops-sample",
                    "base_url": "https://example.org/unsafe-ops",
                    "public_archive_url": "https://example.org/unsafe-ops",
                    "direct_truth_social_scrape": False,
                },
                "posts": [
                    {
                        "post_id": "sample-unsafe-ops-001",
                        "published_at": "2026-06-10T13:00:00Z",
                        "source_url": "https://example.org/archive/sample-unsafe-ops-001",
                        "text": "SAMPLE FAKE POST: A public figure accuse opponents of illegal conduct without evidence.",
                        "short_excerpt": "SAMPLE FAKE POST: A fictional accusation without evidence.",
                        "summary": "A fictional public post accuse opponents of illegal conduct without evidence.",
                        "topic": "sample accusation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert client.post("/ingest/manual", json={"path": str(unsafe_sample)}).status_code == 200
    assert client.post("/briefs/generate", json={"limit": 3}).status_code == 200
    response = client.get("/ops/blocking-reasons")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_blocking_reasons"] > 0
    assert "safety blocked" in payload["by_category"] or "evidence insufficient" in payload["by_category"]


def test_audit_export_returns_csv_and_json(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/manual/audit-export",
            "archive_url": "https://example.org/archive/audit-export",
            "source_name": "audit-export-source",
            "short_excerpt": "Audit export source review item.",
        },
    )
    item = response.json()
    action = {"reviewer_name": "Editor A", "reviewer_note": "audit export check"}
    assert client.post(f"/sources/review-queue/{item['id']}/approve", json=action).status_code == 200

    json_response = client.get("/ops/audit-log/export?format=json")
    assert json_response.status_code == 200
    assert any(log["action"] == "source_approved" for log in json_response.json()["audit_logs"])

    csv_response = client.get("/ops/audit-log/export?format=csv")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert b"source_approved" in csv_response.content


def test_cleanup_dry_run_does_not_delete_and_run_deletes_old_export_fixture(tmp_path):
    old_dir = tmp_path / "render_packages" / "brief_999"
    old_dir.mkdir(parents=True)
    (old_dir / "artifact.txt").write_text("old", encoding="utf-8")
    old_time = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
    os.utime(old_dir, (old_time, old_time))

    dry = cleanup(dry_run=True, exports_dir=tmp_path, now=datetime.now(timezone.utc))
    assert dry["candidates"]
    assert old_dir.exists()

    ran = cleanup(dry_run=False, exports_dir=tmp_path, now=datetime.now(timezone.utc))
    assert str(old_dir) in ran["deleted"]
    assert not old_dir.exists()


def test_generate_topics_from_promoted_posts(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/topic-001",
        excerpt="A reviewed public source describes a policy-related public post for neutral analysis.",
    )
    response = client.post("/editorial/topics/generate")
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 1
    assert payload["report"]["auto_selected"] is False
    assert payload["topics"][0]["selected_post_ids"]


def test_similar_topics_merge(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/topic-merge-001",
        excerpt="A reviewed public source describes official figures that should be checked.",
    )
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/topic-merge-002",
        excerpt="Another reviewed public source describes related official figures for checking.",
    )
    response = client.post("/editorial/topics/generate")
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 1
    assert len(payload["topics"][0]["selected_post_ids"]) == 2


def test_topic_needing_evidence_cannot_generate_brief(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/high-risk-001",
        excerpt="A reviewed public source includes an accusation about illegal election fraud that requires verification.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    assert topic["status"] == "needs_more_evidence"
    response = client.post(
        f"/editorial/topics/{topic['id']}/generate-brief",
        json={"reviewer_name": "Editor A", "reviewer_note": "attempt blocked by evidence gate"},
    )
    assert response.status_code == 409


def test_rejected_topic_cannot_generate_brief(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/reject-001",
        excerpt="A reviewed public source describes a neutral policy topic.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    reject = client.post(
        f"/editorial/topics/{topic['id']}/reject",
        json={"reviewer_name": "Editor A", "reviewer_note": "not useful for today's brief"},
    )
    assert reject.status_code == 200
    response = client.post(
        f"/editorial/topics/{topic['id']}/generate-brief",
        json={"reviewer_name": "Editor A", "reviewer_note": "should stay blocked"},
    )
    assert response.status_code == 409


def test_selected_topic_can_generate_brief(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/select-001",
        excerpt="A reviewed public source describes a public post about policy messaging for neutral analysis.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    select = client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor A", "reviewer_note": "selected for neutral daily brief"},
    )
    assert select.status_code == 200
    response = client.post(
        f"/editorial/topics/{topic['id']}/generate-brief",
        json={"reviewer_name": "Editor A", "reviewer_note": "generate from selected editorial topic"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata_json"]["topic_id"] == topic["id"]
    assert payload["metadata_json"]["generated_from_editorial_calendar"] is True


def test_schedule_requires_reviewer_note(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/schedule-001",
        excerpt="A reviewed public source describes a neutral daily topic.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor A", "reviewer_note": "selected for schedule"},
    )
    missing_note = client.post(
        "/editorial/calendar/schedule",
        json={"topic_id": topic["id"], "reviewer_name": "Editor A"},
    )
    assert missing_note.status_code == 422
    scheduled = client.post(
        "/editorial/calendar/schedule",
        json={"topic_id": topic["id"], "reviewer_name": "Editor A", "reviewer_note": "scheduled with human approval"},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "ready_for_brief"


def test_production_run_generates_topics_without_auto_select(monkeypatch, tmp_path):
    SessionLocal = _patch_production_job_db(monkeypatch)
    db = SessionLocal()
    try:
        _seed_post(db, promoted=True, post_id="promoted-topic-001")
    finally:
        db.close()

    report = production_daily_run.run(dry_run=False, output_root=tmp_path)
    run_dir = tmp_path / datetime.now().date().isoformat()
    assert (run_dir / "topic_selection_report.json").exists()
    assert (run_dir / "topic_summary.json").exists()
    assert report["brief_summary"] is None
    assert report["topic_summary"]["topic_count"] == 1
    assert report["topic_summary"]["auto_selected"] is False
    db = SessionLocal()
    try:
        topics = list(db.query(EditorialTopic).all())
        assert len(topics) == 1
        assert topics[0].status in {"pending", "needs_more_evidence"}
    finally:
        db.close()


def test_ops_summary_includes_editorial_counts(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/ops-001",
        excerpt="A reviewed public source describes a neutral ops dashboard topic.",
    )
    client.post("/editorial/topics/generate")
    response = client.get("/ops/summary")
    assert response.status_code == 200
    payload = response.json()
    assert "pending_topics" in payload
    assert "scheduled_topics_today" in payload
    assert "briefs_generated_from_calendar" in payload


def test_audit_log_records_topic_actions(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/audit-001",
        excerpt="A reviewed public source describes a neutral audit topic.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor A", "reviewer_note": "selected for audit"},
    )
    client.post(
        "/editorial/calendar/schedule",
        json={"topic_id": topic["id"], "reviewer_name": "Editor A", "reviewer_note": "calendar audit"},
    )
    response = client.get("/ops/audit-log/export?format=json")
    actions = {log["action"] for log in response.json()["audit_logs"]}
    assert {"topic_generated", "topic_selected", "calendar_scheduled"}.issubset(actions)


def test_next_action_blocks_render_before_approval(client):
    brief = generate_sample_brief(client)
    response = client.get(f"/editorial/briefs/{brief['id']}/next-action")
    assert response.status_code == 200
    payload = response.json()
    assert payload["next_action"] == "await_human_approval"
    assert "generate_render_package" in payload["blocked_actions"]


def test_next_action_blocks_final_video_when_voice_qa_blocked(client):
    brief = generate_sample_brief(client)
    assert client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor A", "reviewer_note": "approved before voice qa block test"},
    ).status_code == 200
    assert client.post(f"/briefs/{brief['id']}/render-package").status_code == 200
    assert client.post(f"/briefs/{brief['id']}/tts/generate", json={"provider": "local_stub", "voice": "neutral_zh"}).status_code == 200
    qa_path = Path("exports/tts") / f"brief_{brief['id']}" / "voice_qa_report.json"
    qa_path.write_text(json.dumps({"status": "blocked", "blocking_reasons": ["test_voice_policy_block"]}, ensure_ascii=False), encoding="utf-8")
    response = client.get(f"/editorial/briefs/{brief['id']}/next-action")
    assert response.status_code == 200
    payload = response.json()
    assert payload["next_action"] == "blocked"
    assert "voice_qa_blocked" in payload["blocking_reasons"]
    assert "generate_final_video" in payload["blocked_actions"]


def test_run_next_step_cannot_skip_evidence_gate(client):
    _, brief = generate_selected_topic_brief(client, source_url="https://example.org/editorial/evidence-gate")
    override = app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        for claim in brief["claims"]:
            for pack in db.query(EvidencePack).filter(EvidencePack.claim_id == claim["id"]).all():
                db.delete(pack)
        db.commit()
    finally:
        db.close()
        db_gen.close()
    response = client.post(f"/editorial/briefs/{brief['id']}/run-next-step", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executed_action"] == "generate_evidence_pack"
    assert payload["next_action"]["next_action"] == "await_human_approval"


def test_run_next_step_cannot_auto_approve(client):
    _, brief = generate_selected_topic_brief(client, source_url="https://example.org/editorial/no-auto-approve")
    response = client.post(
        f"/editorial/briefs/{brief['id']}/run-next-step",
        json={"reviewer_name": "Editor A", "reviewer_note": "should not auto approve"},
    )
    assert response.status_code == 409
    assert "cannot auto approve" in str(response.json()["detail"])


def test_production_console_summary_returns_queues(client):
    _, brief = generate_selected_topic_brief(client, source_url="https://example.org/editorial/console-summary")
    response = client.get("/editorial/console/summary")
    assert response.status_code == 200
    payload = response.json()
    assert "source_review_queue" in payload["queues"]
    assert "editorial_topics" in payload["queues"]
    assert "briefs_awaiting_approval" in payload["queues"]
    assert str(brief["id"]) in payload["brief_next_actions"]
    page = client.get(f"/editorial/briefs/{brief['id']}/production-console")
    assert page.status_code == 200
    assert "Manual publish only" in page.text


def test_timeline_includes_audit_events(client):
    topic, brief = generate_selected_topic_brief(client, source_url="https://example.org/editorial/timeline")
    brief_timeline = client.get(f"/editorial/briefs/{brief['id']}/timeline")
    assert brief_timeline.status_code == 200
    brief_events = {event["event_type"] for event in brief_timeline.json()["timeline"]}
    assert "brief_generated_from_topic" in brief_events
    topic_timeline = client.get(f"/editorial/topics/{topic['id']}/timeline")
    assert topic_timeline.status_code == 200
    topic_events = {event["event_type"] for event in topic_timeline.json()["timeline"]}
    assert {"topic_generated", "topic_selected", "brief_generated_from_topic"} & topic_events


def test_start_production_creates_brief_only_for_selected_or_scheduled_topic(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/start-production",
        excerpt="A reviewed public source describes a neutral start production topic.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    pending = client.post(
        f"/editorial/topics/{topic['id']}/start-production",
        json={"reviewer_name": "Editor A", "reviewer_note": "should be blocked while pending"},
    )
    assert pending.status_code == 409
    client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor A", "reviewer_note": "selected for start production"},
    )
    started = client.post(
        f"/editorial/topics/{topic['id']}/start-production",
        json={"reviewer_name": "Editor A", "reviewer_note": "start selected production"},
    )
    assert started.status_code == 200
    assert started.json()["metadata_json"]["topic_id"] == topic["id"]


def test_rejected_topic_cannot_start_production(client):
    promote_manual_source(
        client,
        source_url="https://example.org/editorial/rejected-start",
        excerpt="A reviewed public source describes a neutral rejected production topic.",
    )
    topic = client.post("/editorial/topics/generate").json()["topics"][0]
    client.post(
        f"/editorial/topics/{topic['id']}/reject",
        json={"reviewer_name": "Editor A", "reviewer_note": "reject before start production"},
    )
    response = client.post(
        f"/editorial/topics/{topic['id']}/start-production",
        json={"reviewer_name": "Editor A", "reviewer_note": "should not start rejected topic"},
    )
    assert response.status_code == 409


def test_manual_publish_only_remains_enforced(client):
    brief, _ = generate_approved_final_video(client)
    platform = client.post(f"/briefs/{brief['id']}/platform-package")
    assert platform.status_code == 200
    response = client.post(f"/editorial/briefs/{brief['id']}/run-next-step", json={})
    assert response.status_code == 409
    assert "Manual publish only" in str(response.json()["detail"])


def test_viewer_cannot_mutate(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/roles/viewer-source",
            "archive_url": "https://example.org/roles/viewer-source/archive",
            "source_name": "viewer-source",
            "short_excerpt": "Viewer should not be able to mutate.",
        },
        headers=role_headers("view-only", "viewer"),
    )
    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


def test_editor_can_select_topic_but_cannot_approve_brief(client):
    promote_manual_source(
        client,
        source_url="https://example.org/roles/editor-topic",
        excerpt="A reviewed public source describes an editor-selectable topic.",
    )
    topic = client.post("/editorial/topics/generate", headers=role_headers("ed", "editor")).json()["topics"][0]
    selected = client.post(
        f"/editorial/topics/{topic['id']}/select",
        json={"reviewer_name": "Editor", "reviewer_note": "editor selection allowed"},
        headers=role_headers("ed", "editor"),
    )
    assert selected.status_code == 200
    brief = generate_sample_brief(client)
    denied = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Editor", "reviewer_note": "editor cannot approve"},
        headers=role_headers("ed", "editor"),
    )
    assert denied.status_code == 403


def test_reviewer_can_approve_source_evidence_and_brief(client):
    ingest = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/roles/reviewer-source",
            "archive_url": "https://example.org/roles/reviewer-source/archive",
            "source_name": "reviewer-source",
            "short_excerpt": "Reviewer source approval target.",
        },
    )
    item_id = ingest.json()["id"]
    approved_source = client.post(
        f"/sources/review-queue/{item_id}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "reviewer can approve source"},
        headers=role_headers("rev", "reviewer"),
    )
    assert approved_source.status_code == 200

    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    evidence = client.post(
        f"/claims/{claim['id']}/evidence/manual",
        json={
            "source_name": "Reviewer evidence",
            "source_url": "https://example.org/roles/evidence",
            "publisher_type": "official",
            "reliability_tier": "high",
            "terms_status": "allowed",
            "excerpt": "Short reviewed evidence excerpt.",
            "supports_claim": "supports",
            "confidence": 0.8,
            "reviewer_note": "reviewer attached evidence",
        },
        headers=role_headers("rev", "reviewer"),
    )
    assert evidence.status_code == 200
    approved_brief = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "reviewer can approve brief"},
        headers=role_headers("rev", "reviewer"),
    )
    assert approved_brief.status_code == 200


def test_producer_can_render_after_approval_but_cannot_approve(client):
    brief = generate_sample_brief(client)
    denied = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Producer", "reviewer_note": "producer cannot approve"},
        headers=role_headers("prod", "producer"),
    )
    assert denied.status_code == 403
    assert client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "approved for producer render"},
        headers=role_headers("rev", "reviewer"),
    ).status_code == 200
    rendered = client.post(f"/briefs/{brief['id']}/render-package", headers=role_headers("prod", "producer"))
    assert rendered.status_code == 200


def test_admin_can_export_audit(client):
    response = client.get("/ops/audit-log/export?format=json", headers=role_headers("admin", "admin"))
    assert response.status_code == 200
    denied = client.get("/ops/audit-log/export?format=json", headers=role_headers("viewer", "viewer"))
    assert denied.status_code == 403


def test_same_user_cannot_create_and_approve_brief_when_policy_enabled(client):
    assert client.post("/ingest/manual", json={"path": "data/sample_posts.json"}, headers=role_headers("sam", "editor")).status_code == 200
    brief = client.post("/briefs/generate", json={"limit": 3}, headers=role_headers("sam", "editor")).json()
    denied = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Sam", "reviewer_note": "same user should be blocked"},
        headers=role_headers("sam", "reviewer"),
    )
    assert denied.status_code == 403
    assert "same_user" in denied.json()["detail"]


def test_run_next_step_respects_producer_role(client):
    brief = generate_sample_brief(client)
    assert client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "approved for producer next step"},
        headers=role_headers("rev", "reviewer"),
    ).status_code == 200
    denied = client.post(f"/editorial/briefs/{brief['id']}/run-next-step", json={}, headers=role_headers("ed", "editor"))
    assert denied.status_code == 403
    allowed = client.post(f"/editorial/briefs/{brief['id']}/run-next-step", json={}, headers=role_headers("prod", "producer"))
    assert allowed.status_code == 200
    assert allowed.json()["executed_action"] == "generate_render_package"


def test_denied_action_returns_403(client):
    response = client.post("/editorial/topics/generate", headers=role_headers("viewer", "viewer"))
    assert response.status_code == 403


def test_approval_record_created(client):
    brief = generate_sample_brief(client)
    approved = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "approval record expected"},
        headers=role_headers("record-reviewer", "reviewer"),
    )
    assert approved.status_code == 200
    override = app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        records = db.query(ApprovalRecord).filter(ApprovalRecord.entity_type == "brief", ApprovalRecord.entity_id == brief["id"]).all()
        assert any(record.action == "brief_approved" and record.actor == "record-reviewer" for record in records)
    finally:
        db.close()
        db_gen.close()


def test_production_cannot_start_with_header_stub(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "header_stub")
    monkeypatch.delenv("ALLOW_INSECURE_AUTH_STUB", raising=False)
    try:
        load_environment()
    except RuntimeError as exc:
        assert "header_stub" in str(exc)
    else:
        raise AssertionError("production header_stub should be rejected")


def test_staging_warns_or_blocks_insecure_header_stub(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AUTH_MODE", "header_stub")
    monkeypatch.setenv("ALLOW_INSECURE_AUTH_STUB", "true")
    try:
        load_environment()
    except RuntimeError as exc:
        assert "local/test" in str(exc)
    else:
        raise AssertionError("staging header_stub should be rejected in Phase 2.4")


def test_health_security_reports_manual_publish_only(client):
    response = client.get("/health/security")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manual_publish_only"] is True
    assert payload["platform_publish_api_enabled"] is False
    assert payload["truth_social_direct_scraper_enabled"] is False


def test_viewer_cannot_access_permissions_matrix(client):
    response = client.get("/admin/permissions/matrix", headers=role_headers("viewer", "viewer"))
    assert response.status_code == 403


def test_admin_can_access_permissions_matrix(client):
    response = client.get("/admin/permissions/matrix", headers=role_headers("admin", "admin"))
    assert response.status_code == 200
    matrix = response.json()["matrix"]
    assert matrix["admin"]["approve_brief"] is True
    assert matrix["editor"]["select_topic"] is True
    assert matrix["editor"]["approve_brief"] is False
    assert matrix["reviewer"]["approve_brief"] is True
    assert matrix["producer"]["render"] is True
    assert matrix["producer"]["approve_brief"] is False
    assert matrix["viewer"]["generate_brief"] is False
    assert Path(response.json()["docs_path"]).exists()


def test_request_id_appears_in_write_response_and_audit_log(client):
    request_id = "test-request-id-phase-23"
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase23/request-id",
            "archive_url": "https://example.org/phase23/request-id/archive",
            "source_name": "phase23-request",
            "short_excerpt": "Request id audit test.",
        },
        headers={**role_headers("editor", "editor"), "X-Request-ID": request_id},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    audit = client.get("/ops/audit-log/export?format=json", headers=role_headers("admin", "admin")).json()["audit_logs"]
    assert any(log["request_id"] == request_id and log["after_state_hash"] for log in audit)


def test_audit_log_cannot_be_modified_or_deleted_through_api(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase23/audit-immutable",
            "archive_url": "https://example.org/phase23/audit-immutable/archive",
            "source_name": "phase23-audit",
            "short_excerpt": "Audit immutable test.",
        },
        headers=role_headers("editor", "editor"),
    )
    assert response.status_code == 200
    audit = client.get("/ops/audit-log/export?format=json", headers=role_headers("admin", "admin")).json()["audit_logs"][0]
    assert client.get(f"/admin/audit/{audit['id']}", headers=role_headers("admin", "admin")).status_code == 200
    assert client.put(f"/admin/audit/{audit['id']}", json={}, headers=role_headers("admin", "admin")).status_code == 405
    assert client.delete(f"/admin/audit/{audit['id']}", headers=role_headers("admin", "admin")).status_code == 405


def test_trace_manifest_exists_in_export_render_final_platform_packages(client):
    brief, _ = generate_approved_final_video(client)
    brief_id = brief["id"]
    render = client.get(f"/briefs/{brief_id}/render-package").json()
    assert (Path(render["output_dir"]) / "trace_manifest.json").exists()
    final = client.get(f"/briefs/{brief_id}/final-video").json()
    assert (Path(final["report_path"]).parent / "trace_manifest.json").exists()
    platform = client.post(f"/briefs/{brief_id}/platform-package")
    assert platform.status_code == 200
    platform_payload = platform.json()
    assert (Path(platform_payload["output_dir"]) / "trace_manifest.json").exists()
    with ZipFile(platform_payload["package_path"]) as archive:
        assert "trace_manifest.json" in archive.namelist()
    export_response = client.get(f"/briefs/{brief_id}/export-package")
    assert export_response.status_code == 200
    with ZipFile(io.BytesIO(export_response.content)) as archive:
        assert "trace_manifest.json" in archive.namelist()
        trace = json.loads(archive.read("trace_manifest.json"))
        assert trace["brief_id"] == brief_id
        assert trace["manual_publish_only"] is True


def test_invariant_checker_passes_normal_flow(client):
    brief, _ = generate_approved_final_video(client)
    assert client.post(f"/briefs/{brief['id']}/platform-package").status_code == 200
    response = client.get("/admin/invariants", headers=role_headers("admin", "admin"))
    assert response.status_code == 200
    assert response.json()["overall_status"] == "passed"


def test_invariant_checker_catches_unsafe_mocked_state(client):
    brief = generate_sample_brief(client)
    override = app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        db.add(RenderPackage(brief_id=brief["id"], status="generated", output_dir="unsafe", manifest_path="unsafe/manifest.json"))
        db.commit()
    finally:
        db.close()
        db_gen.close()
    response = client.get("/admin/invariants", headers=role_headers("admin", "admin"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "failed"
    assert any(item["id"] == "unapproved_brief_cannot_render" and not item["passed"] for item in payload["checks"])


def test_staging_smoke_runs_successfully_in_test_mode(tmp_path):
    output = tmp_path / "staging_smoke_report.json"
    result = subprocess.run(
        [sys.executable, "scripts/staging_smoke.py", "--base-url", "testclient://local", "--test-mode", "--output", str(output)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["manual_publish_only"] is True
    assert report["platform_action"] == "generate_platform_package"


def test_header_stub_creates_current_user_context_in_local_test(client):
    response = client.get("/workspaces/current", headers=role_headers("phase24-editor", "editor"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_user"]["username"] == "phase24-editor"
    assert payload["current_user"]["role"] == "editor"
    assert payload["current_user"]["auth_mode"] == "header_stub"
    assert payload["current_user"]["is_stub"] is True
    assert payload["workspace"]["slug"] == "daily-truth-brief-dev"


def test_default_workspace_exists(client):
    response = client.get("/workspaces/current")
    assert response.status_code == 200
    workspace = response.json()["workspace"]
    assert workspace["slug"] == "daily-truth-brief-dev"
    override = app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        stored = db.query(Workspace).filter(Workspace.slug == "daily-truth-brief-dev").one()
        assert stored.status == "active"
    finally:
        db.close()
        db_gen.close()


def test_write_operation_records_workspace_id_in_audit(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase24/workspace-audit",
            "archive_url": "https://example.org/phase24/workspace-audit/archive",
            "source_name": "phase24-workspace-audit",
            "short_excerpt": "Workspace id audit test.",
        },
        headers={**role_headers("phase24-editor", "editor"), "X-Request-ID": "phase24-request"},
    )
    assert response.status_code == 200
    audit = client.get("/ops/audit-log/export?format=json", headers=role_headers("phase24-admin", "admin")).json()["audit_logs"]
    assert any(log["action"] == "ingest_manual_url" and log["workspace_id"] and log["request_id"] == "phase24-request" for log in audit)


def test_current_workspace_endpoint_works(client):
    response = client.get("/workspaces/current", headers=role_headers("workspace-viewer", "viewer"))
    assert response.status_code == 200
    assert response.json()["workspace"]["status"] == "active"


def test_viewer_cannot_create_invite(client):
    response = client.post(
        "/workspaces/current/invites",
        json={"email_or_name": "viewer-attempt", "role": "editor"},
        headers=role_headers("viewer", "viewer"),
    )
    assert response.status_code == 403


def test_admin_can_create_and_revoke_invite(client):
    create = client.post(
        "/workspaces/current/invites",
        json={"email_or_name": "new-reviewer@example.test", "role": "reviewer"},
        headers=role_headers("workspace-admin", "admin"),
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload["status"] == "pending"
    assert payload["role"] == "reviewer"
    revoke = client.post(
        f"/workspaces/current/invites/{payload['id']}/revoke",
        headers=role_headers("workspace-admin", "admin"),
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"


def test_admin_can_create_and_revoke_api_token(client):
    create = client.post(
        "/workspaces/current/api-tokens",
        json={"name": "staging-placeholder", "scopes": ["audit:read"]},
        headers=role_headers("workspace-admin", "admin"),
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload["status"] == "active"
    assert payload["token_auth_active"] is False
    revoke = client.post(
        f"/workspaces/current/api-tokens/{payload['id']}/revoke",
        headers=role_headers("workspace-admin", "admin"),
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"


def test_workspace_isolation_prevents_reading_other_workspace_resources(client):
    default_brief = generate_sample_brief(client)
    other_workspace_id = 999
    response = client.get(
        f"/briefs/{default_brief['id']}",
        headers={**role_headers("other-admin", "admin"), "X-Workspace-ID": str(other_workspace_id)},
    )
    assert response.status_code == 404


def test_trace_manifest_includes_workspace_id(client):
    brief, _ = generate_approved_final_video(client)
    export_response = client.get(f"/briefs/{brief['id']}/export-package")
    assert export_response.status_code == 200
    with ZipFile(io.BytesIO(export_response.content)) as archive:
        trace = json.loads(archive.read("trace_manifest.json"))
    assert trace["workspace_id"] == brief["metadata_json"]["workspace_id"]
    assert trace["workspace_slug"] == "daily-truth-brief-dev"


def test_approved_source_can_promote_to_evidence(client):
    response = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase25/evidence-source",
            "archive_url": "https://example.org/phase25/evidence-source/archive",
            "source_name": "phase25-evidence-source",
            "short_excerpt": "Reviewed source excerpt for evidence promotion.",
        },
    )
    item = response.json()
    assert client.post(
        f"/sources/review-queue/{item['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "approved source"},
    ).status_code == 200
    promoted = client.post(
        f"/sources/review-queue/{item['id']}/promote-to-evidence",
        json={"reviewer_name": "Reviewer", "reviewer_note": "promote evidence"},
    )
    assert promoted.status_code == 200
    evidence = promoted.json()["evidence_item"]
    assert evidence["source_review_item_id"] == item["id"]
    assert evidence["human_status"] == "approved"
    assert evidence["workspace_id"]


def test_pending_rejected_blocked_source_cannot_promote_to_evidence(client):
    pending = client.post(
        "/sources/ingest/manual-url",
        json={"source_url": "https://example.org/phase25/pending", "source_name": "pending", "short_excerpt": "Pending source."},
    ).json()
    denied = client.post(
        f"/sources/review-queue/{pending['id']}/promote-to-evidence",
        json={"reviewer_name": "Reviewer", "reviewer_note": "not approved"},
    )
    assert denied.status_code == 409

    rejected = client.post(
        "/sources/ingest/manual-url",
        json={"source_url": "https://example.org/phase25/rejected", "source_name": "rejected", "short_excerpt": "Rejected source."},
    ).json()
    assert client.post(
        f"/sources/review-queue/{rejected['id']}/reject",
        json={"reviewer_name": "Reviewer", "reviewer_note": "reject"},
    ).status_code == 200
    denied = client.post(
        f"/sources/review-queue/{rejected['id']}/promote-to-evidence",
        json={"reviewer_name": "Reviewer", "reviewer_note": "rejected"},
    )
    assert denied.status_code == 409

    blocked = client.post(
        "/sources/ingest/manual-url",
        json={"source_url": "https://truthsocial.com/@sample/posts/phase25", "source_name": "blocked", "short_excerpt": "Blocked direct source."},
    ).json()
    assert client.post(
        f"/sources/review-queue/{blocked['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "attempt"},
    ).status_code == 200
    denied = client.post(
        f"/sources/review-queue/{blocked['id']}/promote-to-evidence",
        json={"reviewer_name": "Reviewer", "reviewer_note": "blocked"},
    )
    assert denied.status_code == 409


def test_only_approved_evidence_can_link_to_claim(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    item = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase25/link-rejected",
            "archive_url": "https://example.org/phase25/link-rejected/archive",
            "source_name": "link-rejected",
            "short_excerpt": "Evidence that will be rejected.",
        },
    ).json()
    assert client.post(f"/sources/review-queue/{item['id']}/approve", json={"reviewer_name": "Reviewer", "reviewer_note": "approve"}).status_code == 200
    evidence = client.post(f"/sources/review-queue/{item['id']}/promote-to-evidence", json={"reviewer_name": "Reviewer", "reviewer_note": "promote"}).json()["evidence_item"]
    assert client.post(f"/evidence/{evidence['id']}/reject", json={"reviewer_name": "Reviewer", "reviewer_note": "reject evidence"}).status_code == 200
    link = client.post(
        f"/claims/{claim['id']}/evidence-links",
        json={"evidence_item_id": evidence["id"], "support_type": "supports", "confidence": "high"},
    )
    assert link.status_code == 409


def test_cross_workspace_evidence_link_blocked(client):
    brief = generate_sample_brief(client)
    claim = first_claim(brief, "fact")
    override = app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        other = Workspace(name="Other Workspace", slug="other-phase25", status="active")
        db.add(other)
        db.flush()
        evidence = EvidenceItem(
            workspace_id=other.id,
            evidence_type="manual_note",
            title="Other workspace evidence",
            source_name="other",
            source_url="https://example.org/other",
            excerpt="Other workspace excerpt.",
            summary="Other workspace summary.",
            reliability_score=80,
            terms_status="allowed",
            human_status="approved",
            created_by="other",
        )
        db.add(evidence)
        db.commit()
        evidence_id = evidence.id
    finally:
        db.close()
        db_gen.close()
    link = client.post(
        f"/claims/{claim['id']}/evidence-links",
        json={"evidence_item_id": evidence_id, "support_type": "supports", "confidence": "high"},
    )
    assert link.status_code == 404


def test_fact_claim_without_evidence_blocks_approval(client):
    post = promote_manual_source(
        client,
        source_url="https://example.org/phase25/no-evidence-fact",
        excerpt="A reviewed public source states a factual policy claim for gate testing.",
        source_name="phase25-no-evidence",
    )
    brief = client.post("/briefs/generate", json={"limit": 2, "post_ids": [post["id"]], "production_only": True}).json()
    assert brief["fact_check_quality_gate"]["status"] == "blocked"
    approval = client.post(f"/briefs/{brief['id']}/approve", json={"reviewer_name": "Reviewer", "reviewer_note": "should block"})
    assert approval.status_code == 409
    assert "Fact-check quality gate" in str(approval.json()["detail"])


def test_high_risk_claim_with_insufficient_evidence_blocks_approval(client):
    item = client.post(
        "/sources/ingest/manual-url",
        json={
            "source_url": "https://example.org/phase25/high-risk",
            "archive_url": "https://example.org/phase25/high-risk/archive",
            "source_name": "phase25-high-risk",
            "short_excerpt": "A public source accuse opponents of illegal election conduct.",
        },
    ).json()
    assert client.post(f"/sources/review-queue/{item['id']}/approve", json={"reviewer_name": "Reviewer", "reviewer_note": "approve"}).status_code == 200
    promoted = client.post(f"/sources/review-queue/{item['id']}/promote-to-post-and-evidence", json={"reviewer_name": "Reviewer", "reviewer_note": "promote"}).json()
    brief = client.post("/briefs/generate", json={"limit": 2, "post_ids": [promoted["post"]["id"]], "production_only": True}).json()
    claim = first_claim(brief, "accusation")
    link = client.post(
        f"/claims/{claim['id']}/evidence-links",
        json={"evidence_item_id": promoted["evidence_item"]["id"], "support_type": "supports", "confidence": "medium"},
    )
    assert link.status_code == 200
    refreshed = client.post(f"/briefs/{brief['id']}/evidence-pack/generate")
    assert refreshed.status_code == 200
    approval = client.post(f"/briefs/{brief['id']}/approve", json={"reviewer_name": "Reviewer", "reviewer_note": "insufficient high risk evidence"})
    assert approval.status_code == 409
    assert approval.json()["detail"]["fact_check_quality_gate"]["status"] == "blocked"


def test_opinion_claim_can_pass_without_evidence(client):
    post = promote_manual_source(
        client,
        source_url="https://example.org/phase25/opinion",
        excerpt="A reviewed public source says a court decision is important for public discussion.",
        source_name="phase25-opinion",
    )
    brief = client.post("/briefs/generate", json={"limit": 2, "post_ids": [post["id"]], "production_only": True}).json()
    assert first_claim(brief, "opinion")
    approval = client.post(f"/briefs/{brief['id']}/approve", json={"reviewer_name": "Reviewer", "reviewer_note": "opinion can pass"})
    assert approval.status_code == 200


def test_script_writer_does_not_assert_unsupported_claim_as_fact():
    script = ScriptWriter().write(
        [{"source_url": "https://example.org/source", "post_id": "p1", "topic": "test", "summary": "A factual claim."}],
        [{"claim_id": 1, "verdict": "unsupported"}],
    )
    assert "缺乏足够公开证据" in script["text"]
    assert "公开资料显示" not in script["text"]


def test_platform_package_includes_evidence_summary_and_gate_report(client):
    brief, _ = generate_approved_final_video(client)
    platform = client.post(f"/briefs/{brief['id']}/platform-package")
    assert platform.status_code == 200
    payload = platform.json()
    assert payload["evidence_summary"] is not None
    assert payload["fact_check_quality_gate"]["status"] in {"passed", "warning"}
    output_dir = Path(payload["output_dir"])
    assert (output_dir / "evidence_summary.json").exists()
    assert (output_dir / "fact_check_quality_gate.json").exists()
    with ZipFile(payload["package_path"]) as archive:
        assert "evidence_summary.json" in archive.namelist()
        assert "fact_check_quality_gate.json" in archive.namelist()


def test_trace_manifest_includes_evidence_ids_and_gate_status(client):
    brief, _ = generate_approved_final_video(client)
    export_response = client.get(f"/briefs/{brief['id']}/export-package")
    assert export_response.status_code == 200
    with ZipFile(io.BytesIO(export_response.content)) as archive:
        trace = json.loads(archive.read("trace_manifest.json"))
    assert "evidence_item_ids" in trace
    assert "claim_evidence_link_ids" in trace
    assert trace["fact_check_quality_gate_status"] in {"passed", "warning"}


def test_pilot_input_template_validates():
    payload = json.loads(Path("data/pilot/pilot_input_template.json").read_text(encoding="utf-8"))
    assert payload["sources"]
    required = {
        "source_name",
        "source_url",
        "archive_url",
        "retrieved_at",
        "short_excerpt",
        "source_type",
        "topic_hint",
        "why_it_matters",
        "operator_note",
    }
    assert required.issubset(payload["sources"][0])
    assert len(payload["sources"][0]["short_excerpt"]) <= 500


def test_pilot_runner_refuses_auto_approve_in_staging(monkeypatch, tmp_path):
    from scripts import pilot_run

    input_path = tmp_path / "pilot_input.json"
    input_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_name": "real-source",
                        "source_url": "https://example.org/pilot/source",
                        "archive_url": "https://example.org/pilot/archive",
                        "retrieved_at": "2026-06-12T12:00:00Z",
                        "short_excerpt": "Short reviewed source excerpt.",
                        "source_type": "manual_note",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, method, path, *, role, user, workspace=None, body=None):
        return {
            "status_code": 200,
            "body": {"app_env": "staging", "manual_publish_only": True, "platform_publish_api_enabled": False},
            "request_id": "pilot-test",
        }

    monkeypatch.setattr(pilot_run, "request_json", fake_request_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot_run.py",
            "--base-url",
            "http://testserver",
            "--input",
            str(input_path),
            "--auto-approve-sources-for-local-test",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        pilot_run.main()
    assert "only allowed" in str(exc.value)


def test_evidence_link_suggester_returns_suggestions_without_auto_approval(client):
    _, brief = generate_selected_topic_brief(client, source_url="https://example.org/pilot/suggestion-brief")
    claim = first_claim(brief)
    with next(app.dependency_overrides[get_db]()) as db:
        evidence = EvidenceItem(
            workspace_id=1,
            post_id=claim["post_id"] if "post_id" in claim else None,
            evidence_type="public_archive",
            title="Infrastructure coordination source",
            source_name="pilot-suggestion-source",
            source_url="https://example.org/pilot/suggestion-source",
            archive_url="https://example.org/pilot/suggestion-source/archive",
            excerpt="A reviewed public source describes infrastructure coordination.",
            summary="A reviewed public source describes infrastructure coordination.",
            reliability_score=80,
            terms_status="manual_review_required",
            human_status="approved",
            created_by="test",
            reviewed_by="test",
        )
        db.add(evidence)
        db.commit()
        db.refresh(evidence)
        brief_obj = db.get(BriefScript, brief["id"])
        suggestions = EvidenceLinkSuggester().suggest_for_brief(db, brief_obj)
    assert suggestions["auto_approved"] is False
    assert suggestions["suggestions"]
    assert all("requires_manual_confirmation" in item for item in suggestions["suggestions"])


def test_editorial_qa_report_includes_coverage_and_risk_notes(client, tmp_path):
    brief, _ = generate_approved_final_video(client)
    platform = client.post(f"/briefs/{brief['id']}/platform-package").json()
    report = EditorialQAReporter(base_dir=tmp_path).build(client.get(f"/briefs/{brief['id']}").json(), platform)
    qa = report["editorial_qa_report"]
    assert "evidence_coverage_rate" in qa
    assert "script_risk_notes" in qa
    assert qa["manual_publish_checklist_status"] == "required"


def test_pilot_report_markdown_generated(client, tmp_path):
    brief, _ = generate_approved_final_video(client)
    report = EditorialQAReporter(base_dir=tmp_path).build(client.get(f"/briefs/{brief['id']}").json(), None)
    assert Path(report["pilot_report_path"]).exists()
    assert "Pilot Production Report" in Path(report["pilot_report_path"]).read_text(encoding="utf-8")


def test_pilot_flow_can_produce_final_video_and_platform_package_in_local_test(tmp_path):
    input_path = tmp_path / "pilot_input.json"
    output_path = tmp_path / "pilot_run_report.json"
    input_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_name": "pilot-official-note",
                        "source_url": "https://example.org/pilot/official-note",
                        "archive_url": "https://example.org/pilot/official-note/archive",
                        "retrieved_at": "2026-06-12T12:00:00Z",
                        "short_excerpt": "A reviewed public note describes infrastructure coordination for neutral coverage.",
                        "source_type": "official_doc",
                        "topic_hint": "Infrastructure coordination",
                        "why_it_matters": "Useful for a neutral pilot brief.",
                        "operator_note": "Prepared for local pilot test.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/pilot_run.py",
            "--base-url",
            "testclient://local",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--auto-approve-sources-for-local-test",
            "--auto-link-evidence-for-local-test",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert Path(report["final_video"]["video_path"]).exists()
    assert Path(report["platform_package"]["package_path"]).exists()
    assert Path(report["editorial_qa_report_path"]).exists()
    assert Path(report["pilot_report_path"]).exists()
    assert report["manual_publish_only"] is True


def test_fact_check_quality_gate_blocked_pilot_cannot_approve(client):
    _, brief = generate_selected_topic_brief(client, source_url="https://example.org/pilot/blocked-gate")
    client.post(f"/briefs/{brief['id']}/evidence-pack/generate")
    approval = client.post(
        f"/briefs/{brief['id']}/approve",
        json={"reviewer_name": "Reviewer", "reviewer_note": "should fail missing evidence"},
    )
    assert approval.status_code == 409
    assert "quality gate" in json.dumps(approval.json(), ensure_ascii=False)
    assert client.post(f"/briefs/{brief['id']}/platform-package").status_code == 409


def test_manual_publish_only_remains_true(client):
    response = client.get("/health/security")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manual_publish_only"] is True
    assert payload["platform_publish_api_enabled"] is False


def test_create_pilot_input_validates_required_fields(tmp_path):
    from scripts.create_pilot_input import validate_source

    with pytest.raises(ValueError):
        validate_source({"source_name": "", "source_url": "https://example.org/source", "short_excerpt": "short", "source_type": "manual_note"})
    with pytest.raises(ValueError):
        validate_source(
            {
                "source_name": "real source",
                "source_url": "https://example.org/source",
                "short_excerpt": "x" * 501,
                "source_type": "manual_note",
            }
        )
    output = tmp_path / "pilot_input.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/create_pilot_input.py",
            "--output",
            str(output),
            "--source-name",
            "real source",
            "--source-url",
            "https://example.org/source",
            "--archive-url",
            "https://example.org/archive/source",
            "--short-excerpt",
            "Short human-entered excerpt.",
            "--source-type",
            "manual_note",
            "--topic-hint",
            "Topic",
            "--why-it-matters",
            "Neutral relevance.",
            "--operator-note",
            "Operator reviewed.",
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["sources"][0]["source_name"] == "real source"
    assert payload["operator_checklist"]


def test_video_template_yaml_loads():
    config = yaml.safe_load(Path("app/config/video_template.yaml").read_text(encoding="utf-8"))
    assert config["aspect_ratio"] == "9:16"
    assert config["resolution"]["width"] == 1080
    assert config["subtitle_max_chars"] > 0
    assert config["show_ai_label"] is True


def test_script_readability_qa_detects_long_unsupported_assertive_wording():
    script = "今天特朗普公开发帖重点有 1 个。" + "这是一个非常长的句子" * 30 + "。事实证明该说法已经证实。以上为公开信息整理，来源见说明区。"
    report = ScriptReadabilityQA().review(script, [{"verdict": "unsupported"}])
    assert report["qa_status"] == "blocked"
    assert report["long_sentence_count"] > 0
    assert report["blocking_errors"]


def test_subtitle_timing_qa_detects_overlong_subtitles():
    report = SubtitleTimingQA().review(
        [{"index": 1, "start_seconds": 0, "end_seconds": 1.0, "text": "这是一条明显超过最大字数限制的字幕文本"}],
        [{"index": 1, "text": "segment"}],
        max_chars=8,
    )
    assert report["qa_status"] == "needs_revision"
    assert report["overlong_subtitles"]
    assert report["too_fast_subtitles"]


def test_visual_template_qa_checks_png_labels(tmp_path):
    for filename in VisualTemplateQA.REQUIRED_FILES:
        Image.new("RGB", (1080, 1920), (255, 255, 255)).save(tmp_path / filename)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "safety_labels": ["信息整理卡 / AI 生成示意图"],
                "source_cards": [{"source_id": "S1", "url": "https://example.org/source"}],
                "output_files": {"sources_card": "card_04_sources.png"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = VisualTemplateQA().review(tmp_path, {"resolution": {"width": 1080, "height": 1920}, "show_ai_label": True, "show_source_numbers": True})
    assert report["qa_status"] == "passed"
    assert report["contains_ai_label"] is True
    assert report["contains_source_numbers"] is True


def test_editorial_qa_includes_new_template_sections(client):
    brief, _ = generate_approved_final_video(client)
    platform = client.post(f"/briefs/{brief['id']}/platform-package").json()
    report = EditorialQAReporter().build(client.get(f"/briefs/{brief['id']}").json(), platform)["editorial_qa_report"]
    assert "script_readability_report" in report
    assert "subtitle_timing_report" in report
    assert "visual_template_report" in report
    assert "first_sample_publish_readiness" in report


def test_first_sample_readiness_blocks_missing_sources(client, tmp_path):
    brief, _ = generate_approved_final_video(client)
    payload = client.get(f"/briefs/{brief['id']}").json()
    payload["script"]["sources"] = []
    report = EditorialQAReporter(base_dir=tmp_path).build(payload, None)["editorial_qa_report"]
    assert report["first_sample_publish_readiness"]["ready_internal_review"] is False
    assert any("Missing script sources" in item for item in report["first_sample_publish_readiness"]["blockers"])


def test_phase27_pilot_flow_still_produces_final_video_and_platform_package(tmp_path):
    input_path = tmp_path / "pilot_input.json"
    output_path = tmp_path / "pilot_run_report.json"
    input_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_name": "phase27-real-input-helper-source",
                        "source_url": "https://example.org/phase27/source",
                        "archive_url": "https://example.org/phase27/source/archive",
                        "retrieved_at": "2026-06-12T12:00:00Z",
                        "short_excerpt": "A reviewed public note describes infrastructure coordination for template QA.",
                        "source_type": "public_archive",
                        "topic_hint": "Template QA",
                        "why_it_matters": "Useful for a neutral first-sample workflow.",
                        "operator_note": "Prepared for Phase 2.7 local test.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/pilot_run.py",
            "--base-url",
            "testclient://local",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--auto-approve-sources-for-local-test",
            "--auto-link-evidence-for-local-test",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert Path(report["final_video"]["video_path"]).exists()
    assert Path(report["platform_package"]["package_path"]).exists()
    assert "script_readability_report" in report["editorial_qa_report"]


def test_daily_feed_adapter_creates_source_review_items(client):
    response = client.post("/sources/ingest/daily-feed-json", json={"path": "data/feeds/daily_truth_feed.json"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["items"][0]["adapter_name"] == "daily_feed_json"
    assert payload["items"][0]["human_status"] == "pending"


def test_daily_feed_unknown_source_blocked(tmp_path):
    feed = tmp_path / "bad_feed.json"
    feed.write_text(
        json.dumps(
            {
                "feed_date": "2026-06-13",
                "items": [
                    {
                        "source_name": "unknown-source",
                        "source_url": "https://example.org/unknown",
                        "archive_url": "https://example.org/archive/unknown",
                        "retrieved_at": "2026-06-13T12:00:00Z",
                        "short_excerpt": "Short excerpt.",
                        "source_type": "public_archive",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    adapter = DailyFeedJsonAdapter(feed)
    with pytest.raises(ValueError):
        adapter.fetch_review_items()


def test_remote_feed_adapter_creates_source_review_items(client):
    response = client.post("/sources/ingest/remote-feed", json={"config_path": "app/config/remote_source_feeds.yaml"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["filter_report"]["total_raw_items"] == 3
    assert payload["filter_report"]["filtered_by_exclusion"] == 1
    assert payload["items"][0]["adapter_name"] == "remote_feed"
    assert payload["items"][0]["human_status"] == "pending"


def test_remote_feed_blocks_truth_social_direct_url(tmp_path):
    config = tmp_path / "remote_source_feeds.yaml"
    config.write_text(
        """
feeds:
  - name: sample-public-archive-json
    enabled: true
    feed_url: https://truthsocial.com/@realDonaldTrump/rss
    parser: rss
defaults:
  max_items: 5
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        RemoteFeedAdapter(config).validate_terms_safety()


def test_remote_feed_date_filter_keeps_only_target_day_items():
    items, report = RemoteFeedAdapter(Path("app/config/remote_source_feeds.yaml")).fetch_review_items_with_filter_report(target_date="2026-06-14")
    assert items == []
    assert report["total_raw_items"] == 3
    assert report["filtered_by_date"] == 2
    assert report["filtered_by_exclusion"] == 1


def test_remote_feed_readiness_passes_sample_config(client):
    response = client.post("/sources/remote-feed/readiness", json={"config_path": "app/config/remote_source_feeds.yaml"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"passed", "warning"}
    assert payload["feed_count"] == 1
    assert payload["feeds"][0]["preview_item_count"] == 3
    assert payload["feeds"][0]["preview_kept_item_count"] == 2
    assert payload["items_enter_source_review_queue"] is True
    assert payload["direct_truth_social_scraper_used"] is False


def test_remote_feed_readiness_blocks_unknown_source(tmp_path):
    config = tmp_path / "remote_source_feeds.yaml"
    config.write_text(
        """
feeds:
  - name: not-on-allowlist
    enabled: true
    feed_url: data/feeds/remote_feed_sample.xml
    parser: rss
defaults:
  max_items: 5
""",
        encoding="utf-8",
    )
    report = FeedReadinessValidator().validate_remote_feed_config(config, fetch_preview=False)
    assert report["status"] == "blocked"
    assert "not-on-allowlist:feed_not_allowlisted" in report["blocking_errors"]


def test_daily_orchestrator_dry_run_does_not_approve_or_publish(tmp_path):
    from app.jobs.daily_run_orchestrator import run_daily

    report = run_daily("2026-06-13", "dry-run", "data/feeds/daily_truth_feed.json", str(tmp_path))
    assert report["mode"] == "dry-run"
    assert report["accepted_source_count"] == 0
    assert report["platform_publish_api_called"] is False
    assert report["platform_package_path"] is None
    assert (tmp_path / "daily_run_report.json").exists()


def test_daily_orchestrator_remote_dry_run_does_not_approve_or_publish(tmp_path):
    from app.jobs.daily_run_orchestrator import run_daily

    report = run_daily(
        "2026-06-13",
        "dry-run",
        "app/config/remote_source_feeds.yaml",
        str(tmp_path),
        feed_mode="remote",
    )
    assert report["feed_mode"] == "remote"
    assert report["feed_readiness"]["status"] in {"passed", "warning"}
    assert report["feed_filter_report"]["total_raw_items"] == 3
    assert report["feed_filter_report"]["kept_item_count"] == 2
    assert report["accepted_source_count"] == 0
    assert report["platform_publish_api_called"] is False
    assert report["platform_package_path"] is None


def test_daily_run_index_service_writes_latest(tmp_path):
    run_dir = tmp_path / "2099-01-03"
    run_dir.mkdir(parents=True)
    (run_dir / "daily_run_report.json").write_text(
        json.dumps(
            {
                "date": "2099-01-03",
                "mode": "dry-run",
                "feed_mode": "remote",
                "generated_at": "2099-01-03T08:00:00+00:00",
                "feed_item_count": 2,
                "accepted_source_count": 0,
                "manual_actions_required": ["Review sources."],
                "manual_publish_only": True,
                "platform_publish_api_called": False,
                "truth_social_direct_scraper_used": False,
            }
        ),
        encoding="utf-8",
    )
    payload = DailyRunIndexService(tmp_path).write_index()
    assert payload["run_count"] == 1
    assert payload["latest"]["date"] == "2099-01-03"
    assert payload["latest"]["manual_actions_count"] == 1
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "latest.json").exists()


def test_daily_run_index_api_lists_latest(client):
    run_dir = Path("exports/daily_runs/2099-01-04")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "daily_run_report.json").write_text(
            json.dumps(
                {
                    "date": "2099-01-04",
                    "mode": "dry-run",
                    "feed_mode": "remote",
                    "generated_at": "2099-01-04T08:00:00+00:00",
                    "feed_item_count": 1,
                    "accepted_source_count": 0,
                    "manual_actions_required": ["Review daily feed sources."],
                    "manual_publish_only": True,
                    "platform_publish_api_called": False,
                    "truth_social_direct_scraper_used": False,
                }
            ),
            encoding="utf-8",
        )
        index = client.get("/daily-runs")
        assert index.status_code == 200
        assert any(run["date"] == "2099-01-04" for run in index.json()["runs"])
        latest = client.get("/daily-runs/latest")
        assert latest.status_code == 200
        payload = latest.json()
        assert payload["latest"]["date"] == "2099-01-04"
        assert payload["manual_publish_only"] is True
        assert payload["platform_publish_api_called"] is False
        assert payload["truth_social_direct_scraper_used"] is False
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir)


def test_daily_orchestrator_remote_blocked_readiness_stops_intake(tmp_path):
    from app.jobs.daily_run_orchestrator import run_daily

    config = tmp_path / "remote_source_feeds.yaml"
    config.write_text(
        """
feeds:
  - name: sample-public-archive-json
    enabled: true
    feed_url: https://truthsocial.com/@realDonaldTrump/rss
    parser: rss
defaults:
  max_items: 5
""",
        encoding="utf-8",
    )
    report = run_daily("2026-06-13", "dry-run", str(config), str(tmp_path / "out"), feed_mode="remote")
    assert report["publish_readiness"] == "blocked"
    assert report["created_source_count"] == 0
    assert "sample-public-archive-json:direct_truth_social_feed_forbidden" in report["blockers"]


def test_daily_orchestrator_local_auto_works_only_local_test(tmp_path, monkeypatch):
    from app.jobs.daily_run_orchestrator import run_daily

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("AUTH_MODE", "header_stub")
    report = run_daily("2026-06-13", "local-auto", "data/feeds/daily_truth_feed.json", str(tmp_path / "local"))
    assert report["mode"] == "local-auto"
    assert report["final_video_path"] and Path(report["final_video_path"]).exists()
    assert report["platform_package_path"] and Path(report["platform_package_path"]).exists()
    assert report["manual_publish_only"] is True


def test_daily_orchestrator_rejects_local_auto_in_staging(monkeypatch):
    from app.jobs.daily_run_orchestrator import run_daily

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AUTH_MODE", "external")
    with pytest.raises(SystemExit):
        run_daily("2026-06-13", "local-auto", "data/feeds/daily_truth_feed.json")


def test_auto_topic_selector_rejects_weak_evidence_high_risk_topic():
    topic = {
        "id": 1,
        "title": "High risk weak evidence",
        "selected_post_ids": [1],
        "evidence_score": 0.1,
        "risk_score": 0.9,
        "platform_fit_score": 0.8,
        "priority_score": 0.8,
        "rationale": {"freshness": 1.0},
    }
    decision = AutoTopicSelector().select([topic])
    assert decision["selected_topic"] is None
    assert decision["candidates"][0]["auto_selection_status"] == "blocked"


def test_daily_run_report_and_manual_actions_endpoint(client, tmp_path):
    report_dir = Path("exports/daily_runs/2099-01-01")
    if report_dir.exists():
        shutil.rmtree(report_dir)
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "daily_run_report.json").write_text(
            json.dumps(
                {
                    "date": "2099-01-01",
                    "mode": "dry-run",
                    "manual_actions_required": ["Review pending sources."],
                    "final_packages_needing_human_publish_decision": [],
                    "manual_publish_only": True,
                }
            ),
            encoding="utf-8",
        )
        summary = client.get("/daily-runs/2099-01-01/summary")
        assert summary.status_code == 200
        actions = client.get("/daily-runs/2099-01-01/manual-actions")
        assert actions.status_code == 200
        assert "sources_needing_review" in actions.json()
        assert actions.json()["manual_publish_only"] is True
    finally:
        if report_dir.exists():
            shutil.rmtree(report_dir)


def test_scheduler_disabled_by_default(monkeypatch):
    from app.scheduler import create_scheduler

    monkeypatch.delenv("DAILY_RUN_ENABLED", raising=False)
    scheduler = create_scheduler()
    assert scheduler.get_jobs() == []


def test_platform_publish_api_remains_disabled_for_daily_run(client):
    response = client.get("/health/security")
    assert response.status_code == 200
    assert response.json()["platform_publish_api_enabled"] is False
    assert response.json()["manual_publish_only"] is True


def test_safety_regression_fixtures_pass(client):
    cases = json.loads(Path("tests/fixtures/safety_cases.json").read_text(encoding="utf-8"))["cases"]
    case_ids = {case["id"] for case in cases}
    assert {
        "unsupported_accusation",
        "missing_source",
        "missing_ai_disclosure",
        "clickbait_title",
        "blocked_evidence_domain",
        "mock_provider_in_production",
        "unapproved_brief_render_attempt",
    }.issubset(case_ids)

    review = SafetyChecker().review(
        ranked_posts=[{"short_excerpt": "short", "source_url": ""}],
        script={"text": "Neutral script.", "sources": []},
        visual_plan={"cards": [{"ai_label": "missing"}], "prohibited": ["fake_screenshot", "lip_sync"]},
        fact_checks=[{"claim_id": 1, "claim_type": "accusation", "verdict": "unsupported", "sources": []}],
        claims=[{"id": 1, "claim_type": "accusation", "claim_text": "accuse opponents", "requires_fact_check": True}],
        evidence_packs=[{"claim_id": 1, "status": "insufficient", "verdict": "unsupported", "evidence_count": 0}],
    )
    assert review["overall_status"] == "blocked"

    bad_copy = {
        "bilibili": {
            "title_options": ["震惊：彻底完了"],
            "description": "missing disclosures",
            "pinned_comment": "",
            "tags": [],
            "source_disclosure": "",
            "ai_disclosure": "",
            "manual_publish_checklist": [],
        }
    }
    assert ComplianceCopyChecker().check_all(bad_copy)["overall_status"] == "blocked"

    try:
        default_registry(environment="production").get_provider("mock")
    except ValueError:
        pass
    else:
        raise AssertionError("mock provider should be blocked")

    brief = generate_sample_brief(client)
    render_response = client.post(f"/briefs/{brief['id']}/render-package")
    assert render_response.status_code == 409
