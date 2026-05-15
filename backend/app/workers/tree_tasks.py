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
from app.core.database import AsyncSessionLocal
from app.services.document.extractor import extract_text

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

            # Extract text
            text = extract_text(doc.file_path, doc.file_type)

            # Resolve LLM provider from workspace config (falls back to Bedrock)
            from app.services.llm.factory import get_llm_provider
            from app.services.pageindex.tree_builder import build_tree as _build_tree_via_builder
            provider = await get_llm_provider(doc.workspace_id, db)

            # Use tree_builder for the tree (handles chunking for large docs)
            tree_json = await _build_tree_via_builder(
                doc.file_path, doc.file_type, doc.filename, provider, doc_id=document_id,
            )
            # Generate insights separately (summary only needs a representative excerpt)
            insights = await _generate_insights(provider, text, doc.filename)

            # Persist tree
            existing = await db.execute(
                select(DocumentTree).where(DocumentTree.document_id == doc_uuid)
            )
            doc_tree = existing.scalar_one_or_none()

            if doc_tree is None:
                doc_tree = DocumentTree(
                    document_id=doc_uuid,
                    tree_json=tree_json,
                    llm_model_used=provider.model,
                    token_count=0,
                    **insights,
                )
                db.add(doc_tree)
            else:
                doc_tree.tree_json = tree_json
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


async def _generate_tree_and_insights(provider, text: str, filename: str) -> tuple[dict, dict]:
    """
    Generate both tree structure and insights in a single LLM call for better performance.
    Returns (tree_json, insights_dict).
    """
    system_prompt = (
        "You are a document analysis assistant. Analyze the document and return a JSON object with two keys:\n"
        "1. 'tree': hierarchical structure with nodes (node_id, title, page_start, page_end, depth, text, children)\n"
        "2. 'insights': object with executive_summary (string), key_entities (object with people/organizations/dates/amounts arrays), "
        "document_tags (array), complexity_score (float 0.0-1.0)\n"
        "Return ONLY valid JSON, no explanation."
    )
    
    messages = [
        {
            "role": "user",
            "content": f"Document: {filename}\n\n{text[:8000]}",  # truncate for token limits
        }
    ]

    try:
        response = await provider.complete(messages, system_prompt=system_prompt)
        
        # Parse JSON from LLM response
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        combined_data = json.loads(content)
        
        # Extract tree and insights
        tree_data = combined_data.get("tree", {})
        insights_raw = combined_data.get("insights", {})
        
        # Validate tree structure
        if not tree_data or "nodes" not in tree_data:
            raise ValueError("Invalid tree structure")
        
        insights = {
            "executive_summary": insights_raw.get("executive_summary", f"Summary of {filename}"),
            "key_entities": insights_raw.get("key_entities", {"people": [], "organizations": [], "dates": [], "amounts": []}),
            "document_tags": insights_raw.get("document_tags", ["General"]),
            "complexity_score": float(insights_raw.get("complexity_score", 0.5)),
        }
        
        return tree_data, insights
        
    except Exception as exc:
        logger.warning("Combined generation failed, using fallback", extra={"error": str(exc)})
        # Fallback to separate calls
        tree_data = await _generate_tree(provider, text, filename)
        insights = await _generate_insights(provider, text, filename)
        return tree_data, insights


async def _generate_tree(provider, text: str, filename: str) -> dict:
    """Send document text to LLM and parse hierarchical tree JSON."""
    system_prompt = (
        "You are a document structure analyzer. Given document text, produce a hierarchical "
        "JSON tree representing the document's structure. Each node must have: "
        "node_id (string), title (string), page_start (int), page_end (int), "
        "depth (int, starting at 1), text (string excerpt), children (array). "
        "Return ONLY valid JSON, no explanation."
    )
    messages = [
        {
            "role": "user",
            "content": f"Document: {filename}\n\n{text[:8000]}",  # truncate for token limits
        }
    ]

    response = await provider.complete(messages, system_prompt=system_prompt)

    # Parse JSON from LLM response
    try:
        # Strip markdown code fences if present
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        tree_data = json.loads(content)
    except (json.JSONDecodeError, IndexError):
        # Fallback: create minimal tree structure
        tree_data = {
            "doc_id": "unknown",
            "title": filename,
            "nodes": [
                {
                    "node_id": "n1",
                    "title": "Full Document",
                    "page_start": 1,
                    "page_end": 1,
                    "depth": 1,
                    "text": text[:500],
                    "children": [],
                }
            ],
        }

    return tree_data


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
