"""Celery task for Wiki RAG document ingestion — builds/updates LLM-maintained wiki pages."""
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
_RETRY_BASE_DELAY = 10  # seconds — actual delays: 10s, 20s, 40s
_WIKI_PAGE_CAP = 100    # Max pages per KB to control LLM costs


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


def _extract_domain(filename: str) -> str:
    """
    Extract the document 'domain' from a filename for merge decisions.
    Examples:
      'Domestic_Travel_Policy.pdf' → 'domestic travel'
      'International_Travel_Policy.pdf' → 'international travel'
      'Leave_Policy.pdf' → 'leave'
      'Laptop_Policy.pdf' → 'laptop'
    """
    # Remove extension and split by underscores/hyphens
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Replace separators with spaces and lowercase
    name = name.replace("_", " ").replace("-", " ").lower()
    # Remove common suffixes that don't indicate domain
    for suffix in ["policy", "document", "guide", "manual", "handbook", "report"]:
        name = name.replace(suffix, "").strip()
    return name.strip()


def _should_merge_by_context(existing_source_docs: list[str], new_doc_filename: str) -> bool:
    """
    Determine if a wiki page should be merged based on document context.

    Logic: The context-aware extraction prompt already prefixes document-specific
    titles (e.g. "Domestic Travel - Mode of Travel"). If two pages have the SAME
    title despite this prompt, they're genuinely the same topic and should merge.

    We only reject merges when the new document is clearly from a different domain
    AND the existing page was sourced from a single document (not already cross-doc).
    
    For now: always merge when titles match. The extraction prompt is the primary
    defense against wrong merges.
    """
    # If the existing page already has multiple source documents, it's a shared topic — merge
    if len(existing_source_docs) > 1:
        return True

    # Default: trust the extraction prompt's context-aware titles
    return True


@celery_app.task(
    bind=True,
    name="app.workers.wiki_tasks.build_wiki_pages",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def build_wiki_pages(self: Task, document_id: str) -> dict:
    """
    Build/update LLM-maintained wiki pages for a newly uploaded document.

    Retry policy: max 3 retries with exponential backoff (10s, 20s, 40s).
    On success: wiki pages created/updated, document status → ready.
    On exhaustion: document status → failed.
    """
    try:
        return _run_async(_build_wiki_async(document_id))
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded for wiki build", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning(
            "build_wiki_pages failed, retrying",
            extra={"document_id": document_id, "attempt": attempt, "delay": delay, "error": str(exc)},
        )
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for wiki build", extra={"document_id": document_id})
            _run_async(_mark_failed(document_id, str(exc)))
            raise


