"""Full-text search retriever using PostgreSQL tsvector/tsquery."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.services.retrieval.retriever import RetrievalResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FullTextRetriever:
    """
    Retrieves document chunks using PostgreSQL full-text search.
    No embeddings required — uses the GIN index on the tsvector.
    """

    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    async def retrieve(
        self,
        query: str,
        kb_id: uuid.UUID | str,
        workspace_id: uuid.UUID | str,
        db: "AsyncSession",
    ) -> list[RetrievalResult]:
        """
        Retrieve chunks using PostgreSQL full-text search.

        Args:
            query: User query string
            kb_id: Knowledge base UUID
            workspace_id: Workspace UUID
            db: AsyncSession for DB reads

        Returns:
            List of RetrievalResult ordered by ts_rank (desc)
        """
        sql = text("""
            SELECT
                d.id AS chunk_id,
                d.document_id,
                doc.filename AS doc_filename,
                d.text,
                ts_rank(
                    to_tsvector('english', d.text),
                    plainto_tsquery('english', :query)
                ) AS score,
                d.page_number,
                d.chunk_index
            FROM document_chunks d
            JOIN documents doc ON doc.id = d.document_id
            WHERE d.kb_id = CAST(:kb_id AS uuid)
              AND d.workspace_id = CAST(:workspace_id AS uuid)
              AND to_tsvector('english', d.text) @@ plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :top_k
        """)

        result = await db.execute(sql, {
            "query": query,
            "kb_id": str(kb_id),
            "workspace_id": str(workspace_id),
            "top_k": self.top_k,
        })
        rows = result.fetchall()

        results = [
            RetrievalResult(
                chunk_id=str(row.chunk_id),
                document_id=str(row.document_id),
                doc_filename=row.doc_filename,
                text=row.text,
                score=float(row.score),
                page_number=row.page_number,
                chunk_index=row.chunk_index,
            )
            for row in rows
        ]

        logger.debug("Full-text retrieval returned %d results for query: %s", len(results), query[:50])
        return results
