import enum
import uuid
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    hashed_password: Mapped[str]
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.viewer)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
