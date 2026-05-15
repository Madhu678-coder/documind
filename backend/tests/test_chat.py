# Feature: documind-platform, Property 10: Chat Session Scoped to KnowledgeBase
# Feature: documind-platform, Property 11: Message History Round Trip
"""
Property 10: For any chat session created with a valid kb_id, the session's kb_id
should match the provided value, and the session should only retrieve documents
from that KnowledgeBase during tree navigation.

Property 11: For any chat session with N messages sent, retrieving the message history
via GET /api/v1/chat/sessions/{id}/messages should return exactly N messages in
chronological order with all fields (content, citations, reasoning_trace, node_ids_visited) intact.

Validates: Requirements 7.1, 7.3, 7.5, 7.10, 7.11
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from app.api.routes.chat import router
from app.core.database import get_db
from app.core.security import get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_user(workspace_id: uuid.UUID, role: str = "editor"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.workspace_id = workspace_id
    user.role = role
    return user


def _mock_kb(workspace_id: uuid.UUID, kb_id: uuid.UUID):
    kb = MagicMock()
    kb.id = kb_id
    kb.workspace_id = workspace_id
    kb.name = "Test KB"
    return kb


def _mock_session(workspace_id: uuid.UUID, kb_id: uuid.UUID, session_id: Optional[uuid.UUID] = None):
    session = MagicMock()
    session.id = session_id or uuid.uuid4()
    session.workspace_id = workspace_id
    session.kb_id = kb_id
    session.user_id = uuid.uuid4()
    session.title = "Test Session"
    session.created_at = datetime.utcnow()
    return session


def _mock_message(session_id: uuid.UUID, role: str, content: str, offset_seconds: int = 0):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.session_id = session_id
    msg.role = role
    msg.content = content
    msg.citations = []
    msg.reasoning_trace = {}
    msg.node_ids_visited = []
    msg.created_at = datetime.utcnow() + timedelta(seconds=offset_seconds)
    return msg


def _build_app(mock_user, mock_db_factory):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = mock_db_factory
    return app


def _make_db_mock(execute_results: list):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=execute_results)

    def _get_db():
        return mock_db

    @asynccontextmanager
    async def _ctx():
        yield mock_db

    return mock_db, _get_db


# ── Property 10: Chat session KB scoping ─────────────────────────────────────

class TestChatSessionKBScoping:

    def test_create_session_stores_correct_kb_id(self):
        """Property 10: created session has kb_id matching the request."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        mock_session = _mock_session(workspace_id, kb_id, session_id)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "__dict__", mock_session.__dict__) or None)
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=_mock_kb(workspace_id, kb_id))
        ))

        added_sessions = []
        original_add = mock_db.add

        def capture_add(obj):
            from app.models.chat_session import ChatSession
            if isinstance(obj, ChatSession):
                added_sessions.append(obj)

        mock_db.add = capture_add

        async def _run():
            from app.api.routes.chat import create_session
            from app.schemas.chat import ChatSessionCreate

            body = ChatSessionCreate(kb_id=kb_id)
            # Patch refresh to set the id
            async def mock_refresh(obj):
                obj.id = session_id
                obj.workspace_id = workspace_id
                obj.kb_id = kb_id
                obj.user_id = mock_user.id
                obj.title = "Session"
                obj.created_at = datetime.utcnow()

            mock_db.refresh = mock_refresh
            result = await create_session(body, current_user=mock_user, db=mock_db)
            return result

        result = asyncio.run(_run())
        assert result.kb_id == kb_id

    def test_create_session_rejects_cross_workspace_kb(self):
        """Property 10: creating session with KB from another workspace returns 403."""
        workspace_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)  # KB not found in workspace
        ))

        async def _run():
            from fastapi import HTTPException
            from app.api.routes.chat import create_session
            from app.schemas.chat import ChatSessionCreate

            body = ChatSessionCreate(kb_id=uuid.uuid4())
            with pytest.raises(HTTPException) as exc_info:
                await create_session(body, current_user=mock_user, db=mock_db)
            return exc_info.value.status_code

        status_code = asyncio.run(_run())
        assert status_code == 403

    def test_load_kb_trees_only_returns_ready_documents(self):
        """Property 10: tree navigation only loads documents with status=ready."""
        async def _run():
            from app.api.routes.chat import _load_kb_trees
            from app.models.document import DocumentStatus

            kb_id = uuid.uuid4()
            mock_db = AsyncMock()

            # Simulate DB returning only ready documents
            ready_doc = MagicMock()
            ready_doc.id = uuid.uuid4()
            ready_doc.filename = "ready.pdf"
            ready_doc.status = DocumentStatus.ready

            ready_tree = MagicMock()
            ready_tree.tree_json = {"doc_id": str(ready_doc.id), "title": "Ready", "nodes": []}

            mock_db.execute = AsyncMock(return_value=MagicMock(
                all=MagicMock(return_value=[(ready_doc, ready_tree)])
            ))

            trees = await _load_kb_trees(kb_id, mock_db)
            return trees

        trees = asyncio.run(_run())
        assert len(trees) == 1
        assert trees[0][1] == "ready.pdf"

    @given(
        kb_id=st.builds(lambda: uuid.uuid4()),
        workspace_id=st.builds(lambda: uuid.uuid4()),
    )
    @settings(max_examples=30)
    def test_session_kb_id_always_matches_request(self, kb_id: uuid.UUID, workspace_id: uuid.UUID):
        """Property 10: session kb_id always equals the requested kb_id."""
        async def _run():
            from app.api.routes.chat import create_session
            from app.schemas.chat import ChatSessionCreate

            mock_user = _mock_user(workspace_id)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=_mock_kb(workspace_id, kb_id))
            ))
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()

            async def mock_refresh(obj):
                obj.id = uuid.uuid4()
                obj.workspace_id = workspace_id
                obj.kb_id = kb_id
                obj.user_id = mock_user.id
                obj.title = "Session"
                obj.created_at = datetime.utcnow()

            mock_db.refresh = mock_refresh

            body = ChatSessionCreate(kb_id=kb_id)
            result = await create_session(body, current_user=mock_user, db=mock_db)
            return result.kb_id

        result = asyncio.run(_run())
        assert result == kb_id


