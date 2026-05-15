"""Pydantic schemas for KnowledgeBase CRUD."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, computed_field


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    document_count: int = 0
    settings: Optional[dict[str, Any]] = None

    @computed_field  # type: ignore[misc]
    @property
    def rag_mode(self) -> str:
        if self.settings:
            return self.settings.get("rag_mode", "pageindex")
        return "pageindex"

    model_config = {"from_attributes": True}


class KnowledgeBaseDetail(KnowledgeBaseOut):
    documents: list[dict[str, Any]] = []
