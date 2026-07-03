"""Celery task for Wiki RAG document ingestion — builds/updates LLM-maintained wiki pages.

Implements the full Karpathy LLM Wiki pattern:
  - compile: extract concept pages + connection pages → merge into KB → update index → append log
  - update_related_pages_async: background cross-page propagation
"""
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
_WIKI_PAGE_CAP = 100


def _run_async(coro):
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
    name="app.workers.wiki_tasks.build_wiki_pages",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def build_wiki_pages(self: Task, document_id: str) -> dict:
    """Build/update LLM wiki pages for a newly uploaded document."""
    try:
        return _run_async(_build_wiki_async(document_id))
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded for wiki build", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning("build_wiki_pages failed, retrying",
                       extra={"document_id": document_id, "attempt": attempt, "delay": delay, "error": str(exc)})
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded", extra={"document_id": document_id})
            _run_async(_mark_failed(document_id, str(exc)))
            raise


async def _build_wiki_async(document_id: str) -> dict:
    """Core async logic — full Karpathy compile pipeline."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.document import Document, DocumentStatus
    from app.models.wiki_page import WikiPage
    from app.core.config import settings
    from app.services.llm.factory import get_llm_provider
    from app.services.wiki.wiki_builder import (
        extract_pages, extract_connections, merge_page_content,
        add_frontmatter_to_page, get_frontmatter_created_date,
        build_index_content, build_log_entry, prepend_log_entry,
        inject_wikilinks, _INDEX_TITLE, _LOG_TITLE, _should_merge_by_context,
    )

    doc_uuid = uuid.UUID(document_id)
    task_engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    TaskSession = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)

    pages_created = 0
    pages_merged = 0

    try:
        async with TaskSession() as db:
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            text = extract_text(doc.file_path, doc.file_type)
            if len(text.strip()) < 100:
                logger.info("Document text too short for wiki extraction, marking ready",
                            extra={"document_id": document_id})
                doc.status = DocumentStatus.ready
                await db.commit()
                await _push_ws_event(document_id, "ready")
                return {"document_id": document_id, "status": "ready", "pages_created": 0}

            provider = await get_llm_provider(doc.workspace_id, db)

            # Load all existing KB pages (excluding structural index/log pages)
            existing_result = await db.execute(
                select(WikiPage).where(WikiPage.kb_id == doc.kb_id)
            )
            all_existing = existing_result.scalars().all()
            content_pages = [p for p in all_existing if p.page_type not in ("index", "log")]
            existing_map = {p.title.lower(): p for p in content_pages}
            index_page = next((p for p in all_existing if p.title == _INDEX_TITLE), None)
            log_page = next((p for p in all_existing if p.title == _LOG_TITLE), None)
            existing_count = len(content_pages)

            # ── Step 1: Extract concept/entity/process pages ──────────────────
            new_pages_data = await extract_pages(provider, text, doc.filename)
            if not new_pages_data:
                new_pages_data = [{
                    "title": doc.filename.rsplit(".", 1)[0],
                    "page_type": "general",
                    "summary": f"Content from {doc.filename}",
                    "content": f"## {doc.filename}\n\n{text[:2000]}",
                    "related_titles": [],
                }]

            # ── Step 2: Extract connection pages ─────────────────────────────
            connection_pages_data = await extract_connections(provider, new_pages_data)
            all_new_pages_data = new_pages_data + connection_pages_data

            # ── Step 3: Merge or create each page ─────────────────────────────
            import asyncio as _asyncio

            merge_candidates = []
            truly_new = []
            for page_data in all_new_pages_data:
                title_key = page_data["title"].lower()
                existing = existing_map.get(title_key)
                if existing:
                    merge_candidates.append((page_data, existing))
                else:
                    truly_new.append(page_data)

            # Parallel merges
            if merge_candidates:
                merge_tasks = [merge_page_content(provider, ex.content, pd["content"])
                               for pd, ex in merge_candidates]
                merged_contents = await _asyncio.gather(*merge_tasks)

                for (page_data, existing), merged_content in zip(merge_candidates, merged_contents):
                    created_date = get_frontmatter_created_date(existing.content)
                    existing.content = add_frontmatter_to_page(
                        merged_content, existing.title, existing.page_type,
                        list(existing.source_doc_ids or []), created=created_date,
                    )
                    existing.summary = page_data.get("summary") or existing.summary
                    src_ids = list(existing.source_doc_ids or [])
                    if str(doc.id) not in src_ids:
                        src_ids.append(str(doc.id))
                    existing.source_doc_ids = src_ids
                    existing_related = set(existing.related_titles or [])
                    existing_related.update(page_data.get("related_titles", []))
                    existing.related_titles = sorted(existing_related)
                    existing.llm_model_used = provider.model
                    pages_merged += 1

                    if existing.related_titles:
                        update_related_pages_async.delay(
                            str(doc.kb_id), str(doc.workspace_id),
                            existing.title, existing.summary or "",
                            page_data["content"][:2000],
                            list(existing.related_titles),
                        )

            # Create new pages with frontmatter
            for page_data in truly_new:
                if existing_count >= _WIKI_PAGE_CAP:
                    logger.info("Wiki page cap reached", extra={"title": page_data["title"]})
                    continue
                content_with_fm = add_frontmatter_to_page(
                    page_data["content"], page_data["title"],
                    page_data.get("page_type", "general"), [str(doc.id)],
                )
                new_page = WikiPage(
                    kb_id=doc.kb_id,
                    workspace_id=doc.workspace_id,
                    title=page_data["title"],
                    summary=page_data.get("summary"),
                    content=content_with_fm,
                    page_type=page_data.get("page_type", "general"),
                    source_doc_ids=[str(doc.id)],
                    related_titles=page_data.get("related_titles", []),
                    llm_model_used=provider.model,
                )
                db.add(new_page)
                existing_map[page_data["title"].lower()] = new_page
                existing_count += 1
                pages_created += 1

            await db.flush()

            # ── Step 4: Rebuild the index page ────────────────────────────────
            # Re-query to get all pages including newly added ones
            all_pages_result = await db.execute(
                select(WikiPage).where(
                    WikiPage.kb_id == doc.kb_id,
                    WikiPage.page_type.notin_(["index", "log"]),
                )
            )
            all_content_pages = all_pages_result.scalars().all()
            index_content = build_index_content(all_content_pages)

            if index_page:
                index_page.content = index_content
                index_page.summary = f"{len(all_content_pages)} articles"
            else:
                index_page = WikiPage(
                    kb_id=doc.kb_id, workspace_id=doc.workspace_id,
                    title=_INDEX_TITLE, summary=f"{len(all_content_pages)} articles",
                    content=index_content, page_type="index",
                    source_doc_ids=[], related_titles=[],
                    llm_model_used=provider.model,
                )
                db.add(index_page)

            # ── Step 5: Append to log page ────────────────────────────────────
            log_entry = build_log_entry(f"compile | {doc.filename}", {
                "document_id": document_id,
                "pages_created": pages_created,
                "pages_merged": pages_merged,
                "connection_pages": len(connection_pages_data),
                "total_pages": len(all_content_pages),
            })

            if log_page:
                log_page.content = prepend_log_entry(log_page.content, log_entry)
            else:
                from app.services.wiki.wiki_builder import generate_frontmatter, _LOG_TITLE as _LT
                fm = generate_frontmatter(_LT, "log", [], tags=["structural"])
                log_page = WikiPage(
                    kb_id=doc.kb_id, workspace_id=doc.workspace_id,
                    title=_LOG_TITLE, summary="Build log",
                    content=fm + "\n\n# Build Log\n\n*(newest entries first)*\n\n" + log_entry,
                    page_type="log",
                    source_doc_ids=[], related_titles=[],
                    llm_model_used=provider.model,
                )
                db.add(log_page)

            doc.status = DocumentStatus.ready
            await db.commit()

    finally:
        await task_engine.dispose()

    await _push_ws_event(document_id, "ready")
    logger.info("Wiki pages built successfully",
                extra={"document_id": document_id, "created": pages_created, "merged": pages_merged})
    return {"document_id": document_id, "status": "ready",
            "pages_created": pages_created, "pages_merged": pages_merged,
            "connection_pages": len(connection_pages_data) if 'connection_pages_data' in dir() else 0}


async def _mark_failed(document_id: str, error_detail: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.document import Document, DocumentStatus
    from app.core.config import settings
    doc_uuid = uuid.UUID(document_id)
    engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = DocumentStatus.failed
                await db.commit()
    finally:
        await engine.dispose()
    await _push_ws_event(document_id, "failed", error=error_detail)


async def _push_ws_event(document_id: str, status: str, **extra) -> None:
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


@celery_app.task(
    bind=True,
    name="app.workers.wiki_tasks.update_related_pages_async",
    queue="default",
    max_retries=1,
    acks_late=True,
)
def update_related_pages_async(
    self, kb_id: str, workspace_id: str,
    updated_title: str, updated_summary: str,
    new_info_snippet: str, related_titles: list[str],
) -> dict:
    """Background: update related wiki pages after a merge. Non-blocking."""
    try:
        return _run_async(_update_related_async(
            kb_id, workspace_id, updated_title, updated_summary, new_info_snippet, related_titles
        ))
    except Exception as exc:
        logger.warning("Cross-page update task failed", extra={"error": str(exc)})
        return {"updated": 0, "error": str(exc)}


async def _update_related_async(
    kb_id: str, workspace_id: str,
    updated_title: str, updated_summary: str,
    new_info_snippet: str, related_titles: list[str],
) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.models.wiki_page import WikiPage
    from app.core.config import settings
    from app.services.llm.factory import get_llm_provider
    from app.services.wiki.wiki_builder import update_related_page

    kb_uuid = uuid.UUID(kb_id)
    ws_uuid = uuid.UUID(workspace_id)
    engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    updated_count = 0

    try:
        async with Session() as db:
            provider = await get_llm_provider(ws_uuid, db)
            for related_title in related_titles[:3]:
                result = await db.execute(
                    select(WikiPage).where(WikiPage.kb_id == kb_uuid, WikiPage.title == related_title)
                )
                rp = result.scalar_one_or_none()
                if not rp:
                    continue
                updated_content = await update_related_page(
                    provider, rp.content, rp.title,
                    updated_title, updated_summary, new_info_snippet,
                )
                if updated_content != rp.content:
                    rp.content = updated_content
                    updated_count += 1
            await db.commit()
    finally:
        await engine.dispose()

    return {"updated": updated_count}
