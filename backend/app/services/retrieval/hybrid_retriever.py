"""Hybrid retriever: combines vector and full-text search using Reciprocal Rank Fusion."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Optional

from app.services.retrieval.retriever import RetrievalResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.embedding.provider import EmbeddingProvider

logger = logging.getLogger(__name__)

_RRF_K = 60  # constant for RRF — prevents division by zero, standard value


class HybridRetriever:
    """
    Combines vector similarity search and full-text search using Reciprocal Rank Fusion (RRF).

    RRF score = sum(1 / (rank + k)) for each chunk across both result lists.
    Higher RRF score = better combined relevance.
    """

    def __init__(
        self,
        embedding_provider: "EmbeddingProvider",
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        semantic_weight: float = 0.7,
    ):
        self.embedding_provider = embedding_provider
        self.top_k = top_k
        self.score_threshold = score_threshold
        self.semantic_weight = semantic_weight

    async def retrieve(
        self,
        query: str,
        kb_id: uuid.UUID | str,
        workspace_id: uuid.UUID | str,
        db: "AsyncSession",
    ) -> list[RetrievalResult]:
        """
        Run vector and full-text retrieval in parallel, merge with RRF.

        Args:
            query: User query string
            kb_id: Knowledge base UUID
            workspace_id: Workspace UUID
            db: AsyncSession for DB reads

        Returns:
            List of RetrievalResult ordered by RRF score (desc)
        """
        from app.services.retrieval.vector_retriever import VectorRetriever
        from app.services.retrieval.fulltext_retriever import FullTextRetriever

        # Run both retrievers in parallel with a larger top_k to merge better
        fetch_k = max(self.top_k * 2, 20)
        vector_retriever = VectorRetriever(
            embedding_provider=self.embedding_provider,
            top_k=fetch_k,
            score_threshold=None,  # don't filter before merging
        )
        fts_retriever = FullTextRetriever(top_k=fetch_k)

        vector_results, fts_results = await asyncio.gather(
            vector_retriever.retrieve(query, kb_id, workspace_id, db),
            fts_retriever.retrieve(query, kb_id, workspace_id, db),
        )

        # RRF merge
        rrf_scores: dict[str, float] = {}
        result_map: dict[str, RetrievalResult] = {}

        for rank, r in enumerate(vector_results):
            rrf_contribution = self.semantic_weight / (rank + _RRF_K)
            rrf_scores[r.chunk_id] = rrf_scores.get(r.chunk_id, 0.0) + rrf_contribution
            result_map[r.chunk_id] = r

        keyword_weight = 1.0 - self.semantic_weight
        for rank, r in enumerate(fts_results):
            rrf_contribution = keyword_weight / (rank + _RRF_K)
            rrf_scores[r.chunk_id] = rrf_scores.get(r.chunk_id, 0.0) + rrf_contribution
            if r.chunk_id not in result_map:
                result_map[r.chunk_id] = r

        # Sort by RRF score and take top_k
        sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)

        merged: list[RetrievalResult] = []
        for cid in sorted_ids[:self.top_k]:
            r = result_map[cid]
            rrf_score = rrf_scores[cid]
            if self.score_threshold is not None and rrf_score < self.score_threshold:
                continue
            merged.append(RetrievalResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                doc_filename=r.doc_filename,
                text=r.text,
                score=rrf_score,
                page_number=r.page_number,
                chunk_index=r.chunk_index,
            ))

        logger.debug("Hybrid retrieval returned %d results for query: %s", len(merged), query[:50])
        return merged
