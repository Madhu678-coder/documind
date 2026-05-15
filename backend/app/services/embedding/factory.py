"""Embedding provider factory."""
from __future__ import annotations

from typing import Optional

from app.services.embedding.provider import EmbeddingProvider


class EmbeddingFactory:
    """Factory for creating embedding provider instances."""

    @staticmethod
    def create(
        provider_name: str,
        model_id: str,
        api_key: Optional[str] = None,
        region: Optional[str] = None,
    ) -> EmbeddingProvider:
        """
        Create and return the appropriate EmbeddingProvider.

        Args:
            provider_name: 'bedrock' or 'openai'
            model_id: Model identifier (e.g. 'amazon.titan-embed-text-v2:0')
            api_key: Required for OpenAI provider
            region: Optional AWS region override for Bedrock

        Returns:
            An EmbeddingProvider instance
        """
        if provider_name == "bedrock":
            from app.services.embedding.bedrock_embedding import BedrockEmbeddingProvider
            return BedrockEmbeddingProvider(model=model_id, region=region)
        elif provider_name == "openai":
            if not api_key:
                raise ValueError("api_key is required for OpenAI embedding provider")
            from app.services.embedding.openai_embedding import OpenAIEmbeddingProvider
            return OpenAIEmbeddingProvider(api_key=api_key, model=model_id)
        else:
            raise ValueError(f"Unknown embedding provider: {provider_name!r}. Must be 'bedrock' or 'openai'.")
