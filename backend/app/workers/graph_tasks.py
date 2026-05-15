"""Celery task for GraphRAG document ingestion — builds knowledge graph from documents."""
from __future__ import annotations

import asyncio
import logging
import uuid

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app
from app.services.document.extractor import extract_text

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10


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
    name="app.workers.graph_tasks.build_document_graph",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def build_document_graph(self: Task, document_id: str) -> dict:
    """
    Build/update knowledge graph for a newly uploaded document.

    Retry policy: max 3 retries with exponential backoff.
    On success: graph nodes/edges created, document status → ready.
    On exhaustion: document status → failed.
    """
    try:
        return _run_async(_build_graph_async(document_id))
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded for graph build", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning(
            "build_document_graph failed, retrying",
            extra={"document_id": document_id, "attempt": attempt, "delay": delay, "error": str(exc)},
        )
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for graph build", extra={"document_id": document_id})
            _run_async(_mark_failed(document_id, str(exc)))
            raise


async def _build_graph_async(document_id: str) -> dict:
    """Core async logic for graph building."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.document import Document, DocumentStatus
    from app.core.config import settings
    from app.services.llm.factory import get_llm_provider
    from app.services.embedding.factory import EmbeddingFactory
    from app.services.graph.graph_builder import build_graph

    doc_uuid = uuid.UUID(document_id)

    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with TaskSession() as db:
            # Load document
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            # Extract text
            text = extract_text(doc.file_path, doc.file_type)
            if len(text.strip()) < 100:
                logger.info("Document text too short for graph extraction", extra={"document_id": document_id})
                doc.status = DocumentStatus.ready
                await db.commit()
                return {"document_id": document_id, "status": "ready", "nodes_created": 0}

            # Get LLM and embedding providers
            provider = await get_llm_provider(doc.workspace_id, db)

            # Use Bedrock Titan for embeddings (same as vector RAG)
            from app.models.knowledge_base import KnowledgeBase
            kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id))
            kb = kb_result.scalar_one()
            kb_settings = kb.settings or {}

            embedding_provider = EmbeddingFactory.create(
                kb_settings.get("embedding_provider", "bedrock"),
                kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
            )

            # Build graph
            stats = await build_graph(
                provider=provider,
                embedding_provider=embedding_provider,
                text=text,
                filename=doc.filename,
                doc_id=document_id,
                kb_id=str(doc.kb_id),
                workspace_id=str(doc.workspace_id),
                db=db,
            )

            # Mark document ready
            doc.status = DocumentStatus.ready
            await db.commit()

    finally:
        await task_engine.dispose()

    # Push WebSocket event
    await _push_ws_event(document_id, "ready")

    logger.info(
        "Document graph built successfully",
        extra={"document_id": document_id, **stats},
    )
    return {"document_id": document_id, "status": "ready", **stats}


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
    """Push a WebSocket event via Redis pub/sub."""
    import json
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings

        r = aioredis.from_url(settings.redis_url)
        payload = json.dumps({"type": "document.status", "document_id": document_id, "status": status, **extra})
        await r.publish(f"ws:document:{document_id}", payload)
        await r.aclose()
    except Exception as exc:
        logger.warning("Failed to push WebSocket event", extra={"error": str(exc)})
