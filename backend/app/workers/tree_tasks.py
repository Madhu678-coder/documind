"""Celery tasks for document tree building and auto-insights generation."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Retry policy: 2^attempt * 10s → 10s, 20s, 40s
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
    name="app.workers.tree_tasks.build_document_tree",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def build_document_tree(self: Task, document_id: str) -> dict:
    """
    Build a hierarchical PageIndex tree for a document.

    Retry policy: max 3 retries with exponential backoff (10s, 20s, 40s).
    On success: persists tree_json, sets status=ready, generates auto-insights.
    On exhaustion: sets status=failed, stores error detail.
    """
    try:
        return _run_async(_build_tree_async(document_id))
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded for document", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning(
            "build_document_tree failed, retrying",
            extra={"document_id": document_id, "attempt": attempt, "delay": delay, "error": str(exc)},
        )
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for document", extra={"document_id": document_id})
            _run_async(_mark_failed(document_id, str(exc)))
            raise


async def _build_tree_async(document_id: str) -> dict:
    """Core async logic for tree building."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.document import Document, DocumentStatus
    from app.models.document_tree import DocumentTree
    from app.core.config import settings

    doc_uuid = uuid.UUID(document_id)

    # Create a fresh engine per task — avoids asyncpg connection pool reuse
    # across different event loops (which causes InterfaceError in Celery workers)
    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with TaskSession() as db:
            # Load document
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            # Resolve LLM provider and use the PageIndex pipeline
            from app.services.llm.factory import get_llm_provider
            from app.services.pageindex.tree_builder import build_tree as _build_tree_via_builder
            provider = await get_llm_provider(doc.workspace_id, db)

            # ── Download file from S3 to a local temp path if needed ──────────
            # page_extractor uses pymupdf/markitdown which require a real path.
            # When S3_BUCKET is set, doc.file_path is an S3 key, not a local path.
            import tempfile
            import os as _os
            actual_file_path = doc.file_path
            temp_path: str | None = None

            if settings.s3_bucket:
                try:
                    from aiobotocore.session import get_session as _get_session
                    _session = _get_session()
                    _client_kwargs: dict = {"region_name": settings.aws_region}
                    if settings.aws_endpoint_url:
                        _client_kwargs["endpoint_url"] = settings.aws_endpoint_url
                    async with _session.create_client("s3", **_client_kwargs) as _s3:
                        _obj = await _s3.get_object(Bucket=settings.s3_bucket, Key=doc.file_path)
                        _file_bytes = await _obj["Body"].read()
                    _suffix = f".{doc.file_type.lower()}" if doc.file_type else ""
                    with tempfile.NamedTemporaryFile(mode="wb", suffix=_suffix, delete=False) as _tmp:
                        _tmp.write(_file_bytes)
                        temp_path = _tmp.name
                    actual_file_path = temp_path
                    logger.info(
                        "Downloaded file from S3 to temp path",
                        extra={"s3_key": doc.file_path, "temp": temp_path},
                    )
                except Exception as _exc:
                    logger.error("S3 download failed", extra={"error": str(_exc)})
                    raise

            try:
                tree_json, source_pages = await _build_tree_via_builder(
                    file_path=actual_file_path,
                    file_type=doc.file_type,
                    filename=doc.filename,
                    llm=provider,
                    doc_id=document_id,
                )
            finally:
                if temp_path and _os.path.exists(temp_path):
                    _os.unlink(temp_path)
                    logger.debug("Removed temp file", extra={"path": temp_path})

            # Generate insights from first page content (no extra LLM call for full text)
            first_pages_text = " ".join(
                p.get("content", "") for p in (source_pages[:5] if source_pages else [])
            )
            insights = await _generate_insights(provider, first_pages_text or "", doc.filename)

            # Persist tree
            existing = await db.execute(
                select(DocumentTree).where(DocumentTree.document_id == doc_uuid)
            )
            doc_tree = existing.scalar_one_or_none()

            if doc_tree is None:
                doc_tree = DocumentTree(
                    document_id=doc_uuid,
                    tree_json=tree_json,
                    source_pages=source_pages,
                    page_count=len(source_pages) if source_pages else None,
                    llm_model_used=provider.model,
                    token_count=0,
                    **insights,
                )
                db.add(doc_tree)
            else:
                doc_tree.tree_json = tree_json
                doc_tree.source_pages = source_pages
                doc_tree.page_count = len(source_pages) if source_pages else None
                doc_tree.llm_model_used = provider.model
                for k, v in insights.items():
                    setattr(doc_tree, k, v)

            # Update document status
            doc.status = DocumentStatus.ready
            await db.commit()
    finally:
        await task_engine.dispose()

    # Push WebSocket event
    await _push_ws_event(document_id, "ready")

    logger.info("Document tree built successfully", extra={"document_id": document_id})
    return {"document_id": document_id, "status": "ready"}


async def _generate_insights(provider, text: str, filename: str) -> dict:
    """Generate executive summary, key entities, tags, and complexity score using Claude."""
    import json as _json

    prompt = (
        f"Analyze this document and return a JSON object with:\n"
        f"- executive_summary: 5-bullet summary as a string\n"
        f"- key_entities: object with keys people, organizations, dates, amounts (each an array of strings)\n"
        f"- document_tags: array of category tags (Legal, Financial, Technical, HR, etc.)\n"
        f"- complexity_score: float 0.0-1.0\n\n"
        f"Document: {filename}\n\n{text[:4000]}\n\nReturn ONLY valid JSON."
    )

    try:
        response = await provider.complete(
            [{"role": "user", "content": prompt}],
            system_prompt="You are a document analysis assistant. Return only valid JSON.",
        )
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        insights_data = _json.loads(content)
    except Exception as exc:
        logger.warning("Insights generation failed, using defaults", extra={"error": str(exc)})
        insights_data = {}

    return {
        "executive_summary": insights_data.get("executive_summary", f"Summary of {filename}"),
        "key_entities": insights_data.get("key_entities", {"people": [], "organizations": [], "dates": [], "amounts": []}),
        "document_tags": insights_data.get("document_tags", ["General"]),
        "complexity_score": float(insights_data.get("complexity_score", 0.5)),
    }


async def _mark_failed(document_id: str, error_detail: str) -> None:
    """Set document status to failed and store error detail."""
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
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings

        r = aioredis.from_url(settings.redis_url)
        payload = json.dumps({"type": "document.status", "document_id": document_id, "status": status, **extra})
        await r.publish(f"ws:document:{document_id}", payload)
        await r.aclose()
    except Exception as exc:
        logger.warning("Failed to push WebSocket event", extra={"error": str(exc)})
