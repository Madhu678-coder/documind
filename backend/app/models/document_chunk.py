"""DocumentChunk model for vector RAG chunked document storage."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

try:
    from pgvector.sqlalchemy import Vector
    _VECTOR_AVAILABLE = True
except ImportError:
    from sqlalchemy import String as Vector  # type: ignore[assignment]  # fallback
    _VECTOR_AVAILABLE = False


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int]
    text: Mapped[str]
    char_start: Mapped[int] = mapped_column(default=0)
    char_end: Mapped[int] = mapped_column(default=0)
    page_number: Mapped[int] = mapped_column(default=1)
    parent_chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(1024) if _VECTOR_AVAILABLE else Text(),  # type: ignore[arg-type]
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
