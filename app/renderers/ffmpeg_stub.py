import json
from pathlib import Path


REQUIRED_RENDER_FILES = [
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
]


def check_render_readiness(output_dir: Path) -> dict:
    missing = [filename for filename in REQUIRED_RENDER_FILES if not (output_dir / filename).exists()]
    report = {
        "ready": not missing,
        "missing_files": missing,
        "mp4_rendered": False,
        "renderer": "ffmpeg_stub",
        "next_step": "Phase 1.3 can connect real ffmpeg rendering after this readiness check passes.",
    }
    (output_dir / "readiness_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

