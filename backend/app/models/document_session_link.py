import uuid
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DocumentSessionLink(Base):
    __tablename__ = "document_session_links"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
