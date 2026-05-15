"""Anthropic direct LLM provider stub."""
from __future__ import annotations

from typing import AsyncIterator

from app.services.llm.provider import LLMProvider, LLMResponse


class AnthropicDirectProvider:
    """Stub implementation — wire up anthropic SDK when needed."""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022-v2", api_key: str | None = None):
        self.model = model
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError("AnthropicDirectProvider is not yet implemented")

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("AnthropicDirectProvider is not yet implemented")
        yield  # make this a generator
