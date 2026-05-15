"""Retrieval hit-testing endpoint for Vector RAG KBs."""
from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


class RetrievalTestRequest(BaseModel):
    kb_id: uuid.UUID
    query: str


class RetrievalResultOut(BaseModel):
    chunk_id: str
    document_id: str
    doc_filename: str
    text: str
    score: float
    page_number: int
    chunk_index: int


class RetrievalTestResponse(BaseModel):
    chunks: list[RetrievalResultOut]
    retrieval_mode: str
    kb_rag_mode: str


@router.post("/test", response_model=RetrievalTestResponse)
async def test_retrieval(
    body: RetrievalTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run retrieval for a KB and return the top chunks without generating an answer.
    Only available for KBs with rag_mode == 'vector'.
    """
    # Load and validate KB
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == body.kb_id,
            KnowledgeBase.workspace_id == current_user.workspace_id,
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found in your workspace.",
        )

    kb_settings = kb.settings or {}
    rag_mode = kb_settings.get("rag_mode", "pageindex")

    if rag_mode != "vector":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retrieval testing is only available for knowledge bases using Vector RAG mode.",
        )

    if not body.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query cannot be empty.",
        )

    try:
        from app.services.embedding.factory import EmbeddingFactory
        from app.services.retrieval.factory import RetrieverFactory

        emb = EmbeddingFactory.create(
            kb_settings.get("embedding_provider", "bedrock"),
            kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
        )
        retriever = RetrieverFactory.create(kb_settings, emb)
        chunks = await retriever.retrieve(body.query, body.kb_id, current_user.workspace_id, db)

        return RetrievalTestResponse(
            chunks=[
                RetrievalResultOut(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    doc_filename=c.doc_filename,
                    text=c.text,
                    score=c.score,
                    page_number=c.page_number,
                    chunk_index=c.chunk_index,
                )
                for c in chunks
            ],
            retrieval_mode=kb_settings.get("retrieval_mode", "vector"),
            kb_rag_mode=rag_mode,
        )

    except Exception as exc:
        logger.exception("Retrieval test failed", extra={"kb_id": str(body.kb_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Retrieval failed: {exc}",
        )
