from typing import Protocol


class LLMClient(Protocol):
    def generate(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise NotImplementedError


class OpenAICompatibleClient:
    """Thin boundary for future OpenAI-compatible providers."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str = "gpt-4.1-mini"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def generate(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise NotImplementedError("LLM generation is intentionally not wired in the MVP mock pipeline.")

