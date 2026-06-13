import json
import re
from pathlib import Path


class SubtitleGenerator:
    def generate(self, script_text: str, output_dir: Path, duration_target_seconds: int = 60) -> dict:
        chunks = self._chunk_text(script_text)
        if not chunks:
            chunks = [script_text[:18] or "Daily Truth Brief"]
        per_item = max(1.8, duration_target_seconds / len(chunks))
        items = []
        for index, text in enumerate(chunks, start=1):
            start = round((index - 1) * per_item, 2)
            end = round(min(duration_target_seconds, index * per_item), 2)
            items.append({"index": index, "start_seconds": start, "end_seconds": end, "text": text})

        srt_text = self.to_srt(items)
        srt_path = output_dir / "subtitles.srt"
        json_path = output_dir / "subtitles.json"
        srt_path.write_text(srt_text, encoding="utf-8")
        json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"items": items, "srt_path": str(srt_path), "json_path": str(json_path)}

    def _chunk_text(self, text: str, max_chars: int = 18) -> list[str]:
        normalized = re.sub(r"\s+", "", text.replace("\n", "。"))
        sentences = [part for part in re.split(r"([。！？!?])", normalized) if part]
        merged: list[str] = []
        buffer = ""
        for part in sentences:
            buffer += part
            if part in "。！？!?" or len(buffer) >= max_chars:
                merged.extend(self._split_fixed(buffer, max_chars))
                buffer = ""
        if buffer:
            merged.extend(self._split_fixed(buffer, max_chars))
        return [item for item in merged if item]

    def _split_fixed(self, text: str, max_chars: int) -> list[str]:
        return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]

    def to_srt(self, items: list[dict]) -> str:
        blocks = []
        for item in items:
            blocks.append(
                "\n".join(
                    [
                        str(item["index"]),
                        f"{self._format_time(item['start_seconds'])} --> {self._format_time(item['end_seconds'])}",
                        item["text"],
                    ]
                )
            )
        return "\n\n".join(blocks) + "\n"

    def _format_time(self, seconds: float) -> str:
        millis = int(round((seconds - int(seconds)) * 1000))
        total = int(seconds)
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

