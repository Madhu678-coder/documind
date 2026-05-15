import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str]
    content: Mapped[str]
    citations: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    reasoning_trace: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    node_ids_visited: Mapped[Optional[list]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
