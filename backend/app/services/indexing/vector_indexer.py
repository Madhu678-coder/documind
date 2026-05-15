"""Vector indexer: embeds chunks and stores them in the document_chunks table."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.embedding.provider import EmbeddingProvider

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 50


class VectorIndexer:
    """
    Embeds document chunks in batches and stores them in the document_chunks table.
    """

    def __init__(self, embedding_provider: "EmbeddingProvider"):
        self.embedding_provider = embedding_provider

    async def index_chunks(
        self,
        chunks: list[dict],
        document_id: uuid.UUID | str,
        kb_id: uuid.UUID | str,
        workspace_id: uuid.UUID | str,
        db: "AsyncSession",
    ) -> int:
        """
        Embed chunks in batches and persist them to the database.

        Args:
            chunks: List of chunk dicts from a splitter (text, char_start, char_end, etc.)
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

        # Build a map from chunk_index to parent DocumentChunk id for parent-child strategy
        # We need to do a first pass to create parent chunks (no embedding), then child chunks
        parent_index_map: dict[int, uuid.UUID] = {}

        # First pass: identify and create parent chunks (those with parent_chunk_index = None)
        # These are stored without embeddings first so children can reference them
        parent_chunks = [c for c in chunks if c.get("parent_chunk_index") is None]
        child_chunks = [c for c in chunks if c.get("parent_chunk_index") is not None]

        # If no parent/child distinction (recursive strategy), all chunks are treated as independent
        all_need_embedding = not child_chunks  # True for recursive strategy

        if child_chunks:
            # Parent-child strategy: store parents first without embeddings
            for chunk in parent_chunks:
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
                    embedding=None,
                )
                db.add(db_chunk)
                await db.flush()  # get the id
                parent_index_map[chunk["chunk_index"]] = db_chunk.id

            # Now embed children in batches
            texts_to_embed = [c["text"] for c in child_chunks]
            embeddings: list[list[float]] = []
            for i in range(0, len(texts_to_embed), _EMBED_BATCH_SIZE):
                batch = texts_to_embed[i:i + _EMBED_BATCH_SIZE]
                result = await self.embedding_provider.embed_texts(batch)
                embeddings.extend(result.embeddings)
                logger.debug("Embedded batch %d/%d", i + _EMBED_BATCH_SIZE, len(texts_to_embed))

            for chunk, embedding in zip(child_chunks, embeddings):
                parent_idx = chunk.get("parent_chunk_index")
                parent_db_id = parent_index_map.get(parent_idx) if parent_idx is not None else None
                db_chunk = DocumentChunk(
                    document_id=doc_id,
                    kb_id=kb_uuid,
                    workspace_id=ws_uuid,
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    char_start=chunk.get("char_start", 0),
                    char_end=chunk.get("char_end", 0),
                    page_number=chunk.get("page_number", 1),
                    parent_chunk_id=parent_db_id,
                    chunk_metadata=chunk.get("metadata", {}),
                    embedding=embedding,
                )
                db.add(db_chunk)

        else:
            # Recursive strategy: embed all chunks
            texts_to_embed = [c["text"] for c in chunks]
            embeddings = []
            for i in range(0, len(texts_to_embed), _EMBED_BATCH_SIZE):
                batch = texts_to_embed[i:i + _EMBED_BATCH_SIZE]
                result = await self.embedding_provider.embed_texts(batch)
                embeddings.extend(result.embeddings)
                logger.debug("Embedded batch %d/%d", i + _EMBED_BATCH_SIZE, len(texts_to_embed))

            for chunk, embedding in zip(chunks, embeddings):
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
                    embedding=embedding,
                )
                db.add(db_chunk)

        await db.commit()
        logger.info("Indexed %d chunks for document %s", len(chunks), document_id)
        return len(chunks)
