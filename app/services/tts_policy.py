from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class TTSPolicy:
    def __init__(self, path: Path | None = None):
        self.path = path or Path("app/config/tts_policy.yaml")
        self.config: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8"))

    @property
    def default_provider(self) -> str:
        return self.config.get("default_provider", "local_stub")

    @property
    def allow_external_tts(self) -> bool:
        return bool(self.config.get("allow_external_tts", False))

    def validate_provider(self, provider: str, production: bool = True) -> None:
        if provider not in set(self.config.get("allowed_providers", [])):
            raise ValueError(f"TTS provider is not allowed: {provider}")
        if production and provider != "local_stub" and not self.allow_external_tts:
            raise ValueError("External TTS is disabled by tts_policy.allow_external_tts=false")

    def validate_voice_name(self, voice: str) -> None:
        normalized = voice.lower().replace("-", "_").replace(" ", "_")
        blocked = [term for term in self.config.get("blocked_voice_terms", []) if term in normalized]
        if blocked:
            raise ValueError(f"Voice policy blocked terms: {', '.join(blocked)}")
        if normalized not in set(self.config.get("allowed_voices", [])):
            raise ValueError(f"Voice is not allowlisted: {voice}")

    def validate_script(self, text: str) -> None:
        if not text.strip():
            raise ValueError("TTS script is empty")
        max_chars = int(self.config.get("max_script_chars", 5000))
        if len(text) > max_chars:
            raise ValueError(f"TTS script exceeds max_script_chars={max_chars}")

    def validate_request(self, provider: str, voice: str, text: str, production: bool = True) -> None:
        self.validate_provider(provider, production=production)
        self.validate_voice_name(voice)
        self.validate_script(text)
