import json
import hashlib
import math
import wave
from datetime import datetime, timezone
from pathlib import Path

from app.services.tts_policy import TTSPolicy
from app.tts.base import TTSProvider


class LocalStubTTSProvider(TTSProvider):
    provider = "local_stub"

    def synthesize(self, text: str, output_path: Path, voice: str = "neutral_zh") -> dict:
        self.validate_voice_policy(voice)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_seconds = self._estimate_duration(text)
        self._write_silent_wav(output_path, duration_seconds)
        metadata = {
            "provider": self.provider,
            "voice": voice,
            "model": "local_silence_stub",
            "script_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "voice_policy": "neutral narrator only; identity-targeted voices are not allowed",
            "disclosure": "AI assisted neutral narrator preview / local silent stub; human review required.",
            "duration_seconds": duration_seconds,
            "output_path": str(output_path),
            "external_api_called": False,
        }
        (output_path.parent / "tts_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def validate_voice_policy(self, voice: str) -> None:
        TTSPolicy().validate_voice_name(voice)

    def _estimate_duration(self, text: str) -> float:
        # Short-video target: keep local stub audio in the 45-90 second range.
        estimated = max(45.0, min(90.0, len(text.replace("\n", "")) / 4.5))
        return round(estimated, 2)

    def _write_silent_wav(self, output_path: Path, duration_seconds: float) -> None:
        sample_rate = 44100
        frame_count = int(duration_seconds * sample_rate)
        with wave.open(str(output_path), "w") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            silence = b"\x00\x00"
            chunk = silence * sample_rate
            full_seconds = int(math.floor(duration_seconds))
            for _ in range(full_seconds):
                wav.writeframes(chunk)
            remaining = frame_count - full_seconds * sample_rate
            if remaining > 0:
                wav.writeframes(silence * remaining)
