"""Embedding provider protocol and result types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class EmbeddingResult:
    embeddings: list[list[float]]
    model: str
    total_tokens: int


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed_texts(self, texts: list[str]) -> EmbeddingResult: ...
    async def embed_query(self, text: str) -> list[float]: ...
    def get_dimensions(self) -> int: ...
