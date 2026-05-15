import uuid
from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str]
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
