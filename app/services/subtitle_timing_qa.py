from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SubtitleTimingQA:
    def review(
        self,
        subtitles: list[dict] | None = None,
        script_segments: list[dict] | None = None,
        *,
        subtitles_path: str | Path | None = None,
        max_chars: int = 18,
    ) -> dict[str, Any]:
        if subtitles is None and subtitles_path:
            subtitles = json.loads(Path(subtitles_path).read_text(encoding="utf-8"))
        subtitles = subtitles or []
        script_segments = script_segments or []
        warnings: list[str] = []
        blockers: list[str] = []
        overlong = []
        too_fast = []
        empty = []
        for item in subtitles:
            text = item.get("text", "")
            duration = float(item.get("end_seconds", 0)) - float(item.get("start_seconds", 0))
            if not text.strip():
                empty.append(item.get("index"))
            if len(text) > max_chars:
                overlong.append({"index": item.get("index"), "chars": len(text)})
            if duration < 1.2:
                too_fast.append({"index": item.get("index"), "duration_seconds": round(duration, 2)})
        if empty:
            blockers.append(f"Empty subtitles found: {empty}")
        if overlong:
            warnings.append(f"{len(overlong)} subtitle(s) exceed {max_chars} characters.")
        if too_fast:
            warnings.append(f"{len(too_fast)} subtitle(s) have duration under 1.2s.")
        if script_segments and subtitles and len(subtitles) < len(script_segments):
            warnings.append("Subtitle count is lower than script segment count; check coverage.")
        if not subtitles:
            blockers.append("No subtitles found.")
        report = {
            "subtitle_count": len(subtitles),
            "script_segment_count": len(script_segments),
            "max_chars": max_chars,
            "overlong_subtitles": overlong,
            "too_fast_subtitles": too_fast,
            "empty_subtitles": empty,
            "warnings": warnings,
            "blocking_errors": blockers,
            "qa_status": "blocked" if blockers else "needs_revision" if warnings else "passed",
        }
        return report

    def write_report(self, output_dir: Path, report: dict[str, Any]) -> Path:
        path = output_dir / "subtitle_timing_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