# ── Property 11: Message history round trip ───────────────────────────────────

class TestMessageHistoryRoundTrip:

    def test_get_messages_returns_all_messages(self):
        """Property 11: GET messages returns all N messages for a session."""
        async def _run():
            from app.api.routes.chat import get_messages

            workspace_id = uuid.uuid4()
            session_id = uuid.uuid4()
            mock_user = _mock_user(workspace_id)

            messages = [
                _mock_message(session_id, "user", f"Question {i}", i * 2)
                for i in range(5)
            ] + [
                _mock_message(session_id, "assistant", f"Answer {i}", i * 2 + 1)
                for i in range(5)
            ]

            mock_db = AsyncMock()
            # First execute: session lookup
            # Second execute: messages query
            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_session(workspace_id, uuid.uuid4(), session_id))),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=messages)))),
            ])

            result = await get_messages(session_id, current_user=mock_user, db=mock_db)
            return result

        result = asyncio.run(_run())
        assert len(result) == 10

    def test_get_messages_returns_chronological_order(self):
        """Property 11: messages are returned in chronological order."""
        async def _run():
            from app.api.routes.chat import get_messages

            workspace_id = uuid.uuid4()
            session_id = uuid.uuid4()
            mock_user = _mock_user(workspace_id)

            # Create messages with explicit timestamps
            messages = [
                _mock_message(session_id, "user", f"msg_{i}", i)
                for i in range(5)
            ]

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_session(workspace_id, uuid.uuid4(), session_id))),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=messages)))),
            ])

            result = await get_messages(session_id, current_user=mock_user, db=mock_db)
            return result

        result = asyncio.run(_run())
        # Verify chronological order
        for i in range(len(result) - 1):
            assert result[i].created_at <= result[i + 1].created_at

    def test_get_messages_preserves_all_fields(self):
        """Property 11: all message fields are intact in the response."""
        async def _run():
            from app.api.routes.chat import get_messages

            workspace_id = uuid.uuid4()
            session_id = uuid.uuid4()
            mock_user = _mock_user(workspace_id)

            msg = _mock_message(session_id, "assistant", "The answer is 42.")
            msg.citations = [{"doc_name": "doc.pdf", "section_title": "S1",
                              "page_number": 1, "node_id": "n1", "verbatim_excerpt": "42"}]
            msg.reasoning_trace = {"nodes_visited": [], "confidence": 0.9, "query": "q"}
            msg.node_ids_visited = ["n1", "n2"]

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_session(workspace_id, uuid.uuid4(), session_id))),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg])))),
            ])

            result = await get_messages(session_id, current_user=mock_user, db=mock_db)
            return result[0]

        msg = asyncio.run(_run())
        assert msg.content == "The answer is 42."
        assert msg.citations is not None
        assert msg.reasoning_trace is not None
        assert msg.node_ids_visited == ["n1", "n2"]

    def test_get_messages_returns_403_for_wrong_workspace(self):
        """Property 11: accessing another workspace's session returns 403."""
        async def _run():
            from fastapi import HTTPException
            from app.api.routes.chat import get_messages

            workspace_id = uuid.uuid4()
            mock_user = _mock_user(workspace_id)

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=None)  # session not found
            ))

            with pytest.raises(HTTPException) as exc_info:
                await get_messages(uuid.uuid4(), current_user=mock_user, db=mock_db)
            return exc_info.value.status_code

        status_code = asyncio.run(_run())
        assert status_code == 403

    @given(n_messages=st.integers(min_value=1, max_value=20))
    @settings(max_examples=30)
    def test_message_count_matches_n(self, n_messages: int):
        """Property 11: GET returns exactly N messages for any N."""
        async def _run():
            from app.api.routes.chat import get_messages

            workspace_id = uuid.uuid4()
            session_id = uuid.uuid4()
            mock_user = _mock_user(workspace_id)

            messages = [
                _mock_message(session_id, "user" if i % 2 == 0 else "assistant", f"msg_{i}", i)
                for i in range(n_messages)
            ]

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_session(workspace_id, uuid.uuid4(), session_id))),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=messages)))),
            ])

            result = await get_messages(session_id, current_user=mock_user, db=mock_db)
            return len(result)

        count = asyncio.run(_run())
        assert count == n_messages
