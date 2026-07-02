"""Celery task for OpenKB RAG mode — exact OpenKB ingestion pipeline.

Steps (mirrors OpenKB's _add_single_file_locked):
  1. Download file from S3 / local storage to a temp directory.
  2. For PDFs: count pages with pymupdf.
     - Pages < threshold  → short doc → convert with pymupdf/markitdown.
     - Pages >= threshold → long doc  → index with PageIndexClient.
  3. Run compile_short_doc_db() or compile_long_doc_db() (exact OpenKB prompts).
  4. Persist CompileResult to openkb_pages table.
  5. Rebuild __index__ page.
  6. Mark document ready, push WebSocket event.

pageindex_threshold defaults to 20 pages (configurable per-KB via
kb.settings["pageindex_threshold"]).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10
_DEFAULT_THRESHOLD = 20   # pages — matches OpenKB's DEFAULT_CONFIG["pageindex_threshold"]


# ---------------------------------------------------------------------------
# Celery entry point
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.workers.openkb_tasks.build_openkb_pages",
    queue="default",
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def build_openkb_pages(self: Task, document_id: str) -> dict:
    """Build OpenKB wiki pages for a newly uploaded document."""
    try:
        return _run_async(_build_async(document_id))
    except MaxRetriesExceededError:
        logger.error("OpenKB: max retries exceeded", extra={"document_id": document_id})
        _run_async(_mark_failed(document_id, "Max retries exceeded"))
        raise
    except Exception as exc:
        attempt = self.request.retries
        delay = (2 ** attempt) * _RETRY_BASE_DELAY
        logger.warning(
            "OpenKB build failed, retrying",
            extra={"document_id": document_id, "attempt": attempt, "error": str(exc)},
        )
        try:
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            _run_async(_mark_failed(document_id, str(exc)))
            raise


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)

# ---------------------------------------------------------------------------
# Document conversion helpers — mirrors OpenKB's converter.py
# ---------------------------------------------------------------------------


def _get_pdf_page_count(pdf_path: str) -> int:
    """Count PDF pages using pymupdf — identical to OpenKB get_pdf_page_count."""
    import pymupdf  # type: ignore[import]
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def _convert_pdf_short(pdf_path: str, doc_name: str, images_dir: Path) -> str:
    """Convert short PDF to markdown with text + inline images.

    Uses pymupdf get_text() as primary extraction (most reliable),
    dict-mode only for image extraction.
    Falls back to pdfplumber if pymupdf returns insufficient text.
    """
    import pymupdf  # type: ignore[import]

    images_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    img_counter = 0
    _MIN_DIM = 32

    with pymupdf.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1

            # Primary: simple get_text() — most reliable for encoded fonts
            text = page.get_text("text", flags=~pymupdf.TEXT_PRESERVE_LIGATURES).strip()
            if not text:
                # Try without any flags
                text = page.get_text().strip()

            if text:
                parts.append(f"[Page {page_num}]\n{text}")

            # Extract images separately via dict-mode (doesn't affect text)
            try:
                for block in page.get_text("dict")["blocks"]:
                    if block["type"] != 1:
                        continue
                    if block.get("width", 0) < _MIN_DIM or block.get("height", 0) < _MIN_DIM:
                        continue
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pix = pymupdf.Pixmap(image_bytes)
                        if pix.n > 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_counter += 1
                        filename = f"p{page_num}_img{img_counter}.png"
                        (images_dir / filename).write_bytes(pix.tobytes("png"))
                        parts.append(f"![image](sources/images/{doc_name}/{filename})")
                    except Exception:
                        pass
            except Exception:
                pass

    result = "\n\n".join(parts)

    # If pymupdf still gives very little text, fall back to pdfplumber
    if len(result.strip()) < 100:
        logger.info(
            "OpenKB: pymupdf gave %d chars for %s, trying pdfplumber",
            len(result.strip()), doc_name,
        )
        try:
            import pdfplumber
            plumber_parts: list[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    if text.strip():
                        plumber_parts.append(f"[Page {i}]\n{text.strip()}")
            if plumber_parts:
                plumber_text = "\n\n".join(plumber_parts)
                logger.info(
                    "OpenKB: pdfplumber extracted %d chars for %s",
                    len(plumber_text), doc_name,
                )
                if len(plumber_text.strip()) > len(result.strip()):
                    result = plumber_text
        except Exception as exc:
            logger.warning("OpenKB: pdfplumber fallback failed for %s: %s", doc_name, exc)

    if result.strip():
        logger.info("OpenKB: final extracted text length: %d chars for %s", len(result.strip()), doc_name)
    return result


def _convert_pdf_to_pages(pdf_path: str, doc_name: str, images_dir: Path) -> list[dict]:
    """Convert PDF to per-page dicts for PageIndex source storage.

    Returns [{"page": int, "content": str, "images": [{"path": str}]}].
    Mirrors OpenKB's images.convert_pdf_to_pages().
    """
    import pymupdf  # type: ignore[import]

    images_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    img_counter = 0
    _MIN_DIM = 32

    with pymupdf.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1
            text_parts: list[str] = []
            page_images: list[dict] = []

            for block in page.get_text("dict")["blocks"]:
                if block["type"] == 0:
                    text_parts.append(
                        "\n".join(
                            "".join(span["text"] for span in line["spans"])
                            for line in block["lines"]
                        )
                    )
                elif block["type"] == 1:
                    if block.get("width", 0) < _MIN_DIM or block.get("height", 0) < _MIN_DIM:
                        continue
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pix = pymupdf.Pixmap(image_bytes)
                        if pix.n > 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_counter += 1
                        filename = f"p{page_num}_img{img_counter}.png"
                        (images_dir / filename).write_bytes(pix.tobytes("png"))
                        page_images.append({"path": f"sources/images/{doc_name}/{filename}"})
                    except Exception:
                        pass

            pages.append({
                "page": page_num,
                "content": "\n".join(text_parts),
                "images": page_images,
            })
    return pages


def _convert_with_markitdown(file_path: str) -> str:
    """Convert DOCX, PPTX, HTML, XLSX, CSV, etc. to markdown using markitdown.

    Mirrors OpenKB's MarkItDown usage for non-PDF, non-MD files.
    """
    try:
        from markitdown import MarkItDown  # type: ignore[import]
        mid = MarkItDown()
        result = mid.convert(file_path)
        return result.text_content or ""
    except ImportError:
        # Fallback: use documind's existing text extractor
        from app.services.document.extractor import extract_text
        from pathlib import Path as _Path
        p = _Path(file_path)
        return extract_text(file_path, p.suffix.lstrip("."))

# ---------------------------------------------------------------------------
# PageIndex integration for long docs — mirrors OpenKB's indexer.py
# ---------------------------------------------------------------------------


def _index_long_doc_pageindex(
    pdf_path: str,
    doc_name: str,
    images_dir: Path,
    storage_path: str,
    model: str,
) -> tuple[str, str, str, list[dict]]:
    """Index a long PDF with PageIndex.

    Returns (doc_id, description, summary_md, per_page_data).
    Mirrors OpenKB's index_long_document().
    """
    try:
        from pageindex import IndexConfig, PageIndexClient  # type: ignore[import]
    except ImportError:
        logger.warning("OpenKB: pageindex package not available — falling back to full text")
        return "", "", "", []

    api_key = os.environ.get("PAGEINDEX_API_KEY", "")
    index_config = IndexConfig(
        if_add_node_text=True,
        if_add_node_summary=True,
        if_add_doc_description=True,
    )

    # ── Format model for LiteLLM (which PageIndex uses internally) ──────────
    # LiteLLM needs "bedrock/model-id" format, not the bare Bedrock model ID.
    # We also need to set AWS credentials as env vars so LiteLLM can find them.
    litellm_model = model
    if not litellm_model.startswith(("bedrock/", "anthropic/", "openai/",
                                     "gemini/", "gpt-", "claude-")):
        # Likely a bare Bedrock model ID — prepend the provider prefix
        litellm_model = f"bedrock/{model}"

    # Expose AWS credentials to LiteLLM (reads env vars, not boto3 profile)
    from app.core.config import settings as _cfg
    if _cfg.aws_profile and not os.environ.get("AWS_ACCESS_KEY_ID"):
        # Try to read credentials from the AWS profile via boto3 and expose them
        try:
            import boto3
            session_kwargs: dict = {"profile_name": _cfg.aws_profile} if _cfg.aws_profile else {}
            _boto_session = boto3.Session(**session_kwargs)
            _creds = _boto_session.get_credentials()
            if _creds:
                resolved = _creds.resolve()
                os.environ.setdefault("AWS_ACCESS_KEY_ID", resolved.access_key or "")
                os.environ.setdefault("AWS_SECRET_ACCESS_KEY", resolved.secret_key or "")
                if resolved.token:
                    os.environ.setdefault("AWS_SESSION_TOKEN", resolved.token)
        except Exception as exc:
            logger.warning("OpenKB: could not expose Bedrock creds to LiteLLM: %s", exc)

    os.environ.setdefault("AWS_REGION_NAME", _cfg.aws_bedrock_region or _cfg.aws_region)
    client = PageIndexClient(
        api_key=api_key or None,
        model=litellm_model,      # LiteLLM format: "bedrock/model-id"
        storage_path=storage_path,
        index_config=index_config,
    )
    col = client.collection()

    # Add PDF — retry 3 times (PageIndex TOC is stochastic)
    doc_id = None
    for attempt in range(1, 4):
        try:
            doc_id = col.add(pdf_path)
            break
        except Exception as exc:
            if attempt == 3:
                raise RuntimeError(f"PageIndex failed after 3 attempts: {exc}") from exc

    doc = col.get_document(doc_id, include_text=True)
    description: str = doc.get("doc_description", "")
    structure: list = doc.get("structure", [])

    # Build summary markdown from tree structure
    from app.services.openkb._tree_renderer import render_summary_md
    tree = {"doc_name": doc_name, "doc_description": description, "structure": structure}
    summary_md = render_summary_md(tree, doc_name, doc_id, description=description)

    # Per-page content
    per_page: list[dict] = []
    if api_key:
        try:
            page_count = _get_pdf_page_count(pdf_path)
            raw = col.get_page_content(doc_id, f"1-{page_count}")
            per_page = _normalize_pages(raw)
        except Exception as exc:
            logger.warning("OpenKB: PageIndex cloud pages failed: %s", exc)

    if not per_page:
        per_page = _convert_pdf_to_pages(pdf_path, doc_name, images_dir)

    return doc_id, description, summary_md, per_page


def _normalize_pages(raw_pages) -> list[dict]:
    if not isinstance(raw_pages, list):
        return []
    pages = []
    for i, item in enumerate(raw_pages, 1):
        if isinstance(item, str):
            if item.strip():
                pages.append({"page": i, "content": item.strip(), "images": []})
            continue
        if not isinstance(item, dict):
            continue
        page_num = item.get("page", item.get("page_number", i))
        try:
            page_num = int(page_num)
        except (TypeError, ValueError):
            page_num = i
        content = str(item.get("content", item.get("markdown", item.get("text", ""))) or "").strip()
        images = [img for img in (item.get("images") or []) if isinstance(img, dict)]
        if content or images:
            pages.append({"page": page_num, "content": content, "images": images})
    return pages

# ---------------------------------------------------------------------------
# Image upload + path-fixing helpers
# ---------------------------------------------------------------------------


def _upload_images_to_s3(
    images_dir: Path,
    doc_name: str,
    kb_id: str,
) -> dict[str, str]:
    """Upload all PNG images from images_dir to S3.

    Returns a path-replacement map:
      "sources/images/{doc_name}/{filename}" → "/api/v1/knowledge-bases/{kb_id}/openkb/images/{doc_name}/{filename}"

    Images are stored in S3 under key:
      openkb/{kb_id}/{doc_name}/{filename}

    This mirrors OpenKB's wiki/sources/images/{doc_name}/ but stored in S3
    instead of on disk, served via the openkb images API endpoint.
    """
    if not images_dir.exists():
        return {}

    from app.core.config import settings

    if not settings.s3_bucket:
        logger.warning("OpenKB: no S3 bucket configured — images will not be persisted")
        return {}

    import boto3

    session_kwargs: dict = {}
    if settings.aws_endpoint_url:
        session_kwargs = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}
    elif settings.aws_profile:
        session_kwargs = {"profile_name": settings.aws_profile}

    boto_session = boto3.Session(**session_kwargs)
    client_kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        client_kwargs["endpoint_url"] = settings.aws_endpoint_url
    s3 = boto_session.client("s3", **client_kwargs)

    path_map: dict[str, str] = {}
    for img_file in sorted(images_dir.glob("*.png")):
        filename = img_file.name
        original_path = f"sources/images/{doc_name}/{filename}"
        s3_key = f"openkb/{kb_id}/{doc_name}/{filename}"
        api_path = f"/api/v1/knowledge-bases/{kb_id}/openkb/images/{doc_name}/{filename}"
        try:
            with img_file.open("rb") as fh:
                s3.put_object(
                    Bucket=settings.s3_bucket,
                    Key=s3_key,
                    Body=fh.read(),
                    ContentType="image/png",
                )
            path_map[original_path] = api_path
            logger.debug("OpenKB: uploaded image %s → %s", filename, s3_key)
        except Exception as exc:
            logger.warning("OpenKB: image upload failed for %s: %s", filename, exc)

    return path_map


def _fix_content_image_paths(content: str, path_map: dict[str, str]) -> str:
    """Replace local image paths in markdown content with API paths."""
    for original, api_path in path_map.items():
        content = content.replace(original, api_path)
    return content


def _fix_page_data_image_paths(per_page_data: list[dict], path_map: dict[str, str]) -> list[dict]:
    """Replace local image paths in per-page JSON dicts (for pageindex docs)."""
    if not path_map:
        return per_page_data
    fixed: list[dict] = []
    for page in per_page_data:
        content = _fix_content_image_paths(page.get("content", ""), path_map)
        images = [
            {"path": path_map.get(img.get("path", ""), img.get("path", ""))}
            for img in page.get("images", [])
            if isinstance(img, dict)
        ]
        fixed.append({**page, "content": content, "images": images})
    return fixed


async def _build_async(document_id: str) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.document import Document, DocumentStatus
    from app.models.knowledge_base import KnowledgeBase
    from app.models.openkb_page import OpenKBPage
    from app.services.llm.factory import get_llm_provider
    from app.services.openkb.compiler import (
        CompileResult, PageData, build_index_content,
        compile_long_doc_db, compile_short_doc_db,
        _sanitize_concept_name,
    )

    doc_uuid = uuid.UUID(document_id)
    engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            # --- Load document ---
            doc_res = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = doc_res.scalar_one_or_none()
            if doc is None:
                raise ValueError(f"Document {document_id} not found")

            kb_res = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id))
            kb = kb_res.scalar_one()
            kb_settings = kb.settings or {}
            threshold = int(kb_settings.get("pageindex_threshold", _DEFAULT_THRESHOLD))

            provider = await get_llm_provider(doc.workspace_id, db)
            language = kb_settings.get("language", "en")
            doc_name = _sanitize_concept_name(doc.filename.rsplit(".", 1)[0])
            file_type = doc.file_type.lower()

            # --- Load existing pages for this KB ---
            existing_res = await db.execute(
                select(OpenKBPage).where(OpenKBPage.kb_id == doc.kb_id)
            )
            existing_pages = existing_res.scalars().all()

            # --- Download file to temp directory ---
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = await _download_file(doc, tmpdir)
                images_dir = Path(tmpdir) / "images" / doc_name
                pageindex_storage = tmpdir

                is_long_doc = False
                source_text = ""
                summary_md = ""
                per_page_data: list[dict] = []
                doc_id_pi = ""
                doc_description = ""

                # --- Short/Long detection (mirrors OpenKB converter.py) ---
                if file_type == "pdf":
                    page_count = await asyncio.get_event_loop().run_in_executor(
                        None, _get_pdf_page_count, tmp_path
                    )
                    logger.info(
                        "OpenKB: PDF %s has %d pages (threshold=%d)",
                        doc.filename, page_count, threshold,
                    )
                    if page_count >= threshold:
                        is_long_doc = True
                    else:
                        # Short PDF: convert with pymupdf
                        source_text = await asyncio.get_event_loop().run_in_executor(
                            None, _convert_pdf_short, tmp_path, doc_name, images_dir,
                        )
                elif file_type == "md":
                    source_text = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
                else:
                    # DOCX, PPTX, HTML, XLSX, CSV, TXT → markitdown
                    source_text = await asyncio.get_event_loop().run_in_executor(
                        None, _convert_with_markitdown, tmp_path,
                    )

                if len((source_text or "").strip()) < 30 and not is_long_doc:
                    logger.info("OpenKB: text too short, skipping: %s", doc.filename)
                    doc.status = DocumentStatus.ready
                    await db.commit()
                    await _push_ws_event(document_id, "ready")
                    return {"document_id": document_id, "status": "ready", "pages_created": 0}

                # --- Long doc: index with PageIndex ---
                if is_long_doc:
                    doc_id_pi, doc_description, summary_md, per_page_data = (
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            _index_long_doc_pageindex,
                            tmp_path, doc_name, images_dir,
                            pageindex_storage, provider.model,
                        )
                    )
                    if not summary_md:
                        # PageIndex unavailable — fall back to full text extraction
                        logger.warning("OpenKB: PageIndex unavailable, falling back to short-doc for %s", doc.filename)
                        from app.services.document.extractor import extract_text
                        source_text = extract_text(doc.file_path, file_type)
                        is_long_doc = False

                # --- Upload extracted images to S3 and fix paths in content ---
                path_map: dict[str, str] = {}
                if images_dir.exists() and any(images_dir.glob("*.png")):
                    path_map = await asyncio.get_event_loop().run_in_executor(
                        None,
                        _upload_images_to_s3,
                        images_dir, doc_name, str(doc.kb_id),
                    )
                    if path_map:
                        logger.info(
                            "OpenKB: uploaded %d image(s) to S3 for %s",
                            len(path_map), doc_name,
                        )
                        # Fix paths in short-doc markdown
                        if source_text:
                            source_text = _fix_content_image_paths(source_text, path_map)
                        # Fix paths in long-doc per-page JSON
                        if per_page_data:
                            per_page_data = _fix_page_data_image_paths(per_page_data, path_map)
                        # Fix paths in long-doc summary markdown
                        if summary_md:
                            summary_md = _fix_content_image_paths(summary_md, path_map)

                # --- Compile ---
                if is_long_doc:
                    result: CompileResult = await compile_long_doc_db(
                        provider=provider,
                        doc_name=doc_name,
                        summary_md=summary_md,
                        doc_id=doc_id_pi or document_id,
                        existing_pages=existing_pages,
                        doc_description=doc_description,
                        language=language,
                    )
                else:
                    result = await compile_short_doc_db(
                        provider=provider,
                        doc_name=doc_name,
                        source_text=source_text,
                        doc_id=document_id,
                        existing_pages=existing_pages,
                        language=language,
                    )

            # tmpdir cleaned up here — images are only needed during indexing

            # --- Persist pages to DB ---
            pages_created, pages_updated = await _persist_result(
                db, result, doc, per_page_data, existing_pages, provider.model
            )

            # --- Rebuild index page ---
            await _rebuild_index(db, doc.kb_id, doc.workspace_id, provider.model)

            # --- Ensure AGENTS.md wiki page exists (created once per KB) ---
            await _ensure_agents_page(db, doc.kb_id, doc.workspace_id)

            doc.status = DocumentStatus.ready
            await db.commit()

    finally:
        await engine.dispose()

    await _push_ws_event(document_id, "ready")
    logger.info(
        "OpenKB: document compiled — %s created, %s updated",
        pages_created, pages_updated,
    )
    return {
        "document_id": document_id,
        "status": "ready",
        "pages_created": pages_created,
        "pages_updated": pages_updated,
    }

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def _download_file(doc, tmpdir: str) -> str:
    """Download document file to tmpdir and return local path."""
    import boto3
    from app.core.config import settings

    dest = os.path.join(tmpdir, f"doc.{doc.file_type}")
    if settings.s3_bucket:
        try:
            session_kwargs: dict = {}
            if settings.aws_endpoint_url:
                session_kwargs = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}
            elif settings.aws_profile:
                session_kwargs = {"profile_name": settings.aws_profile}
            session = boto3.Session(**session_kwargs)
            client_kwargs: dict = {"region_name": settings.aws_region}
            if settings.aws_endpoint_url:
                client_kwargs["endpoint_url"] = settings.aws_endpoint_url
            s3 = session.client("s3", **client_kwargs)
            s3.download_file(settings.s3_bucket, doc.file_path, dest)
            return dest
        except Exception:
            pass

    # Local fallback
    from pathlib import Path as _P
    local = _P(doc.file_path)
    if local.exists():
        import shutil
        shutil.copy2(local, dest)
        return dest

    raise FileNotFoundError(f"Cannot download file for document {doc.id}")


async def _persist_result(
    db,
    result,
    doc,
    per_page_data: list[dict],
    existing_pages: list,
    model: str,
) -> tuple[int, int]:
    from app.models.openkb_page import OpenKBPage

    pages_by_id = {str(p.id): p for p in existing_pages}
    pages_created = pages_updated = 0

    for page_data in result.all_pages:
        doc_id_str = str(doc.id)

        if page_data.is_update and page_data.existing_id:
            row = pages_by_id.get(page_data.existing_id)
            if row:
                row.content = page_data.content
                row.summary = page_data.description or row.summary
                row.page_type = page_data.page_type
                row.doc_type = page_data.doc_type
                src_ids = list(row.source_doc_ids or [])
                if doc_id_str not in src_ids:
                    src_ids.append(doc_id_str)
                row.source_doc_ids = src_ids
                row.llm_model_used = model
                # Store per-page data on long-doc summary pages
                if page_data.page_category == "summary" and per_page_data:
                    row.source_data = per_page_data
                pages_updated += 1
                continue

        # Create new row
        new_row = OpenKBPage(
            kb_id=doc.kb_id,
            workspace_id=doc.workspace_id,
            title=page_data.title,
            page_category=page_data.page_category,
            page_type=page_data.page_type,
            doc_type=page_data.doc_type,
            summary=page_data.description,
            content=page_data.content,
            source_doc_ids=[doc_id_str],
            related_titles=[],
            llm_model_used=model,
            source_data=per_page_data if page_data.page_category == "summary" and per_page_data else None,
        )
        db.add(new_row)
        pages_created += 1

    await db.flush()
    return pages_created, pages_updated


async def _ensure_agents_page(db, kb_id, workspace_id) -> None:
    """Create the __agents__ page (AGENTS.md) once per KB if it doesn't exist yet.

    Mirrors OpenKB's wiki/AGENTS.md — defines the wiki schema so the query
    agent (and humans browsing the wiki) understand the structure.
    """
    from sqlalchemy import select
    from app.models.openkb_page import OpenKBPage
    from app.services.openkb.compiler import FULL_AGENTS_MD

    existing = await db.execute(
        select(OpenKBPage).where(
            OpenKBPage.kb_id == kb_id,
            OpenKBPage.title == "__agents__",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return  # Already exists — only create once

    db.add(OpenKBPage(
        kb_id=kb_id,
        workspace_id=workspace_id,
        title="__agents__",
        page_category="schema",
        page_type="schema",
        summary="Wiki schema and structure definition (AGENTS.md).",
        content=FULL_AGENTS_MD,
        source_doc_ids=[],
        related_titles=[],
        llm_model_used=None,
    ))
    logger.info("OpenKB: created AGENTS.md (__agents__) page for KB %s", kb_id)


async def _rebuild_index(db, kb_id, workspace_id, model: str) -> None:
    """Rebuild the __index__ page from all current pages."""
    from sqlalchemy import select
    from app.models.openkb_page import OpenKBPage
    from app.services.openkb.compiler import build_index_content

    all_res = await db.execute(
        select(OpenKBPage).where(OpenKBPage.kb_id == kb_id)
    )
    all_pages = all_res.scalars().all()
    content_pages = [p for p in all_pages if p.page_category != "index"]
    index_content = build_index_content(content_pages)

    index_row = next((p for p in all_pages if p.title == "__index__"), None)
    if index_row:
        index_row.content = index_content
    else:
        db.add(OpenKBPage(
            kb_id=kb_id,
            workspace_id=workspace_id,
            title="__index__",
            page_category="index",
            page_type="index",
            summary="Knowledge base index",
            content=index_content,
            source_doc_ids=[],
            related_titles=[],
            llm_model_used=model,
        ))


async def _mark_failed(document_id: str, error_detail: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.document import Document, DocumentStatus
    from app.core.config import settings

    engine = create_async_engine(settings.database_url, echo=False, pool_size=1, max_overflow=0)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            res = await db.execute(
                select(Document).where(Document.id == uuid.UUID(document_id))
            )
            doc = res.scalar_one_or_none()
            if doc:
                doc.status = DocumentStatus.failed
                await db.commit()
    finally:
        await engine.dispose()
    await _push_ws_event(document_id, "failed", error=error_detail)


async def _push_ws_event(document_id: str, status: str, **extra) -> None:
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings
        r = aioredis.from_url(settings.redis_url)
        payload = json.dumps({"type": "document.status", "document_id": document_id, "status": status, **extra})
        await r.publish(f"ws:document:{document_id}", payload)
        await r.aclose()
    except Exception as exc:
        logger.warning("OpenKB: WS push failed: %s", exc)
