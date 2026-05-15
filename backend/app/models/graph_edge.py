"""GraphEdge model — stores relationships between entities for GraphRAG."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Float, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(Text(), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    weight: Mapped[float] = mapped_column(Float(), nullable=False, default=1.0)
    source_doc_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
