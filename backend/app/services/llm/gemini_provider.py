"""Google Gemini LLM provider via the google-genai SDK."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.services.llm.provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider:
    """
    LLMProvider backed by Google Gemini (google-genai SDK).

    Args:
        model:   Gemini model identifier, e.g. "gemini-2.0-flash", "gemini-1.5-pro".
        api_key: Google AI Studio API key.
    """

    def __init__(self, model: str = _DEFAULT_MODEL, api_key: str | None = None):
        try:
            from google import genai  # type: ignore
            from google.genai import types as genai_types  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package is required for GeminiProvider. "
                "Add 'google-genai>=1.0' to requirements.txt."
            ) from exc

        self.model = model
        self._genai = genai
        self._types = genai_types
        self._client = genai.Client(api_key=api_key)

    def _build_contents(self, messages: list[dict]) -> list:
        """Convert OpenAI-style messages to Gemini Content objects."""
        contents = []
        for msg in messages:
            role = "user" if msg["role"] != "assistant" else "model"
            contents.append(
                self._types.Content(
                    role=role,
                    parts=[self._types.Part(text=msg["content"])],
                )
            )
        return contents

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        import asyncio

        config_kwargs: dict = {"max_output_tokens": max_tokens or 4096}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        contents = self._build_contents(messages)
        config = self._types.GenerateContentConfig(**config_kwargs)

        # Gemini SDK is sync; run in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            ),
        )

        content = response.text or ""
        usage = response.usage_metadata
        return LLMResponse(
            content=content,
            model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        import asyncio

        config_kwargs: dict = {"max_output_tokens": 4096}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        contents = self._build_contents(messages)
        config = self._types.GenerateContentConfig(**config_kwargs)

        loop = asyncio.get_event_loop()
        # generate_content_stream is sync-iterable; pull chunks in executor
        chunks_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _produce():
            try:
                for chunk in self._client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                ):
                    text = chunk.text or ""
                    if text:
                        loop.call_soon_threadsafe(chunks_queue.put_nowait, text)
            finally:
                loop.call_soon_threadsafe(chunks_queue.put_nowait, None)

        loop.run_in_executor(None, _produce)

        while True:
            token = await chunks_queue.get()
            if token is None:
                break
            yield token
