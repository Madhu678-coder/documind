"""Full-text indexer: stores chunks without embeddings (FTS handled by Postgres tsvector)."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FullTextIndexer:
    """
    Stores document chunks without embeddings.
    Full-text search is handled by the GIN index on the tsvector column in Postgres.
    """

    async def index_chunks(
        self,
        chunks: list[dict],
        document_id: uuid.UUID | str,
        kb_id: uuid.UUID | str,
        workspace_id: uuid.UUID | str,
        db: "AsyncSession",
    ) -> int:
        """
        Store chunks in the database without embeddings.

        Args:
            chunks: List of chunk dicts from a splitter
            document_id: UUID of the source document
            kb_id: UUID of the knowledge base
            workspace_id: UUID of the workspace
            db: AsyncSession for DB writes

        Returns:
            Number of chunks indexed
        """
        from app.models.document_chunk import DocumentChunk

        doc_id = uuid.UUID(str(document_id))
        kb_uuid = uuid.UUID(str(kb_id))
        ws_uuid = uuid.UUID(str(workspace_id))

        for chunk in chunks:
            db_chunk = DocumentChunk(
                document_id=doc_id,
                kb_id=kb_uuid,
                workspace_id=ws_uuid,
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                char_start=chunk.get("char_start", 0),
                char_end=chunk.get("char_end", 0),
                page_number=chunk.get("page_number", 1),
                parent_chunk_id=None,
                chunk_metadata=chunk.get("metadata", {}),
                embedding=None,  # No embedding — FTS only
            )
            db.add(db_chunk)

        await db.commit()
        logger.info("Full-text indexed %d chunks for document %s", len(chunks), document_id)
        return len(chunks)
