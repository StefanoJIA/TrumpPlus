from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path, voice: str = "neutral_zh") -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_voice_policy(self, voice: str) -> None:
        raise NotImplementedError

