import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DocumentTree(Base):
    __tablename__ = "document_trees"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    tree_json: Mapped[dict] = mapped_column(JSONB)
    built_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    llm_model_used: Mapped[str]
    token_count: Mapped[int]
    executive_summary: Mapped[Optional[str]]
    key_entities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    document_tags: Mapped[Optional[list]] = mapped_column(ARRAY(String), nullable=True)
    complexity_score: Mapped[Optional[float]]
