"""ModelProviderConfig model for storing LLM/embedding/rerank provider settings."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModelProviderConfig(Base):
    __tablename__ = "model_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    provider_type: Mapped[str]   # 'llm', 'embedding', 'rerank'
    provider_name: Mapped[str]   # 'bedrock', 'openai', 'cohere'
    model_id: Mapped[str]
    api_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    region: Mapped[Optional[str]] = mapped_column(nullable=True)
    extra_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
