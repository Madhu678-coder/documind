"""Vector similarity retriever using pgvector cosine distance."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import text

from app.services.retrieval.retriever import RetrievalResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.embedding.provider import EmbeddingProvider

logger = logging.getLogger(__name__)


class VectorRetriever:
    """
    Retrieves document chunks using cosine similarity via pgvector.
    """

    def __init__(
        self,
        embedding_provider: "EmbeddingProvider",
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ):
        self.embedding_provider = embedding_provider
        self.top_k = top_k
        self.score_threshold = score_threshold

    async def retrieve(
        self,
        query: str,
        kb_id: uuid.UUID | str,
        workspace_id: uuid.UUID | str,
        db: "AsyncSession",
    ) -> list[RetrievalResult]:
        """
        Embed the query and retrieve the top-k most similar chunks.

        Args:
            query: User query string
            kb_id: Knowledge base UUID
            workspace_id: Workspace UUID
            db: AsyncSession for DB reads

        Returns:
            List of RetrievalResult ordered by cosine similarity (desc)
        """
        # Embed the query
        query_vector = await self.embedding_provider.embed_query(query)

        # Convert to Postgres array literal for pgvector
        vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

        sql = text("""
            SELECT
                d.id AS chunk_id,
                d.document_id,
                doc.filename AS doc_filename,
                d.text,
                1 - (d.embedding <=> CAST(:query_vector AS vector)) AS score,
                d.page_number,
                d.chunk_index
            FROM document_chunks d
            JOIN documents doc ON doc.id = d.document_id
            WHERE d.kb_id = CAST(:kb_id AS uuid)
              AND d.workspace_id = CAST(:workspace_id AS uuid)
              AND d.embedding IS NOT NULL
            ORDER BY d.embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k
        """)

        result = await db.execute(sql, {
            "query_vector": vector_literal,
            "kb_id": str(kb_id),
            "workspace_id": str(workspace_id),
            "top_k": self.top_k,
        })
        rows = result.fetchall()

        results: list[RetrievalResult] = []
        for row in rows:
            score = float(row.score) if row.score is not None else 0.0
            if self.score_threshold is not None and score < self.score_threshold:
                continue
            results.append(RetrievalResult(
                chunk_id=str(row.chunk_id),
                document_id=str(row.document_id),
                doc_filename=row.doc_filename,
                text=row.text,
                score=score,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
            ))

        logger.debug("Vector retrieval returned %d results for query: %s", len(results), query[:50])
        return results
