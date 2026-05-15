"""
OpenAI-compatible LLM provider.

Handles:
  - OpenAI          (base_url=None, uses default api.openai.com)
  - Anthropic direct (base_url=https://api.anthropic.com/v1  — messages API compatible)
  - DeepSeek        (base_url=https://api.deepseek.com/v1)
  - Grok / xAI      (base_url=https://api.x.ai/v1)

All four use the OpenAI Python SDK's chat-completions endpoint.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.services.llm.provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_PROVIDER_DEFAULTS: dict[str, dict] = {
    "openai":    {"base_url": None,                          "default_model": "gpt-4o"},
    "deepseek":  {"base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    "grok":      {"base_url": "https://api.x.ai/v1",         "default_model": "grok-3"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1","default_model": "claude-sonnet-4-6"},
}


class OpenAICompatProvider:
    """
    LLMProvider backed by any OpenAI-compatible chat-completions API.

    Args:
        model:       Model identifier (e.g. "gpt-4o", "deepseek-chat", "grok-3").
        api_key:     API key for the target service.
        base_url:    Override base URL for non-OpenAI endpoints. None = OpenAI default.
        provider_name: Hint for logging; doesn't affect behaviour.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ):
        try:
            from openai import AsyncOpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for OpenAICompatProvider. "
                "Add 'openai>=1.0' to requirements.txt."
            ) from exc

        self.model = model
        self._provider_name = provider_name
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    @classmethod
    def from_provider_name(
        cls,
        provider_name: str,
        model: str | None,
        api_key: str,
    ) -> "OpenAICompatProvider":
        """Construct using a named-provider shorthand (openai / deepseek / grok / anthropic)."""
        cfg = _PROVIDER_DEFAULTS.get(provider_name, _PROVIDER_DEFAULTS["openai"])
        return cls(
            model=model or cfg["default_model"],
            api_key=api_key,
            base_url=cfg["base_url"],
            provider_name=provider_name,
        )

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        all_messages: list[dict] = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=all_messages,  # type: ignore[arg-type]
            max_tokens=max_tokens or 4096,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            content=content,
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        all_messages: list[dict] = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=all_messages,  # type: ignore[arg-type]
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
