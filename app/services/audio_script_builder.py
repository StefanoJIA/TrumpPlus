import json
from pathlib import Path


class AudioScriptBuilder:
    def build(self, manifest: dict, output_dir: Path) -> dict:
        script_segments = manifest.get("script_segments", [])
        narration_lines = [segment["text"] for segment in script_segments if segment.get("text")]
        narration_text = "\n".join(narration_lines)
        duration = max(45, min(90, int(manifest.get("duration_target_seconds", 60))))
        visual_cards = manifest.get("visual_cards", [])
        segments = []
        for index, segment in enumerate(script_segments, start=1):
            card = visual_cards[min(index - 1, len(visual_cards) - 1)] if visual_cards else {}
            segments.append(
                {
                    "index": index,
                    "text": segment["text"],
                    "duration_seconds": segment.get("duration_seconds", duration / max(1, len(script_segments))),
                    "visual_card": card.get("image_path"),
                    "subtitle_range": card.get("subtitle_range", [1, 1]),
                }
            )
        (output_dir / "narration.txt").write_text(narration_text, encoding="utf-8")
        (output_dir / "narration_segments.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"narration_text": narration_text, "segments": segments, "duration_target_seconds": duration}

