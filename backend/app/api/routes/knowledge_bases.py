"""KnowledgeBase CRUD API endpoints."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.schemas.documents import DocumentOut
from app.schemas.knowledge_bases import (
    KnowledgeBaseCreate,
    KnowledgeBaseDetail,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services.kb_service import (
    assert_no_active_sessions,
    assert_unique_name,
    get_document_count,
    get_kb_or_403,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=KnowledgeBaseOut)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new KnowledgeBase scoped to the current user's workspace."""
    await assert_unique_name(body.name, current_user.workspace_id, db)

    kb = KnowledgeBase(
        workspace_id=current_user.workspace_id,
        name=body.name,
        description=body.description,
        created_by=current_user.id,
        settings=body.settings or {},
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)

    doc_count = await get_document_count(kb.id, db)
    logger.info("KnowledgeBase created", extra={"kb_id": str(kb.id)})

    return KnowledgeBaseOut(
        id=kb.id,
        workspace_id=kb.workspace_id,
        name=kb.name,
        description=kb.description,
        created_by=kb.created_by,
        created_at=kb.created_at,
        document_count=doc_count,
        settings=kb.settings or {},
    )


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all KnowledgeBases in the current workspace."""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == current_user.workspace_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    kbs = result.scalars().all()

    out = []
    for kb in kbs:
        doc_count = await get_document_count(kb.id, db)
        out.append(
            KnowledgeBaseOut(
                id=kb.id,
                workspace_id=kb.workspace_id,
                name=kb.name,
                description=kb.description,
                created_by=kb.created_by,
                created_at=kb.created_at,
                document_count=doc_count,
                settings=kb.settings or {},
            )
        )
    return out


@router.get("/{kb_id}", response_model=KnowledgeBaseDetail)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single KnowledgeBase with its document list."""
    kb = await get_kb_or_403(kb_id, current_user.workspace_id, db)

    doc_count = await get_document_count(kb.id, db)

    docs_result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb.id)
        .order_by(Document.created_at.desc())
    )
    docs = docs_result.scalars().all()

    return KnowledgeBaseDetail(
        id=kb.id,
        workspace_id=kb.workspace_id,
        name=kb.name,
        description=kb.description,
        created_by=kb.created_by,
        created_at=kb.created_at,
        settings=kb.settings or {},
        document_count=doc_count,
        documents=[
            {
                "id": str(d.id),
                "filename": d.filename,
                "file_type": d.file_type,
                "size_bytes": d.size_bytes,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ],
    )


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    current_user: User = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
):
    """Update a KnowledgeBase name, description, or settings. Requires Editor+ role."""
    kb = await get_kb_or_403(kb_id, current_user.workspace_id, db)

    if body.name is not None and body.name != kb.name:
        await assert_unique_name(body.name, current_user.workspace_id, db, exclude_id=kb_id)
        kb.name = body.name

    if body.description is not None:
        kb.description = body.description

    if body.settings is not None:
        kb.settings = body.settings

    await db.commit()
    await db.refresh(kb)

    doc_count = await get_document_count(kb.id, db)
    return KnowledgeBaseOut(
        id=kb.id,
        workspace_id=kb.workspace_id,
        name=kb.name,
        description=kb.description,
        created_by=kb.created_by,
        created_at=kb.created_at,
        document_count=doc_count,
        settings=kb.settings or {},
    )


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a KnowledgeBase and all associated data.
    - Deletes all eval results for messages in sessions linked to this KB
    - Deletes all chat messages in sessions linked to this KB
    - Deletes all chat sessions linked to this KB
    - Deletes all document files from S3
    - Deletes all document records from database
    - Deletes the KnowledgeBase record
    Requires Admin role.
    """
    from app.models.chat_session import ChatSession
    from app.models.chat_message import ChatMessage
    from app.models.eval_result import EvalResult
    from app.models.document_tree import DocumentTree
    from app.models.document_session_link import DocumentSessionLink
    
    logger.info("Delete KB request received", extra={"kb_id": str(kb_id), "user_id": str(current_user.id)})
    
    kb = await get_kb_or_403(kb_id, current_user.workspace_id, db)
    logger.info("KB found", extra={"kb_id": str(kb_id), "kb_name": kb.name})

    try:
        # Disable autoflush to prevent premature constraint checks
        with db.no_autoflush:
            # Get all documents in this KB first (needed for eval_results cleanup)
            docs_result = await db.execute(
                select(Document).where(Document.kb_id == kb_id)
            )
            documents = docs_result.scalars().all()
            doc_ids = [d.id for d in documents]
            logger.info("Found documents", extra={"kb_id": str(kb_id), "document_count": len(documents)})
            
            # Get all chat sessions linked to this KB
            sessions_result = await db.execute(
                select(ChatSession).where(ChatSession.kb_id == kb_id)
            )
            sessions = sessions_result.scalars().all()
            session_ids = [s.id for s in sessions]
            logger.info("Found chat sessions", extra={"kb_id": str(kb_id), "session_count": len(sessions)})
            
            # Get all chat messages in these sessions
            message_ids = []
            if session_ids:
                messages_result = await db.execute(
                    select(ChatMessage).where(ChatMessage.session_id.in_(session_ids))
                )
                messages = messages_result.scalars().all()
                message_ids = [m.id for m in messages]
                logger.info("Found chat messages", extra={"kb_id": str(kb_id), "message_count": len(messages)})
            
            # Delete ALL eval results at once (both message-based and document-based)
            # This must happen before deleting messages or documents
            eval_results_to_delete = []
            if message_ids or doc_ids:
                from sqlalchemy import or_
                conditions = []
                if message_ids:
                    conditions.append(EvalResult.message_id.in_(message_ids))
                if doc_ids:
                    conditions.append(EvalResult.document_id.in_(doc_ids))
                
                eval_results_result = await db.execute(
                    select(EvalResult).where(or_(*conditions))
                )
                eval_results_to_delete = eval_results_result.scalars().all()
                for eval_result in eval_results_to_delete:
                    await db.delete(eval_result)
                
                # CRITICAL: Flush the eval_results deletion to DB before deleting messages
                await db.flush()
                
                logger.info("Deleted all eval results", extra={"kb_id": str(kb_id), "eval_results_deleted": len(eval_results_to_delete)})
            
            # Now delete chat messages (safe now that eval_results are gone)
            if message_ids:
                for msg in messages:
                    await db.delete(msg)
                logger.info("Deleted chat messages", extra={"kb_id": str(kb_id), "messages_deleted": len(messages)})
            
            # Delete all chat sessions
            for session in sessions:
                await db.delete(session)
            if sessions:
                logger.info("Deleted chat sessions", extra={"kb_id": str(kb_id), "sessions_deleted": len(sessions)})

            # Delete document_session_links
            if doc_ids:
                doc_links_result = await db.execute(
                    select(DocumentSessionLink).where(DocumentSessionLink.document_id.in_(doc_ids))
                )
                doc_links = doc_links_result.scalars().all()
                for link in doc_links:
                    await db.delete(link)
                logger.info("Deleted document session links", extra={"kb_id": str(kb_id), "links_deleted": len(doc_links)})
                
                # Delete document trees
                doc_trees_result = await db.execute(
                    select(DocumentTree).where(DocumentTree.document_id.in_(doc_ids))
                )
                doc_trees = doc_trees_result.scalars().all()
                for tree in doc_trees:
                    await db.delete(tree)
                
                # CRITICAL: Flush document_trees deletion before deleting documents
                await db.flush()
                
                logger.info("Deleted document trees", extra={"kb_id": str(kb_id), "trees_deleted": len(doc_trees)})

            # Delete all documents
            for doc in documents:
                await db.delete(doc)
            logger.info("Deleted documents", extra={"kb_id": str(kb_id), "documents_deleted": len(documents)})

            # Delete the KB
            await db.delete(kb)
            logger.info("Deleted KB record", extra={"kb_id": str(kb_id)})
        
        # Now commit all deletions at once
        await db.commit()
        logger.info("Database commit successful", extra={"kb_id": str(kb_id)})
        
        # Delete files from S3 after successful DB commit
        if documents:
            from app.services.document.storage import FileStorageService
            storage = FileStorageService()
            
            for doc in documents:
                try:
                    storage.delete(doc.file_path)
                    logger.info("Deleted S3 file", extra={"file_path": doc.file_path, "doc_id": str(doc.id)})
                except Exception as exc:
                    logger.warning("Failed to delete S3 file", extra={"file_path": doc.file_path, "error": str(exc)})
        
        logger.info("KnowledgeBase deleted successfully", extra={"kb_id": str(kb_id), "documents_deleted": len(documents), "sessions_deleted": len(sessions)})
    
    except Exception as exc:
        logger.error("Failed to delete KB", extra={"kb_id": str(kb_id), "error": str(exc)}, exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete knowledge base: {str(exc)}"
        )
