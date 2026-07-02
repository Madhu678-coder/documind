"""Document upload and listing API endpoints."""
import uuid
import logging
from typing import Optional

try:
    import magic as _magic
    _MAGIC_AVAILABLE = True
except (ImportError, OSError):
    _magic = None  # type: ignore[assignment]
    _MAGIC_AVAILABLE = False

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.schemas.documents import DocumentOut, DocumentUploadResponse
from app.services.document.storage import FileStorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}

# Magic bytes signatures for supported types
MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "pdf": [b"%PDF"],
    "docx": [b"PK\x03\x04"],  # ZIP-based (OOXML)
    "txt": [],   # no reliable magic bytes — accept any
    "md": [],    # no reliable magic bytes — accept any
}

MIME_TO_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}


# ── Validation helpers ────────────────────────────────────────────────────────

def _detect_extension(file_bytes: bytes, declared_mime: str) -> str:
    """
    Validate file using both MIME whitelist and magic bytes inspection.
    Returns the canonical extension on success.
    Raises HTTPException 422 on mismatch or unsupported type.
    """
    # 1. Check declared MIME type
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File type '{declared_mime}' is not allowed. Accepted: PDF, DOCX, TXT, MD.",
        )

    ext = MIME_TO_EXT[declared_mime]

    # 2. Magic bytes inspection (skip for txt/md — no reliable signature)
    signatures = MAGIC_SIGNATURES.get(ext, [])
    if signatures:
        if not any(file_bytes.startswith(sig) for sig in signatures):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"File content does not match declared type '{declared_mime}'. "
                    "Magic bytes validation failed."
                ),
            )

    # 3. Cross-check with python-magic for extra confidence
    if _MAGIC_AVAILABLE:
        try:
            detected_mime = _magic.from_buffer(file_bytes[:2048], mime=True)
            if detected_mime not in ALLOWED_MIME_TYPES and detected_mime not in (
                "application/octet-stream",
                "application/zip",  # DOCX is a ZIP
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Magic bytes inspection detected '{detected_mime}' "
                        f"but declared type is '{declared_mime}'."
                    ),
                )
        except HTTPException:
            raise
        except Exception as exc:
            # python-magic failure is non-fatal — log and continue
            logger.warning("python-magic detection failed", extra={"error": str(exc)})

    return ext


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
)
async def upload_document(
    kb_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document into a KnowledgeBase.

    - Validates MIME type + magic bytes (422 on failure)
    - Rejects files > 50 MB (413)
    - Rejects kb_id from another workspace (403)
    - Stores file, creates document record, enqueues tree build task
    """
    # 1. Read file content
    file_bytes = await file.read()

    # 2. Size check
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of 50 MB.",
        )

    # 3. MIME + magic bytes validation
    declared_mime = file.content_type or "application/octet-stream"
    ext = _detect_extension(file_bytes, declared_mime)

    # 4. KB workspace isolation check
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()

    if kb is None or kb.workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="KnowledgeBase not found in your workspace.",
        )

    # 5. Store file (async for better performance)
    storage = FileStorageService()
    file_path = await storage.store_async(file_bytes, file.filename or f"upload.{ext}", str(current_user.workspace_id))

    # 6. Create document record
    doc = Document(
        workspace_id=current_user.workspace_id,
        kb_id=kb_id,
        filename=file.filename or f"upload.{ext}",
        file_path=file_path,
        file_type=ext,
        size_bytes=len(file_bytes),
        status=DocumentStatus.processing,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.flush()  # get doc.id before commit

    # 7. Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="document.upload",
        resource_type="document",
        resource_id=doc.id,
        log_metadata={
            "filename": doc.filename,
            "file_type": ext,
            "size_bytes": len(file_bytes),
            "kb_id": str(kb_id),
        },
    )
    db.add(audit)
    await db.commit()
    await db.refresh(doc)

    # 8. Enqueue Celery task based on KB rag_mode (import here to avoid circular imports)
    try:
        rag_mode = kb.settings.get("rag_mode", "pageindex") if kb.settings else "pageindex"
        if rag_mode == "vector":
            from app.workers.index_tasks import index_document
            index_document.delay(str(doc.id), kb.settings)
        elif rag_mode == "wiki":
            from app.workers.wiki_tasks import build_wiki_pages
            build_wiki_pages.delay(str(doc.id))
        elif rag_mode == "graph":
            from app.workers.graph_tasks import build_document_graph
            build_document_graph.delay(str(doc.id))
        elif rag_mode == "openkb":
            from app.workers.openkb_tasks import build_openkb_pages
            build_openkb_pages.delay(str(doc.id))
        else:
            from app.workers.tree_tasks import build_document_tree
            build_document_tree.delay(str(doc.id))
    except Exception as exc:
        logger.error("Failed to enqueue indexing task", extra={"doc_id": str(doc.id), "error": str(exc)})
        # Don't fail the request — task can be retried manually

    logger.info("Document uploaded", extra={"doc_id": str(doc.id), "kb_id": str(kb_id)})

    return DocumentUploadResponse(
        document_id=doc.id,
        status=doc.status,
        filename=doc.filename,
        kb_id=doc.kb_id,
    )


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    kb_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents in the current workspace, optionally filtered by kb_id."""
    from sqlalchemy import func
    from app.models.document_chunk import DocumentChunk

    query = select(Document).where(Document.workspace_id == current_user.workspace_id)
    if kb_id is not None:
        query = query.where(Document.kb_id == kb_id)
    result = await db.execute(query.order_by(Document.created_at.desc()))
    docs = result.scalars().all()

    # Fetch chunk counts for all docs in one query
    if docs:
        doc_ids = [d.id for d in docs]
        chunk_count_result = await db.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id).label("cnt"))
            .where(DocumentChunk.document_id.in_(doc_ids))
            .group_by(DocumentChunk.document_id)
        )
        chunk_counts = {str(row.document_id): row.cnt for row in chunk_count_result.all()}
    else:
        chunk_counts = {}

    # Build response with chunk_count attached
    out = []
    for doc in docs:
        doc_out = DocumentOut.model_validate(doc)
        doc_out.chunk_count = chunk_counts.get(str(doc.id))
        out.append(doc_out)
    return out


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document by ID, scoped to the current workspace."""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == current_user.workspace_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return doc


@router.get("/{doc_id}/file")
async def get_document_file(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream the raw file bytes for a document (PDF viewer, download)."""
    from fastapi.responses import Response as FastAPIResponse
    import boto3

    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == current_user.workspace_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    from app.core.config import settings as _settings

    # Try S3/LocalStack first
    if _settings.s3_bucket:
        try:
            session_kwargs = {}
            if _settings.aws_endpoint_url:
                session_kwargs["aws_access_key_id"] = "test"
                session_kwargs["aws_secret_access_key"] = "test"
            elif _settings.aws_profile:
                session_kwargs["profile_name"] = _settings.aws_profile
            session = boto3.Session(**session_kwargs)
            client_kwargs = {"region_name": _settings.aws_region}
            if _settings.aws_endpoint_url:
                client_kwargs["endpoint_url"] = _settings.aws_endpoint_url
            s3 = session.client("s3", **client_kwargs)
            obj = s3.get_object(Bucket=_settings.s3_bucket, Key=doc.file_path)
            file_bytes = obj["Body"].read()
        except Exception as exc:
            logger.error("S3 file fetch failed", extra={"doc_id": str(doc_id), "error": str(exc)})
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in storage.")
    else:
        from pathlib import Path
        path = Path(doc.file_path)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk.")
        file_bytes = path.read_bytes()

    mime_map = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain", "md": "text/markdown"}
    media_type = mime_map.get(doc.file_type.lower(), "application/octet-stream")

    return FastAPIResponse(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all its related data (tree, chunks, etc.)."""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == current_user.workspace_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Delete related records (order matters for foreign keys)
    from app.models.document_tree import DocumentTree
    from app.models.document_chunk import DocumentChunk

    await db.execute(select(DocumentTree).where(DocumentTree.document_id == doc_id))
    tree = (await db.execute(select(DocumentTree).where(DocumentTree.document_id == doc_id))).scalar_one_or_none()
    if tree:
        await db.delete(tree)

    # Delete chunks
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))

    # Delete the document itself
    await db.delete(doc)
    await db.commit()

    # Try to delete from S3 (best effort)
    try:
        from app.services.document.storage import FileStorageService
        storage = FileStorageService()
        storage.delete(doc.file_path)
    except Exception:
        pass  # S3 cleanup is best-effort

    logger.info("Document deleted", extra={"doc_id": str(doc_id)})
