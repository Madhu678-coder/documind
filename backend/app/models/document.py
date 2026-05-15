import enum
import uuid
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id"))
    filename: Mapped[str]
    file_path: Mapped[str]
    file_type: Mapped[str]
    size_bytes: Mapped[int]
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.uploading)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
