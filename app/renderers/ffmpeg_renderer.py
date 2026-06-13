import json
from functools import lru_cache
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from app.services.audio_script_builder import AudioScriptBuilder
from app.tts.local_stub import LocalStubTTSProvider


class FFMpegRenderer:
    def __init__(self, tts_provider: LocalStubTTSProvider | None = None):
        self.tts_provider = tts_provider or LocalStubTTSProvider()

    def render(self, render_package_dir: Path, output_dir: Path, voice: str = "neutral_zh", tts_dir: Path | None = None) -> dict:
        render_package_dir = render_package_dir.resolve()
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = render_package_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        audio_script = AudioScriptBuilder().build(manifest, output_dir)
        default_audio_path = output_dir / "audio.wav"
        audio_path, tts_metadata, tts_source, voice_qa_status = self._prepare_audio(audio_script["narration_text"], default_audio_path, voice, tts_dir)
        video_path = output_dir / "final_video.mp4"
        concat_path = render_package_dir / "ffmpeg_images.txt"
        self._write_concat_file(manifest, concat_path)

        command = [
            self._ffmpeg_executable(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_path.name,
            "-i",
            str(audio_path),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,subtitles=subtitles.srt",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-shortest",
            str(video_path),
        ]
        completed = subprocess.run(command, cwd=render_package_dir, text=True, capture_output=True, timeout=180, check=False)
        if completed.returncode != 0:
            report = self._report(
                status="failed",
                manifest=manifest,
                output_dir=output_dir,
                video_path=video_path,
                audio_path=audio_path,
                tts_metadata=tts_metadata,
                tts_source=tts_source,
                voice_qa_status=voice_qa_status,
                error_message=completed.stderr[-4000:],
            )
            raise RuntimeError(report["error_message"])

        report = self._report(
            status="rendered",
            manifest=manifest,
            output_dir=output_dir,
            video_path=video_path,
            audio_path=audio_path,
            tts_metadata=tts_metadata,
            tts_source=tts_source,
            voice_qa_status=voice_qa_status,
            error_message=None,
        )
        (output_dir / "README_FINAL_VIDEO.md").write_text(self._readme(manifest), encoding="utf-8")
        return report

    def _ffmpeg_executable(self) -> str:
        system = shutil.which("ffmpeg")
        if system and _supports_subtitles_filter(system):
            return system
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if _supports_subtitles_filter(bundled):
            return bundled
        return system or bundled

    def _write_concat_file(self, manifest: dict, concat_path: Path) -> None:
        lines = []
        visual_cards = manifest.get("visual_cards", [])
        for card in visual_cards:
            lines.append(f"file '{card['image_path']}'")
            lines.append(f"duration {float(card.get('duration_seconds', 3)):.2f}")
        if visual_cards:
            lines.append(f"file '{visual_cards[-1]['image_path']}'")
        concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _prepare_audio(self, text: str, audio_path: Path, voice: str, tts_dir: Path | None) -> tuple[Path, dict, str, str | None]:
        if tts_dir:
            qa_path = tts_dir / "voice_qa_report.json"
            metadata_path = tts_dir / "tts_metadata.json"
            source_audio = self._find_tts_audio(tts_dir)
            if qa_path.exists() and metadata_path.exists() and source_audio:
                qa = json.loads(qa_path.read_text(encoding="utf-8"))
                if qa.get("status") == "blocked":
                    raise RuntimeError("Voice QA is blocked; final video cannot be rendered")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                target_audio = audio_path.with_suffix(source_audio.suffix)
                shutil.copy2(source_audio, target_audio)
                return target_audio, metadata, "generated_tts", qa.get("status")
        metadata = self.tts_provider.synthesize(text, audio_path, voice=voice)
        return audio_path, metadata, "local_stub", None

    def _find_tts_audio(self, tts_dir: Path) -> Path | None:
        for name in ["audio.wav", "audio.mp3"]:
            path = tts_dir / name
            if path.exists() and path.stat().st_size > 0:
                return path
        return None

    def _report(
        self,
        status: str,
        manifest: dict,
        output_dir: Path,
        video_path: Path,
        audio_path: Path,
        tts_metadata: dict,
        tts_source: str,
        voice_qa_status: str | None,
        error_message: str | None,
    ) -> dict:
        files = {
            "final_video": str(video_path),
            "narration": str(output_dir / "narration.txt"),
            "narration_segments": str(output_dir / "narration_segments.json"),
            "audio": str(audio_path),
            "tts_metadata": str(output_dir / "tts_metadata.json"),
            "render_report": str(output_dir / "render_report.json"),
            "readme": str(output_dir / "README_FINAL_VIDEO.md"),
        }
        report = {
            "status": status,
            "brief_id": manifest["brief_id"],
            "duration_seconds": manifest.get("duration_target_seconds", 60),
            "aspect_ratio": manifest.get("aspect_ratio", "9:16"),
            "resolution": "1080x1920",
            "files": files,
            "video_size_bytes": video_path.stat().st_size if video_path.exists() else 0,
            "tts_provider": tts_metadata["provider"],
            "tts_source": tts_source,
            "voice_qa_status": voice_qa_status,
            "voice": tts_metadata["voice"],
            "voice_policy": tts_metadata["voice_policy"],
            "subtitles_burned_in": status == "rendered",
            "mp4_rendered": status == "rendered",
            "automatic_publishing": False,
            "error_message": error_message,
        }
        (output_dir / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _readme(self, manifest: dict) -> str:
        return "\n".join(
            [
                "# Daily Truth Brief Final Video",
                "",
                "This directory contains a local preview MP4 generated from approved render assets.",
                "",
                "Compliance boundaries:",
                "- Neutral narrator only; no Trump or political figure voice.",
                "- No lip-sync video.",
                "- No fake Truth Social screenshots.",
                "- No automatic publishing.",
                "- Keep source links and information-card labels visible.",
                "",
                f"Brief ID: {manifest['brief_id']}",
            ]
        )


@lru_cache(maxsize=8)
def _supports_subtitles_filter(ffmpeg: str) -> bool:
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return completed.returncode == 0 and " subtitles " in completed.stdout
