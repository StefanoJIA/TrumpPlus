from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from app.services.tts_policy import TTSPolicy


class VoiceQA:
    def review(self, audio_path: str | Path, metadata: dict[str, Any]) -> dict[str, Any]:
        audio = Path(audio_path)
        rules = []
        warnings = []
        blocking = []

        def add(rule_id: str, passed: bool, severity: str, evidence: dict[str, Any] | None = None) -> None:
            rule = {"rule_id": rule_id, "passed": passed, "severity": severity, "evidence": evidence or {}}
            rules.append(rule)
            if not passed and severity == "blocking":
                blocking.append(rule_id)
            elif not passed:
                warnings.append(rule_id)

        policy = TTSPolicy()
        try:
            policy.validate_provider(metadata.get("provider", ""), production=False)
            provider_ok = True
        except ValueError:
            provider_ok = False
        try:
            policy.validate_voice_name(metadata.get("voice", ""))
            voice_ok = True
        except ValueError:
            voice_ok = False
        text_blob = json.dumps(metadata, ensure_ascii=False).lower()
        blocked_terms = [term for term in policy.config.get("blocked_voice_terms", []) if term in text_blob]
        disclosure = metadata.get("disclosure") or ""
        duration = self._duration(audio)

        add("provider_allowed", provider_ok, "blocking", {"provider": metadata.get("provider")})
        add("voice_allowed", voice_ok, "blocking", {"voice": metadata.get("voice")})
        add("no_blocked_voice_terms", not blocked_terms, "blocking", {"blocked_terms": blocked_terms})
        add("no_impersonation_wording", "impersonation" not in text_blob and "clone" not in text_blob, "blocking")
        add("disclosure_present", bool(disclosure), "blocking", {"disclosure": disclosure})
        add("audio_file_exists", audio.exists() and audio.stat().st_size > 0, "blocking", {"audio_path": str(audio)})
        add("duration_estimated", duration > 0, "warning", {"duration_seconds": duration})
        status = "blocked" if blocking else "warning" if warnings else "passed"
        return {
            "status": status,
            "rules": rules,
            "warnings": warnings,
            "blocking_reasons": blocking,
            "audio_path": str(audio),
            "duration_seconds": duration,
            "provider": metadata.get("provider"),
            "voice": metadata.get("voice"),
        }

    def _duration(self, audio: Path) -> float:
        if not audio.exists():
            return 0.0
        if audio.suffix.lower() == ".wav":
            try:
                with wave.open(str(audio), "rb") as wav:
                    return round(wav.getnframes() / float(wav.getframerate()), 2)
            except wave.Error:
                return 0.0
        # For generated mp3 from external providers, first version records duration in metadata elsewhere.
        return 0.01 if audio.stat().st_size > 0 else 0.0
