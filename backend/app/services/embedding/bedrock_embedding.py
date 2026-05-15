"""Amazon Bedrock Titan Embed Text v2 embedding provider."""
from __future__ import annotations

import asyncio
import json
import logging

import boto3

from app.core.config import settings
from app.services.embedding.provider import EmbeddingResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "amazon.titan-embed-text-v2:0"
_DIMENSIONS = 1024  # Titan Embed v2 supports 256, 512, 1024 only


def _build_bedrock_client(region: str):
    """Build a boto3 bedrock-runtime client using the correct credential chain."""
    session_kwargs: dict = {}
    if settings.aws_profile:
        session_kwargs["profile_name"] = settings.aws_profile
    session = boto3.Session(**session_kwargs)
    return session.client("bedrock-runtime", region_name=region)


class BedrockEmbeddingProvider:
    """
    Embedding provider backed by Amazon Bedrock Titan Embed Text v2.

    Uses asyncio.to_thread to avoid blocking the event loop since boto3 is synchronous.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        region: str | None = None,
    ):
        self.model_id = model
        self.region = region or settings.aws_bedrock_region
        self._client = _build_bedrock_client(self.region)

    def _invoke_single(self, text: str) -> list[float]:
        """Synchronous invocation for a single text (run in thread)."""
        body = json.dumps({
            "inputText": text,
            "dimensions": _DIMENSIONS,
        })
        response = self._client.invoke_model(
            modelId=self.model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """Embed a list of texts. Runs blocking boto3 calls in a thread pool."""
        embeddings: list[list[float]] = []
        for text in texts:
            embedding = await asyncio.to_thread(self._invoke_single, text)
            embeddings.append(embedding)

        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model_id,
            total_tokens=len(texts) * 100,  # approximate token count
        )

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        return await asyncio.to_thread(self._invoke_single, text)

    def get_dimensions(self) -> int:
        return _DIMENSIONS
