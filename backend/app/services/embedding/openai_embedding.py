"""OpenAI embedding provider."""
from __future__ import annotations

import logging

from app.services.embedding.provider import EmbeddingResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-3-small"
_DIMENSIONS = 1024  # Match Bedrock Titan Embed v2 max; OpenAI text-embedding-3-small supports truncation


class OpenAIEmbeddingProvider:
    """
    Embedding provider backed by OpenAI text-embedding-3-small.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
    ):
        self.api_key = api_key
        self.model_id = model

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=api_key)
        except ImportError as exc:
            raise ImportError("openai package is required for OpenAIEmbeddingProvider") from exc

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """Embed a list of texts using OpenAI embeddings API."""
        response = await self._client.embeddings.create(
            input=texts,
            model=self.model_id,
            dimensions=_DIMENSIONS,
        )
        embeddings = [item.embedding for item in response.data]
        total_tokens = response.usage.total_tokens if response.usage else len(texts) * 100
        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model_id,
            total_tokens=total_tokens,
        )

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        result = await self.embed_texts([text])
        return result.embeddings[0]

    def get_dimensions(self) -> int:
        return _DIMENSIONS
