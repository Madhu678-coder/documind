"""LLM provider abstraction — Protocol and shared types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM backend implementations must satisfy."""

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send messages and return a complete response."""
        ...

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Send messages and yield response tokens as they arrive."""
        ...
