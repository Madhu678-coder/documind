"""OpenKBPage model — compiled wiki pages for the OpenKB RAG mode.

Table: openkb_pages

page_category values: summary | concept | entity | exploration | index
doc_type values     : short   | pageindex
source_data         : per-page JSON list for pageindex (long) documents
                      [{"page": 1, "content": "...", "images": [...]}, ...]
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OpenKBPage(Base):
    __tablename__ = "openkb_pages"

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

    # Unique merge key per KB.  Index page uses title="__index__".
    # Concept/entity pages use the sanitized slug as title.
    title: Mapped[str] = mapped_column(Text(), nullable=False)

    # Page category: summary | concept | entity | exploration | index
    page_category: Mapped[str] = mapped_column(
        Text(), nullable=False, default="concept", server_default="concept"
    )

    # Page type:
    #   - entity → person / organization / place / product / work / event / other
    #   - others → mirrors page_category
    page_type: Mapped[str] = mapped_column(
        Text(), nullable=False, default="concept", server_default="concept"
    )

    # "short" (< threshold pages) | "pageindex" (>= threshold pages)
    doc_type: Mapped[Optional[str]] = mapped_column(Text(), nullable=True, server_default="short")

    # One-liner description (OpenKB's "description" frontmatter field)
    summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    # Full Markdown body (for short docs: full source text in summary pages;
    # for long docs / pageindex: tree structure summary)
    content: Mapped[str] = mapped_column(Text(), nullable=False)

    # Per-page JSON for pageindex documents.
    # [{"page": int, "content": str, "images": [{"path": str}]}]
    # Populated only on summary pages for long docs.
    source_data: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Document UUIDs (as strings) that contributed to this page
    source_doc_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Titles of related pages (for wikilink graph and cross-reference display)
    related_titles: Mapped[list] = mapped_column(
        ARRAY(Text()), nullable=False, default=list, server_default="{}"
    )

    llm_model_used: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
