"""Pydantic schemas for chat sessions and messages."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class ChatSessionCreate(BaseModel):
    kb_id: uuid.UUID
    title: Optional[str] = None


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    content: str


class CitationOut(BaseModel):
    doc_name: str
    section_title: str
    page_number: int
    node_id: str
    verbatim_excerpt: str


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    citations: Optional[list[dict[str, Any]]] = None
    reasoning_trace: Optional[dict[str, Any]] = None
    node_ids_visited: Optional[list[str]] = None
    created_at: datetime

    model_config = {"from_attributes": True}
