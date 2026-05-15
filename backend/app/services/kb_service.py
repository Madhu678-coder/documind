"""KnowledgeBase service layer — workspace isolation, CRUD, guards."""
import uuid
import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


async def get_kb_or_403(
    kb_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> KnowledgeBase:
    """Fetch a KB and verify it belongs to the given workspace. Raises 403 otherwise."""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None or kb.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="KnowledgeBase not found in your workspace.")
    return kb


async def assert_unique_name(
    name: str,
    workspace_id: uuid.UUID,
    db: AsyncSession,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    """Raise HTTP 409 if a KB with the same name already exists in the workspace."""
    q = select(KnowledgeBase).where(
        KnowledgeBase.workspace_id == workspace_id,
        KnowledgeBase.name == name,
    )
    if exclude_id is not None:
        q = q.where(KnowledgeBase.id != exclude_id)
    result = await db.execute(q)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A KnowledgeBase named '{name}' already exists in this workspace.",
        )


async def get_document_count(kb_id: uuid.UUID, db: AsyncSession) -> int:
    """Return the count of documents associated with a KB."""
    result = await db.execute(
        select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
    )
    return result.scalar_one()


async def assert_no_active_sessions(kb_id: uuid.UUID, db: AsyncSession) -> None:
    """Raise HTTP 409 if there are active chat sessions linked to this KB."""
    result = await db.execute(
        select(func.count()).select_from(ChatSession).where(ChatSession.kb_id == kb_id)
    )
    count = result.scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete KnowledgeBase: {count} active chat session(s) are linked to it.",
        )
