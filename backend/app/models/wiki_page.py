"""WikiPage model — stores LLM-maintained cross-document wiki pages for Wiki RAG mode."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WikiPage(Base):
    __tablename__ = "wiki_pages"

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
    # Title is the merge key — unique per KB (enforced in application layer, case-insensitive)
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    # entity | concept | process | event | general
    page_type: Mapped[str] = mapped_column(Text(), nullable=False, default="general", server_default="general")
    # List of document UUIDs (as strings) that contributed to this page
    source_doc_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Titles of related wiki pages (for cross-reference display)
    related_titles: Mapped[list] = mapped_column(ARRAY(Text()), nullable=False, default=list, server_default="{}")
    llm_model_used: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
