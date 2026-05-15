"""Celery tasks for vector RAG document indexing (chunking + embedding)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10  # seconds


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)


@celery_app.task(
    bind=True,
    name="app.workers.index_tasks.index_document",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def index_document(self: Task, document_id: str, kb_settings: dict[str, Any]) -> dict:
    """
    Chunk and embed a document for vector RAG.

    Steps:
    1. Load document from DB
    2. Extract text
    3. Create chunks using ChunkerFactory
    4. Create EmbeddingProvider from kb_settings
    5. Index chunks (vector, fulltext, or both based on index_method)
    6. Update document status = ready

    Retry policy: max 3 retries with exponential backoff (10s, 20s, 40s).
    """
    try:
        return _run_async(_index_document_async(document_id, kb_settings))
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded for index_document", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning(
            "index_document failed, retrying",
            extra={"document_id": document_id, "attempt": attempt, "delay": delay, "error": str(exc)},
        )
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for index_document", extra={"document_id": document_id})
            _run_async(_mark_failed(document_id, str(exc)))
            raise


async def _index_document_async(document_id: str, kb_settings: dict[str, Any]) -> dict:
    """Core async logic for vector document indexing."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    from app.models.document import Document, DocumentStatus
    from app.core.config import settings
    from app.services.document.extractor import extract_text
    from app.services.chunking.factory import ChunkerFactory
    from app.services.embedding.factory import EmbeddingFactory

    doc_uuid = uuid.UUID(document_id)

    # Fresh engine per task (avoids asyncpg connection pool reuse across event loops)
    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with TaskSession() as db:
            # 1. Load document
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            # 2. Extract text
            text = extract_text(doc.file_path, doc.file_type)

            # 3. Create chunker
            chunk_strategy = kb_settings.get("chunk_strategy", "recursive")
            chunk_size = int(kb_settings.get("chunk_size", 1000))
            chunk_overlap = int(kb_settings.get("chunk_overlap", 200))
            chunker = ChunkerFactory.create(chunk_strategy, chunk_size, chunk_overlap)

            # 4. Chunk the document
            chunks = chunker(text)
            if not chunks:
                logger.warning("No chunks produced for document %s", document_id)
                doc.status = DocumentStatus.ready
                await db.commit()
                return {"document_id": document_id, "status": "ready", "chunks": 0}

            logger.info("Produced %d chunks for document %s", len(chunks), document_id)

            # 5. Index based on index_method
            index_method = kb_settings.get("index_method", "high_quality")
            embedding_provider_name = kb_settings.get("embedding_provider", "bedrock")
            embedding_model = kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0")
            api_key = kb_settings.get("embedding_api_key")  # optional for non-Bedrock

            total_indexed = 0

            if index_method in ("high_quality", "hybrid"):
                # Vector indexing (with embeddings)
                emb_provider = EmbeddingFactory.create(
                    embedding_provider_name,
                    embedding_model,
                    api_key=api_key,
                )
                from app.services.indexing.vector_indexer import VectorIndexer
                indexer = VectorIndexer(emb_provider)
                total_indexed = await indexer.index_chunks(
                    chunks,
                    document_id=doc.id,
                    kb_id=doc.kb_id,
                    workspace_id=doc.workspace_id,
                    db=db,
                )

            if index_method in ("economical", "hybrid") and index_method != "high_quality":
                # Full-text only indexing (skip if already done vector indexing for hybrid)
                from app.services.indexing.fulltext_indexer import FullTextIndexer
                fts_indexer = FullTextIndexer()
                if index_method == "economical":
                    total_indexed = await fts_indexer.index_chunks(
                        chunks,
                        document_id=doc.id,
                        kb_id=doc.kb_id,
                        workspace_id=doc.workspace_id,
                        db=db,
                    )
                # For hybrid, vector indexer already stored the chunks; FTS index is automatic via GIN

            # 6. Mark document as ready
            doc.status = DocumentStatus.ready
            await db.commit()

    finally:
        await task_engine.dispose()

    # Push WebSocket event
    await _push_ws_event(document_id, "ready")

    logger.info("Vector indexing completed for document %s (%d chunks)", document_id, total_indexed)
    return {"document_id": document_id, "status": "ready", "chunks": total_indexed}


async def _mark_failed(document_id: str, error_detail: str) -> None:
    """Set document status to failed."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    from app.models.document import Document, DocumentStatus
    from app.core.config import settings

    doc_uuid = uuid.UUID(document_id)
    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with TaskSession() as db:
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = DocumentStatus.failed
                await db.commit()
    finally:
        await task_engine.dispose()

    await _push_ws_event(document_id, "failed", error=error_detail)


async def _push_ws_event(document_id: str, status: str, **extra) -> None:
    """Push a WebSocket event to the frontend via Redis pub/sub."""
    import json
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings

        r = aioredis.from_url(settings.redis_url)
        payload = json.dumps({
            "type": "document.status",
            "document_id": document_id,
            "status": status,
            **extra,
        })
        await r.publish(f"ws:document:{document_id}", payload)
        await r.aclose()
    except Exception as exc:
        logger.warning("Failed to push WebSocket event", extra={"error": str(exc)})
