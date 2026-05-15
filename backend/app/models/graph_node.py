"""GraphNode model — stores entities extracted from documents for GraphRAG."""
from __future__ import annotations

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
    from sqlalchemy import String as Vector  # type: ignore[assignment]
    _VECTOR_AVAILABLE = False


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text(), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    source_doc_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    mention_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(1024) if _VECTOR_AVAILABLE else Text(),  # type: ignore[arg-type]
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
