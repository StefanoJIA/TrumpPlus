from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import imageio_ffmpeg


class VideoQAAnalyzer:
    def analyze(self, video_path: str | Path, platform_profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
        path = Path(video_path)
        report: dict[str, Any] = {
            "video_path": str(path),
            "file_size": 0,
            "duration_seconds": 0.0,
            "width": None,
            "height": None,
            "video_codec": None,
            "audio_codec": None,
            "has_audio": False,
            "has_video": False,
            "aspect_ratio": None,
            "platform_fit": {},
            "warnings": [],
            "blocking_errors": [],
        }
        if not path.exists():
            report["blocking_errors"].append("final_video_missing")
            report["platform_fit"] = self._platform_fit(report, platform_profiles)
            return report

        report["file_size"] = path.stat().st_size
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            self._analyze_with_ffmpeg(path, report)
            report["platform_fit"] = self._platform_fit(report, platform_profiles)
            return report

        command = [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
        if completed.returncode != 0:
            report["blocking_errors"].append("ffprobe_failed")
            report["warnings"].append(completed.stderr[-1000:])
            report["platform_fit"] = self._platform_fit(report, platform_profiles)
            return report

        data = json.loads(completed.stdout)
        report["duration_seconds"] = round(float(data.get("format", {}).get("duration") or 0), 2)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not report["has_video"]:
                report["has_video"] = True
                report["video_codec"] = stream.get("codec_name")
                report["width"] = stream.get("width")
                report["height"] = stream.get("height")
            if stream.get("codec_type") == "audio" and not report["has_audio"]:
                report["has_audio"] = True
                report["audio_codec"] = stream.get("codec_name")

        if not report["has_video"]:
            report["blocking_errors"].append("missing_video_stream")
        if not report["has_audio"]:
            report["blocking_errors"].append("missing_audio_stream")
        if report["width"] and report["height"]:
            report["aspect_ratio"] = self._aspect_ratio(int(report["width"]), int(report["height"]))
        report["platform_fit"] = self._platform_fit(report, platform_profiles)
        return report

    def _analyze_with_ffmpeg(self, path: Path, report: dict[str, Any]) -> None:
        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        command = [ffmpeg, "-hide_banner", "-i", str(path)]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
        output = "\n".join([completed.stdout, completed.stderr])
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if duration_match:
            hours, minutes, seconds = duration_match.groups()
            report["duration_seconds"] = round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 2)
        video_match = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", output)
        if video_match:
            report["has_video"] = True
            report["video_codec"] = video_match.group(1)
            report["width"] = int(video_match.group(2))
            report["height"] = int(video_match.group(3))
            report["aspect_ratio"] = self._aspect_ratio(report["width"], report["height"])
        audio_match = re.search(r"Audio:\s*([^,\s]+)", output)
        if audio_match:
            report["has_audio"] = True
            report["audio_codec"] = audio_match.group(1)
        if not report["has_video"]:
            report["blocking_errors"].append("missing_video_stream")
        if not report["has_audio"]:
            report["blocking_errors"].append("missing_audio_stream")
        if not report["has_video"] and not report["has_audio"]:
            report["warnings"].append("ffmpeg_probe_failed")

    def _aspect_ratio(self, width: int, height: int) -> str:
        divisor = math.gcd(width, height)
        return f"{width // divisor}:{height // divisor}"

    def _platform_fit(self, report: dict[str, Any], platform_profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
        fit = {}
        for platform, profile in platform_profiles.items():
            warnings = []
            blocking = []
            if report["blocking_errors"]:
                blocking.extend(report["blocking_errors"])
            duration = float(report.get("duration_seconds") or 0)
            min_duration = float(profile.get("preferred_duration_min") or 0)
            max_duration = float(profile.get("preferred_duration_max") or 0)
            if duration and min_duration and duration < min_duration:
                warnings.append(f"duration_below_preferred_min:{min_duration}")
            if duration and max_duration and duration > max_duration:
                warnings.append(f"duration_above_preferred_max:{max_duration}")
            preferred = profile.get("preferred_aspect_ratio") or []
            if isinstance(preferred, str):
                preferred = [preferred]
            if report.get("aspect_ratio") and preferred and report["aspect_ratio"] not in preferred:
                warnings.append(f"aspect_ratio_not_preferred:{report['aspect_ratio']}")
            fit[platform] = {
                "preferred_aspect_ratio": preferred,
                "preferred_duration_range": [min_duration, max_duration],
                "warnings": warnings,
                "blocking_errors": blocking,
                "passed": not blocking,
            }
        return fit
