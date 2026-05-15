"""Document insights API endpoint — supports both PageIndex (tree) and Vector RAG (chunks)."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_tree import DocumentTree
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/{doc_id}")
async def get_document_insights(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return insights for a document. Handles both PageIndex (tree) and Vector RAG (chunks)."""
    # Fetch the document
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Document not found"}},
        )

    if document.workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Access denied to this document"}},
        )

    # Determine rag_mode from the KB
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == document.kb_id))
    kb = kb_result.scalar_one_or_none()
    rag_mode = (kb.settings or {}).get("rag_mode", "pageindex") if kb else "pageindex"

    if rag_mode == "wiki":
        # Wiki mode: return the wiki pages sourced from this document
        from app.models.wiki_page import WikiPage
        wiki_result = await db.execute(
            select(WikiPage).where(
                WikiPage.kb_id == document.kb_id,
            ).order_by(WikiPage.title)
        )
        all_wiki_pages = wiki_result.scalars().all()
        doc_id_str = str(doc_id)
        # Filter to pages that list this document as a source
        doc_pages = [
            p for p in all_wiki_pages
            if doc_id_str in (p.source_doc_ids or [])
        ]
        return {
            "doc_id": str(doc_id),
            "kb_id": str(document.kb_id),
            "rag_mode": "wiki",
            "wiki_page_count": len(doc_pages),
            "wiki_pages": [
                {
                    "id": str(p.id),
                    "title": p.title,
                    "summary": p.summary,
                    "page_type": p.page_type,
                    "source_doc_count": len(p.source_doc_ids or []),
                    "related_titles": list(p.related_titles or []),
                    "updated_at": p.updated_at.isoformat() if p.updated_at else "",
                }
                for p in doc_pages
            ],
        }

    if rag_mode == "vector":
        # Return chunk-based insights for Vector RAG documents
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = chunks_result.scalars().all()

        embedded_count = sum(1 for c in chunks if c.embedding is not None)
        pages = sorted({c.page_number for c in chunks if c.page_number})

        return {
            "doc_id": str(doc_id),
            "kb_id": str(document.kb_id),
            "rag_mode": "vector",
            "chunk_count": len(chunks),
            "embedded_count": embedded_count,
            "page_count": len(pages),
            "chunks": [
                {
                    "id": str(c.id),
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "page_number": c.page_number,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "has_embedding": c.embedding is not None,
                    "metadata": c.chunk_metadata,
                }
                for c in chunks
            ],
        }

    # PageIndex: return tree-based insights
    tree_result = await db.execute(
        select(DocumentTree).where(DocumentTree.document_id == doc_id)
    )
    tree = tree_result.scalar_one_or_none()

    if tree is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Document insights not found"}},
        )

    return {
        "doc_id": str(doc_id),
        "kb_id": str(document.kb_id),
        "rag_mode": "pageindex",
        "executive_summary": tree.executive_summary,
        "key_entities": tree.key_entities,
        "document_tags": tree.document_tags,
        "complexity_score": tree.complexity_score,
        "tree_json": tree.tree_json,
    }
