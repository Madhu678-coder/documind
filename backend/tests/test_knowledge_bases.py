# Feature: documind-platform, Property 25: KnowledgeBase document_count Invariant
# Feature: documind-platform, Property 26: KnowledgeBase Creation Sets Correct Ownership
# Feature: documind-platform, Property 27: KnowledgeBase Deletion Blocked by Active Sessions
"""
Property 25: document_count in API responses always equals the DB count of documents
             with matching kb_id.

Property 26: KB creation sets workspace_id = user's workspace and created_by = user's ID.
             Duplicate names in the same workspace return HTTP 409.

Property 27: DELETE returns HTTP 409 when active chat sessions exist; succeeds otherwise.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from app.api.routes.knowledge_bases import router
from app.core.database import get_db
from app.core.security import get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_user(workspace_id: uuid.UUID, role: str = "admin"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.workspace_id = workspace_id
    user.role = role
    return user


def _mock_kb(workspace_id: uuid.UUID, kb_id: uuid.UUID, name: str = "Test KB"):
    kb = MagicMock()
    kb.id = kb_id
    kb.workspace_id = workspace_id
    kb.name = name
    kb.description = None
    kb.created_by = uuid.uuid4()
    kb.settings = {}
    from datetime import datetime
    kb.created_at = datetime.utcnow()
    return kb


def _build_client(mock_user, get_mock_db):
    from fastapi.routing import APIRoute

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = get_mock_db

    # Override all require_role dependencies
    for route in app.routes:
        if isinstance(route, APIRoute):
            for dep in route.dependencies:
                app.dependency_overrides[dep.dependency] = lambda: mock_user

    return TestClient(app, raise_server_exceptions=False)


# ── Property 25: document_count invariant ─────────────────────────────────────

class TestDocumentCountInvariant:

    def test_empty_kb_has_zero_document_count(self):
        """P25: A newly created KB with no documents must report document_count=0."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        mock_kb = _mock_kb(workspace_id, kb_id)

        mock_db = AsyncMock()

        # execute for duplicate name check → no existing KB
        # execute for list query → returns the KB
        # execute for document count → 0
        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # duplicate name check
                result.scalar_one_or_none.return_value = None
            elif call_count[0] == 2:
                # document count
                result.scalar_one.return_value = 0
            return result

        mock_db.execute = mock_execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", kb_id) or
                                    setattr(obj, "created_at", mock_kb.created_at) or
                                    setattr(obj, "created_by", mock_user.id))

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.post("/knowledge-bases", json={"name": "My KB"})
        assert response.status_code == 201
        assert response.json()["document_count"] == 0

    @given(st.integers(min_value=0, max_value=100))
    @settings(max_examples=30)
    def test_document_count_matches_db_count(self, db_count: int):
        """P25: API-returned document_count always equals the DB count."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        mock_kb = _mock_kb(workspace_id, kb_id)

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # list KBs query
                result.scalars.return_value.all.return_value = [mock_kb]
            elif call_count[0] == 2:
                # document count for the KB
                result.scalar_one.return_value = db_count
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.get("/knowledge-bases")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["document_count"] == db_count


# ── Property 26: KB creation ownership ───────────────────────────────────────

class TestKBCreationOwnership:

    def test_created_kb_has_correct_workspace_and_owner(self):
        """P26: workspace_id and created_by are set from the JWT user."""
        workspace_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        kb_id = uuid.uuid4()

        from datetime import datetime
        created_at = datetime.utcnow()

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = None  # no duplicate
            elif call_count[0] == 2:
                result.scalar_one.return_value = 0  # doc count
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        def _refresh(obj):
            obj.id = kb_id
            obj.workspace_id = workspace_id
            obj.created_by = mock_user.id
            obj.created_at = created_at
            obj.settings = {}

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.post("/knowledge-bases", json={"name": "Owned KB"})
        assert response.status_code == 201
        body = response.json()
        assert body["workspace_id"] == str(workspace_id)
        assert body["created_by"] == str(mock_user.id)

    def test_duplicate_name_in_same_workspace_returns_409(self):
        """P26: Creating a KB with a duplicate name in the same workspace returns HTTP 409."""
        workspace_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        existing_kb = _mock_kb(workspace_id, uuid.uuid4(), name="Duplicate")

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing_kb
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.post("/knowledge-bases", json={"name": "Duplicate"})
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=30)
    def test_duplicate_name_always_409(self, name: str):
        """P26: Any duplicate name in the same workspace always returns 409."""
        workspace_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        existing_kb = _mock_kb(workspace_id, uuid.uuid4(), name=name)

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing_kb
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.post("/knowledge-bases", json={"name": name})
        assert response.status_code == 409

    def test_same_name_in_different_workspace_is_allowed(self):
        """P26: Same name in a different workspace should not conflict."""
        workspace_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id)
        kb_id = uuid.uuid4()

        from datetime import datetime
        created_at = datetime.utcnow()

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # No duplicate in THIS workspace
                result.scalar_one_or_none.return_value = None
            elif call_count[0] == 2:
                result.scalar_one.return_value = 0
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        def _refresh(obj):
            obj.id = kb_id
            obj.workspace_id = workspace_id
            obj.created_by = mock_user.id
            obj.created_at = created_at
            obj.settings = {}

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.post("/knowledge-bases", json={"name": "Shared Name"})
        assert response.status_code == 201


# ── Property 27: KB deletion guard ───────────────────────────────────────────

class TestKBDeletionGuard:

    def _setup_delete_client(self, workspace_id, kb_id, session_count: int):
        mock_user = _mock_user(workspace_id, role="admin")
        mock_kb = _mock_kb(workspace_id, kb_id)

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # get_kb_or_403 lookup
                result.scalar_one_or_none.return_value = mock_kb
            elif call_count[0] == 2:
                # active session count
                result.scalar_one.return_value = session_count
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        async def get_mock_db():
            yield mock_db

        return _build_client(mock_user, get_mock_db), mock_db

    def test_delete_blocked_when_active_sessions_exist(self):
        """P27: DELETE returns HTTP 409 when active chat sessions are linked."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        client, _ = self._setup_delete_client(workspace_id, kb_id, session_count=3)

        response = client.delete(f"/knowledge-bases/{kb_id}")
        assert response.status_code == 409
        assert "active chat session" in response.json()["detail"].lower()

    def test_delete_succeeds_when_no_active_sessions(self):
        """P27: DELETE returns HTTP 204 when no active sessions exist."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        client, _ = self._setup_delete_client(workspace_id, kb_id, session_count=0)

        response = client.delete(f"/knowledge-bases/{kb_id}")
        assert response.status_code == 204

    def test_delete_403_for_wrong_workspace(self):
        """P27: DELETE returns HTTP 403 when KB is not in user's workspace."""
        workspace_id = uuid.uuid4()
        other_workspace = uuid.uuid4()
        kb_id = uuid.uuid4()
        mock_user = _mock_user(workspace_id, role="admin")

        # KB belongs to other_workspace
        mock_kb = _mock_kb(other_workspace, kb_id)

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_kb
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_client(mock_user, get_mock_db)
        response = client.delete(f"/knowledge-bases/{kb_id}")
        assert response.status_code == 403

    @given(st.integers(min_value=1, max_value=1000))
    @settings(max_examples=30)
    def test_any_active_session_count_blocks_deletion(self, session_count: int):
        """P27: Any positive session count must block deletion with 409."""
        workspace_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        client, _ = self._setup_delete_client(workspace_id, kb_id, session_count=session_count)

        response = client.delete(f"/knowledge-bases/{kb_id}")
        assert response.status_code == 409
