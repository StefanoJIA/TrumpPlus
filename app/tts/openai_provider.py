from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from app.services.tts_policy import TTSPolicy
from app.tts.base import TTSProvider


class OpenAITTSProvider(TTSProvider):
    provider = "openai_tts"
    voice_map = {
        "neutral_zh": "alloy",
        "neutral_zh_female": "nova",
        "neutral_zh_male": "verse",
    }

    def __init__(self, client=None, model: str = "gpt-4o-mini-tts"):
        self.client = client
        self.model = model
        self.policy = TTSPolicy()

    def synthesize(self, text: str, output_path: Path, voice: str = "neutral_zh") -> dict:
        self.validate_voice_policy(voice)
        self.policy.validate_request(self.provider, voice, text, production=True)
        api_key = os.getenv("OPENAI_API_KEY")
        if self.client is None and not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for openai_tts provider")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        mapped_voice = self.voice_map[voice]
        if self.client is not None:
            audio_bytes = self.client.synthesize(text=text, voice=mapped_voice, model=self.model)
            output_path.write_bytes(audio_bytes)
            external_api_called = False
        else:
            from openai import OpenAI  # type: ignore

            client = OpenAI(api_key=api_key)
            with client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=mapped_voice,
                input=text,
            ) as response:
                response.stream_to_file(output_path)
            external_api_called = True

        metadata = {
            "provider": self.provider,
            "voice": voice,
            "mapped_voice": mapped_voice,
            "model": self.model,
            "script_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "voice_policy": "neutral narrator only; identity-targeted voices are not allowed",
            "disclosure": "AI assisted neutral narrator voice; not a public figure; human reviewed before use.",
            "output_path": str(output_path),
            "external_api_called": external_api_called,
        }
        (output_path.parent / "tts_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def validate_voice_policy(self, voice: str) -> None:
        self.policy.validate_voice_name(voice)
