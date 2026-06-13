from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.compliance_copy_checker import ComplianceCopyChecker
from app.services.platform_copy_generator import PlatformCopyGenerator
from app.services.video_qa_analyzer import VideoQAAnalyzer


class PlatformPackageBuilder:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("exports/platform_packages")
        self.copy_generator = PlatformCopyGenerator()

    def build(self, brief_payload: dict, final_video_payload: dict) -> dict:
        brief_id = brief_payload["id"]
        output_dir = self.base_dir / f"brief_{brief_id}"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        video_path = Path(final_video_payload["video_path"])
        if not video_path.exists():
            raise FileNotFoundError(f"final_video.mp4 not found: {video_path}")
        copied_video_path = output_dir / "final_video.mp4"
        shutil.copy2(video_path, copied_video_path)

        profiles = self.copy_generator.load_profiles()
        qa_report = VideoQAAnalyzer().analyze(copied_video_path, profiles)
        platform_copies = self.copy_generator.generate_all(brief_payload, {"video_path": str(copied_video_path)})
        copy_report = ComplianceCopyChecker().check_all(platform_copies)
        gate_report = brief_payload.get("fact_check_quality_gate") or {}
        evidence_summary = {
            "brief_id": brief_id,
            "evidence_packs": brief_payload.get("evidence_packs") or [],
            "claim_coverage": gate_report.get("claim_coverage", []),
            "missing_evidence_claims": gate_report.get("missing_evidence_claims", []),
            "weak_evidence_claims": gate_report.get("weak_evidence_claims", []),
            "high_risk_claims": gate_report.get("high_risk_claims", []),
        }

        for platform, payload in platform_copies.items():
            (output_dir / f"{platform}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "qa_report.json").write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "copy_compliance_report.json").write_text(
            json.dumps(copy_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "evidence_summary.json").write_text(
            json.dumps(evidence_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "fact_check_quality_gate.json").write_text(
            json.dumps(gate_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "sources.json").write_text(
            json.dumps(brief_payload["script"]["sources"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "safety_review.json").write_text(
            json.dumps(brief_payload["safety_review"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "MANUAL_PUBLISH_CHECKLIST.md").write_text(
            self._manual_checklist(platform_copies), encoding="utf-8"
        )
        (output_dir / "README_PLATFORM_PACKAGE.md").write_text(self._readme(brief_id), encoding="utf-8")

        package_path = output_dir / "platform_package.zip"
        self._zip_dir(output_dir, package_path)
        return {
            "output_dir": str(output_dir),
            "package_path": str(package_path),
            "qa_report_path": str(output_dir / "qa_report.json"),
            "qa_report": qa_report,
            "copy_compliance_report": copy_report,
            "evidence_summary": evidence_summary,
            "fact_check_quality_gate": gate_report,
            "platform_copies": platform_copies,
        }

    def _zip_dir(self, output_dir: Path, package_path: Path) -> None:
        with ZipFile(package_path, "w", ZIP_DEFLATED) as archive:
            for path in output_dir.iterdir():
                if path.is_file() and path != package_path:
                    archive.write(path, path.name)

    def _manual_checklist(self, platform_copies: dict) -> str:
        first = next(iter(platform_copies.values()))
        return "\n".join(["# Manual Publish Checklist", ""] + [f"- {item}" for item in first["manual_publish_checklist"]] + [""])

    def _readme(self, brief_id: int) -> str:
        return "\n".join(
            [
                "# Daily Truth Brief Platform Package",
                "",
                "This package is for pre-publish platform adaptation only. It does not call Bilibili, Xiaohongshu, Douyin, YouTube, or any other publishing API.",
                "",
                "Contents include neutral title options, descriptions, tags, source disclosure, AI/manual-review disclosure, video QA, copy compliance, and a manual publishing checklist.",
                "",
                "Compliance boundaries:",
                "- Manual publish only.",
                "- No political mobilization or voting guidance.",
                "- No Trump voice, celebrity voice, voice clone, lip sync, fake screenshots, or unauthorized news images.",
                "- Keep sources and `AI 辅助整理 / 人工审核` visible in platform copy.",
                "",
                f"Brief ID: {brief_id}",
            ]
        )
