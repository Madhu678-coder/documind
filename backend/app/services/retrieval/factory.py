"""Retriever factory: creates the appropriate retriever based on KB settings."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.embedding.provider import EmbeddingProvider


class RetrieverFactory:
    """Factory for creating retriever instances based on knowledge base settings."""

    @staticmethod
    def create(kb_settings: dict[str, Any], embedding_provider: "EmbeddingProvider"):
        """
        Create and return the appropriate retriever.

        Args:
            kb_settings: Knowledge base settings dict (from KB.settings)
            embedding_provider: EmbeddingProvider instance (may be unused for FTS-only)

        Returns:
            A retriever with a `.retrieve(query, kb_id, workspace_id, db)` async method
        """
        retrieval_mode = kb_settings.get("retrieval_mode", "vector")
        top_k = int(kb_settings.get("top_k", 5))
        score_threshold = kb_settings.get("score_threshold")
        if score_threshold is not None:
            score_threshold = float(score_threshold)

        if retrieval_mode == "vector":
            from app.services.retrieval.vector_retriever import VectorRetriever
            return VectorRetriever(
                embedding_provider=embedding_provider,
                top_k=top_k,
                score_threshold=score_threshold,
            )

        elif retrieval_mode == "fulltext":
            from app.services.retrieval.fulltext_retriever import FullTextRetriever
            return FullTextRetriever(top_k=top_k)

        elif retrieval_mode == "hybrid":
            from app.services.retrieval.hybrid_retriever import HybridRetriever
            semantic_weight = float(kb_settings.get("hybrid_semantic_weight", 0.7))
            return HybridRetriever(
                embedding_provider=embedding_provider,
                top_k=top_k,
                score_threshold=score_threshold,
                semantic_weight=semantic_weight,
            )

        else:
            # Default to vector retrieval
            from app.services.retrieval.vector_retriever import VectorRetriever
            return VectorRetriever(
                embedding_provider=embedding_provider,
                top_k=top_k,
                score_threshold=score_threshold,
            )
