import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
