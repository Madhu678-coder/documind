import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    resource_type: Mapped[str]
    resource_id: Mapped[uuid.UUID]
    log_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)
