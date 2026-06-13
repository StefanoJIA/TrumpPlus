from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.services.script_readability_qa import ScriptReadabilityQA
from app.services.subtitle_timing_qa import SubtitleTimingQA
from app.services.visual_template_qa import VisualTemplateQA


class EditorialQAReporter:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("exports/pilot_runs")

    def build(self, brief_payload: dict[str, Any], platform_package_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        brief_id = brief_payload["id"]
        output_dir = self.base_dir / f"brief_{brief_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        gate = brief_payload.get("fact_check_quality_gate") or {}
        coverage = gate.get("claim_coverage") or []
        claim_count = len(brief_payload.get("claims") or [])
        covered_claims = [item for item in coverage if item.get("evidence_count", 0) > 0 or item.get("claim_type") == "opinion"]
        coverage_rate = round(len(covered_claims) / claim_count, 3) if claim_count else 0.0
        unsupported = [check for check in brief_payload.get("fact_checks") or [] if check.get("verdict") in {"unsupported", "unclear"}]

        final_video = brief_payload.get("final_video") or {}
        platform_package = platform_package_payload or brief_payload.get("platform_package") or {}
        copy_report = platform_package.get("copy_compliance_report") or {}

        template_config = self._load_template_config()
        render_package = brief_payload.get("render_package") or {}
        render_dir = render_package.get("output_dir")
        manifest = self._read_json(Path(render_dir) / "manifest.json") if render_dir else {}
        subtitle_items = manifest.get("subtitle_items") or self._read_subtitles(render_dir)
        script_segments = manifest.get("script_segments") or []

        script_report = ScriptReadabilityQA().review(
            brief_payload.get("script", {}).get("text") or "",
            brief_payload.get("fact_checks") or [],
        )
        subtitle_report = SubtitleTimingQA().review(
            subtitle_items,
            script_segments,
            max_chars=int(template_config.get("subtitle_max_chars", 18)),
        )
        visual_report = VisualTemplateQA().review(render_dir, template_config)
        readiness = self._first_sample_readiness(brief_payload, gate, copy_report, script_report, subtitle_report, visual_report)

        report = {
            "brief_id": brief_id,
            "topic": brief_payload.get("title"),
            "source_count": len(brief_payload.get("script", {}).get("sources") or []),
            "evidence_count": sum(item.get("evidence_count", 0) for item in coverage),
            "claim_count": claim_count,
            "evidence_coverage_rate": coverage_rate,
            "high_risk_claims": gate.get("high_risk_claims") or [],
            "unsupported_or_unclear_claims": unsupported,
            "script_risk_notes": self._script_risk_notes(brief_payload, gate),
            "video_files": {
                "final_video": final_video.get("video_path"),
                "render_report": final_video.get("report_path"),
            },
            "platform_copy_status": {
                "package_status": platform_package.get("status"),
                "blocking_errors": copy_report.get("blocking_errors") or [],
                "warnings": copy_report.get("warnings") or [],
            },
            "manual_publish_checklist_status": "required",
            "fact_check_quality_gate": gate,
            "script_readability_report": script_report,
            "subtitle_timing_report": subtitle_report,
            "visual_template_report": visual_report,
            "first_sample_publish_readiness": readiness,
            "qa_status": self._qa_status(brief_payload, gate, copy_report, script_report, subtitle_report, visual_report, readiness),
            "revision_recommendations": self._recommendations(gate, copy_report, final_video, readiness),
            "manual_publish_only": True,
        }

        qa_path = output_dir / "editorial_qa_report.json"
        md_path = output_dir / "PILOT_REPORT.md"
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "script_readability_report.json").write_text(json.dumps(script_report, ensure_ascii=False, indent=2), encoding="utf-8")
        SubtitleTimingQA().write_report(output_dir, subtitle_report)
        VisualTemplateQA().write_report(output_dir, visual_report)
        md_path.write_text(self._markdown(brief_payload, report, platform_package), encoding="utf-8")

        return {
            "output_dir": str(output_dir),
            "editorial_qa_report_path": str(qa_path),
            "pilot_report_path": str(md_path),
            "editorial_qa_report": report,
        }

    def _qa_status(
        self,
        brief_payload: dict[str, Any],
        gate: dict[str, Any],
        copy_report: dict[str, Any],
        script_report: dict[str, Any],
        subtitle_report: dict[str, Any],
        visual_report: dict[str, Any],
        readiness: dict[str, Any],
    ) -> str:
        if (
            gate.get("status") == "blocked"
            or copy_report.get("blocking_errors")
            or script_report.get("qa_status") == "blocked"
            or subtitle_report.get("qa_status") == "blocked"
            or visual_report.get("qa_status") == "blocked"
            or readiness.get("blockers")
        ):
            return "blocked"
        if (
            brief_payload.get("status") != "approved"
            or gate.get("status") == "warning"
            or copy_report.get("warnings")
            or script_report.get("qa_status") == "needs_revision"
            or subtitle_report.get("qa_status") == "needs_revision"
            or visual_report.get("qa_status") == "needs_revision"
        ):
            return "needs_revision"
        return "passed"

    def _script_risk_notes(self, brief_payload: dict[str, Any], gate: dict[str, Any]) -> list[str]:
        notes = []
        script_text = brief_payload.get("script", {}).get("text") or ""
        if gate.get("missing_evidence_claims"):
            notes.append("Some claims are missing approved evidence.")
        if gate.get("weak_evidence_claims"):
            notes.append("Some factual or high-risk claims need stronger evidence.")
        if any(check.get("verdict") in {"unsupported", "unclear"} for check in brief_payload.get("fact_checks") or []):
            notes.append("Unsupported or unclear claims must remain qualified in script and copy.")
        if "目前缺乏足够公开证据" in script_text:
            notes.append("Script contains explicit unsupported/unclear evidence caveat.")
        return notes or ["No script-specific risk notes beyond standard manual review."]

    def _recommendations(
        self,
        gate: dict[str, Any],
        copy_report: dict[str, Any],
        final_video: dict[str, Any],
        readiness: dict[str, Any],
    ) -> list[str]:
        recommendations = []
        recommendations.extend(gate.get("recommendations") or [])
        if copy_report.get("blocking_errors"):
            recommendations.append("Fix blocking platform copy compliance errors before manual publishing.")
        if not final_video.get("video_path"):
            recommendations.append("Generate and inspect final_video.mp4 before manual publishing.")
        recommendations.extend(readiness.get("revision_notes") or [])
        if not recommendations:
            recommendations.append("Ready for final human editorial QA before manual publishing.")
        return recommendations

    def _first_sample_readiness(
        self,
        brief_payload: dict[str, Any],
        gate: dict[str, Any],
        copy_report: dict[str, Any],
        script_report: dict[str, Any],
        subtitle_report: dict[str, Any],
        visual_report: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        revision_notes = []
        if not (brief_payload.get("script", {}).get("sources") or []):
            blockers.append("Missing script sources.")
        if gate.get("status") == "blocked":
            blockers.append("FactCheckQualityGate is blocked.")
        if copy_report.get("blocking_errors"):
            blockers.extend(copy_report.get("blocking_errors") or [])
        for label, qa_report in [("script", script_report), ("subtitle", subtitle_report), ("visual", visual_report)]:
            if qa_report.get("qa_status") == "blocked":
                blockers.extend([f"{label}: {item}" for item in qa_report.get("blocking_errors", [])])
            elif qa_report.get("qa_status") == "needs_revision":
                revision_notes.extend([f"{label}: {item}" for item in qa_report.get("warnings", [])])
        ready_internal = not blockers
        ready_manual_publish = ready_internal and brief_payload.get("status") == "approved" and gate.get("status") == "passed" and not revision_notes
        return {
            "ready_internal_review": ready_internal,
            "ready_manual_publish": ready_manual_publish,
            "blockers": blockers,
            "revision_notes": revision_notes,
            "manual_publish_only": True,
        }

    def _markdown(self, brief_payload: dict[str, Any], report: dict[str, Any], platform_package: dict[str, Any]) -> str:
        gate = report["fact_check_quality_gate"]
        sources = brief_payload.get("script", {}).get("sources") or []
        claims = brief_payload.get("claims") or []
        coverage = {item.get("claim_id"): item for item in gate.get("claim_coverage") or []}
        lines = [
            "# Pilot Production Report",
            "",
            f"Brief ID: {brief_payload['id']}",
            f"Topic: {brief_payload.get('title')}",
            "",
            "## Editorial Rationale",
            brief_payload.get("metadata_json", {}).get("editor_note")
            or brief_payload.get("metadata_json", {}).get("topic_hint")
            or "Neutral public information brief generated from reviewed sources.",
            "",
            "## Sources",
        ]
        lines.extend([f"- {source.get('source_name') or source.get('source_url')}: {source.get('source_url')}" for source in sources] or ["- No sources recorded."])
        lines.extend(["", "## Claim-Evidence Table", "| Claim ID | Type | Evidence Count | Max Reliability | Text |", "| --- | --- | ---: | ---: | --- |"])
        for claim in claims:
            row = coverage.get(claim.get("id"), {})
            lines.append(
                f"| {claim.get('id')} | {claim.get('claim_type')} | {row.get('evidence_count', 0)} | {row.get('max_reliability_score', 0)} | {claim.get('claim_text')} |"
            )
        lines.extend(
            [
                "",
                "## FactCheckQualityGate",
                f"Status: {gate.get('status')}",
                f"Missing evidence claims: {len(gate.get('missing_evidence_claims') or [])}",
                f"Weak evidence claims: {len(gate.get('weak_evidence_claims') or [])}",
                "",
                "## Template QA",
                f"Script readability: {report['script_readability_report'].get('qa_status')} / {report['script_readability_report'].get('readability_score')}",
                f"Subtitle timing: {report['subtitle_timing_report'].get('qa_status')}",
                f"Visual template: {report['visual_template_report'].get('qa_status')}",
                f"Ready internal review: {report['first_sample_publish_readiness'].get('ready_internal_review')}",
                f"Ready manual publish: {report['first_sample_publish_readiness'].get('ready_manual_publish')}",
                "",
                "## Script Summary",
                (brief_payload.get("script", {}).get("text") or "")[:700],
                "",
                "## Output Paths",
                f"Final video: {report['video_files'].get('final_video')}",
                f"Platform package: {platform_package.get('package_path')}",
                "",
                "## Manual Publish Checklist",
                "- Confirm all source links and archive links are included in the platform description or pinned comment.",
                "- Confirm AI illustrative visuals are labeled.",
                "- Confirm no voice impersonation, lip sync, fake screenshot, or unauthorized image appears.",
                "- Confirm this package is manually uploaded only; no platform API is called.",
                "",
                "## Risks Before Publishing",
            ]
        )
        lines.extend([f"- {item}" for item in report["script_risk_notes"] + report["revision_recommendations"]])
        return "\n".join(lines) + "\n"

    def _load_template_config(self) -> dict[str, Any]:
        path = Path("app/config/video_template.yaml")
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_subtitles(self, render_dir: str | None) -> list[dict]:
        if not render_dir:
            return []
        path = Path(render_dir) / "subtitles.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))