async def _build_wiki_async(document_id: str) -> dict:
    """Core async logic for wiki page building."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.document import Document, DocumentStatus
    from app.models.wiki_page import WikiPage
    from app.core.config import settings
    from app.services.llm.factory import get_llm_provider
    from app.services.wiki.wiki_builder import extract_pages, merge_page_content

    doc_uuid = uuid.UUID(document_id)

    # Fresh engine per task — avoids asyncpg pool reuse across event loops
    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with TaskSession() as db:
            # Load document
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            # Skip extraction if text too short (empty/corrupt files)
            text = extract_text(doc.file_path, doc.file_type)
            if len(text.strip()) < 100:
                logger.info(
                    "Document text too short for wiki extraction, marking ready",
                    extra={"document_id": document_id},
                )
                doc.status = DocumentStatus.ready
                await db.commit()
                await _push_ws_event(document_id, "ready")
                return {"document_id": document_id, "status": "ready", "pages_created": 0}

            # Resolve LLM provider from workspace config
            provider = await get_llm_provider(doc.workspace_id, db)

            # Load existing wiki pages for this KB (merge key = lowercase title)
            existing_result = await db.execute(
                select(WikiPage).where(WikiPage.kb_id == doc.kb_id)
            )
            existing_pages = existing_result.scalars().all()
            existing_map = {p.title.lower(): p for p in existing_pages}
            existing_count = len(existing_pages)

            # Extract new pages from document
            new_pages_data = await extract_pages(provider, text, doc.filename)

            if not new_pages_data:
                # Fallback: create a single general page with filename as title
                new_pages_data = [{
                    "title": doc.filename.rsplit(".", 1)[0],
                    "page_type": "general",
                    "summary": f"Content from {doc.filename}",
                    "content": f"## {doc.filename}\n\n{text[:2000]}",
                    "related_titles": [],
                }]

            pages_created = 0
            pages_merged = 0

            # Separate pages into "needs merge check" vs "new"
            merge_candidates = []  # (page_data, existing_page)
            new_pages = []

            for page_data in new_pages_data:
                title_key = page_data["title"].lower()
                existing = existing_map.get(title_key)
                if existing:
                    merge_candidates.append((page_data, existing))
                else:
                    new_pages.append(page_data)

            # Merge check — document context rule (no LLM call, instant)
            # If the existing page came from a different document "domain" (filename prefix),
            # don't merge — create a separate page instead.
            merge_decisions = []
            for page_data, existing in merge_candidates:
                should_merge = _should_merge_by_context(
                    existing_source_docs=existing.source_doc_ids or [],
                    new_doc_filename=doc.filename,
                )
                merge_decisions.append(should_merge)

            # Parallel merges — run all confirmed merges concurrently
            import asyncio as _asyncio
            merge_tasks = []
            merge_indices = []  # track which candidates are being merged

            for i, (page_data, existing) in enumerate(merge_candidates):
                if merge_decisions[i]:
                    # Confirmed merge — schedule parallel LLM call
                    merge_tasks.append(
                        merge_page_content(provider, existing.content, page_data["content"])
                    )
                    merge_indices.append(i)
                else:
                    # Rejected merge — create as new page with disambiguated title
                    disambiguated_title = f"{page_data['title']} ({doc.filename.rsplit('.', 1)[0]})"
                    logger.info(
                        "Merge rejected — creating separate page",
                        extra={"original_title": page_data["title"], "new_title": disambiguated_title},
                    )
                    if existing_count < _WIKI_PAGE_CAP:
                        new_page = WikiPage(
                            kb_id=doc.kb_id,
                            workspace_id=doc.workspace_id,
                            title=disambiguated_title,
                            summary=page_data.get("summary"),
                            content=page_data["content"],
                            page_type=page_data.get("page_type", "general"),
                            source_doc_ids=[str(doc.id)],
                            related_titles=page_data.get("related_titles", []),
                            llm_model_used=provider.model,
                        )
                        db.add(new_page)
                        existing_map[disambiguated_title.lower()] = new_page
                        existing_count += 1
                        pages_created += 1

            # Execute all merges in parallel
            if merge_tasks:
                merged_contents = await _asyncio.gather(*merge_tasks)

                for idx, merged_content in zip(merge_indices, merged_contents):
                    page_data, existing = merge_candidates[idx]
                    existing.content = merged_content
                    existing.summary = page_data.get("summary") or existing.summary
                    src_ids = list(existing.source_doc_ids or [])
                    doc_id_str = str(doc.id)
                    if doc_id_str not in src_ids:
                        src_ids.append(doc_id_str)
                    existing.source_doc_ids = src_ids
                    existing_related = set(existing.related_titles or [])
                    existing_related.update(page_data.get("related_titles", []))
                    existing.related_titles = sorted(existing_related)
                    existing.llm_model_used = provider.model
                    pages_merged += 1

                    # Cross-page updates: fire as separate background task (non-blocking)
                    from app.workers.wiki_tasks import update_related_pages_async
                    if existing.related_titles:
                        update_related_pages_async.delay(
                            str(doc.kb_id),
                            str(doc.workspace_id),
                            existing.title,
                            existing.summary or "",
                            page_data["content"][:2000],
                            list(existing.related_titles or []),
                        )

            # Create genuinely new pages
            for page_data in new_pages:
                if existing_count >= _WIKI_PAGE_CAP:
                    logger.info(
                        "Wiki page cap reached, skipping new page creation",
                        extra={"kb_id": str(doc.kb_id), "title": page_data["title"]},
                    )
                    continue

                new_page = WikiPage(
                    kb_id=doc.kb_id,
                    workspace_id=doc.workspace_id,
                    title=page_data["title"],
                    summary=page_data.get("summary"),
                    content=page_data["content"],
                    page_type=page_data.get("page_type", "general"),
                    source_doc_ids=[str(doc.id)],
                    related_titles=page_data.get("related_titles", []),
                    llm_model_used=provider.model,
                )
                db.add(new_page)
                existing_map[page_data["title"].lower()] = new_page
                existing_count += 1
                pages_created += 1

            # Mark document ready
            doc.status = DocumentStatus.ready
            await db.commit()

    finally:
        await task_engine.dispose()

    await _push_ws_event(document_id, "ready")

    logger.info(
        "Wiki pages built successfully",
        extra={
            "document_id": document_id,
            "pages_created": pages_created,
            "pages_merged": pages_merged,
        },
    )
    return {
        "document_id": document_id,
        "status": "ready",
        "pages_created": pages_created,
        "pages_merged": pages_merged,
    }


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
    """Push a WebSocket event via Redis pub/sub (same as tree_tasks)."""
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


# ── Background Cross-Page Update Task ─────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.wiki_tasks.update_related_pages_async",
    queue="default",
    max_retries=1,
    acks_late=True,
)
def update_related_pages_async(
    self,
    kb_id: str,
    workspace_id: str,
    updated_title: str,
    updated_summary: str,
    new_info_snippet: str,
    related_titles: list[str],
) -> dict:
    """
    Background task: update related wiki pages after a merge.
    Runs after the document is already marked 'ready' — non-blocking.
    Limited to max 3 related pages to control LLM costs.
    """
    try:
        return _run_async(_update_related_async(
            kb_id, workspace_id, updated_title, updated_summary, new_info_snippet, related_titles
        ))
    except Exception as exc:
        logger.warning("Cross-page update task failed", extra={"error": str(exc)})
        return {"updated": 0, "error": str(exc)}


async def _update_related_async(
    kb_id: str,
    workspace_id: str,
    updated_title: str,
    updated_summary: str,
    new_info_snippet: str,
    related_titles: list[str],
) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.wiki_page import WikiPage
    from app.core.config import settings
    from app.services.llm.factory import get_llm_provider
    from app.services.wiki.wiki_builder import update_related_page

    kb_uuid = uuid.UUID(kb_id)
    ws_uuid = uuid.UUID(workspace_id)

    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    updated_count = 0
    # Limit to 3 related pages max
    titles_to_update = related_titles[:3]

    try:
        async with TaskSession() as db:
            provider = await get_llm_provider(ws_uuid, db)

            for related_title in titles_to_update:
                result = await db.execute(
                    select(WikiPage).where(
                        WikiPage.kb_id == kb_uuid,
                        WikiPage.title == related_title,
                    )
                )
                related_page = result.scalar_one_or_none()
                if not related_page:
                    continue

                updated_content = await update_related_page(
                    provider,
                    related_page_content=related_page.content,
                    related_page_title=related_page.title,
                    updated_page_title=updated_title,
                    updated_page_summary=updated_summary,
                    new_info_snippet=new_info_snippet,
                )

                if updated_content != related_page.content:
                    related_page.content = updated_content
                    updated_count += 1
                    logger.info(
                        "Cross-page update applied (background)",
                        extra={"updated_page": related_page.title, "triggered_by": updated_title},
                    )

            await db.commit()
    finally:
        await task_engine.dispose()

    return {"updated": updated_count, "related_titles_checked": len(titles_to_update)}
