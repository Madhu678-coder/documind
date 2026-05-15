# Feature: documind-platform, Property 1: Workspace Isolation
"""
Property 1: For any two users belonging to different workspaces, a query made by
user A should never return documents, KnowledgeBases, chat sessions, or messages
that belong to user B's workspace.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from app.api.routes.documents import router as documents_router
from app.api.routes.knowledge_bases import router as kb_router
from app.core.database import get_db
from app.core.security import get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_user(workspace_id: uuid.UUID, role: str = "viewer"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.workspace_id = workspace_id
    user.role = role
    return user


def _mock_kb(workspace_id: uuid.UUID):
    kb = MagicMock()
    kb.id = uuid.uuid4()
    kb.workspace_id = workspace_id
    kb.name = "KB"
    kb.description = None
    kb.created_by = uuid.uuid4()
    kb.settings = {}
    from datetime import datetime
    kb.created_at = datetime.utcnow()
    return kb


def _mock_doc(workspace_id: uuid.UUID, kb_id: uuid.UUID):
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.workspace_id = workspace_id
    doc.kb_id = kb_id
    doc.filename = "doc.pdf"
    doc.file_type = "pdf"
    doc.size_bytes = 1024
    doc.status = "ready"
    doc.uploaded_by = uuid.uuid4()
    from datetime import datetime
    doc.created_at = datetime.utcnow()
    return doc


def _build_app(mock_user, get_mock_db):
    from fastapi.routing import APIRoute

    app = FastAPI()
    app.include_router(kb_router)
    app.include_router(documents_router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = get_mock_db

    for route in app.routes:
        if isinstance(route, APIRoute):
            for dep in route.dependencies:
                app.dependency_overrides[dep.dependency] = lambda: mock_user

    return TestClient(app, raise_server_exceptions=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWorkspaceIsolation:

    def test_kb_list_only_returns_own_workspace_kbs(self):
        """P1: GET /knowledge-bases only returns KBs from the user's workspace."""
        workspace_a = uuid.uuid4()
        workspace_b = uuid.uuid4()

        user_a = _mock_user(workspace_a)
        kb_a = _mock_kb(workspace_a)
        kb_b = _mock_kb(workspace_b)  # belongs to workspace B

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # list KBs — only return workspace_a KB (simulating WHERE workspace_id = workspace_a)
                result.scalars.return_value.all.return_value = [kb_a]
            else:
                result.scalar_one.return_value = 0
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        response = client.get("/knowledge-bases")
        assert response.status_code == 200
        data = response.json()
        # Only workspace_a's KB should appear
        assert all(item["workspace_id"] == str(workspace_a) for item in data)
        assert not any(item["workspace_id"] == str(workspace_b) for item in data)

    def test_kb_from_other_workspace_returns_403(self):
        """P1: Accessing a KB from another workspace returns HTTP 403."""
        workspace_a = uuid.uuid4()
        workspace_b = uuid.uuid4()

        user_a = _mock_user(workspace_a)
        kb_b = _mock_kb(workspace_b)  # belongs to workspace B

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb_b
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        response = client.get(f"/knowledge-bases/{kb_b.id}")
        assert response.status_code == 403

    def test_documents_list_only_returns_own_workspace_docs(self):
        """P1: GET /documents only returns documents from the user's workspace."""
        workspace_a = uuid.uuid4()
        workspace_b = uuid.uuid4()

        user_a = _mock_user(workspace_a)
        kb_a = _mock_kb(workspace_a)
        doc_a = _mock_doc(workspace_a, kb_a.id)

        async def mock_execute(query):
            result = MagicMock()
            # Simulates WHERE workspace_id = workspace_a — only doc_a returned
            result.scalars.return_value.all.return_value = [doc_a]
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        response = client.get("/documents")
        assert response.status_code == 200
        data = response.json()
        assert all(item["workspace_id"] == str(workspace_a) for item in data)
        assert not any(item["workspace_id"] == str(workspace_b) for item in data)

    def test_upload_to_cross_workspace_kb_returns_403(self):
        """P1: Uploading a document to a KB in another workspace returns HTTP 403."""
        workspace_a = uuid.uuid4()
        workspace_b = uuid.uuid4()

        user_a = _mock_user(workspace_a, role="editor")
        kb_b = _mock_kb(workspace_b)  # belongs to workspace B

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb_b
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        pdf_bytes = b"%PDF-1.4 fake content"
        response = client.post(
            "/documents/upload",
            data={"kb_id": str(kb_b.id)},
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 403

    def test_delete_kb_from_other_workspace_returns_403(self):
        """P1: Deleting a KB from another workspace returns HTTP 403."""
        workspace_a = uuid.uuid4()
        workspace_b = uuid.uuid4()

        user_a = _mock_user(workspace_a, role="admin")
        kb_b = _mock_kb(workspace_b)

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb_b
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        response = client.delete(f"/knowledge-bases/{kb_b.id}")
        assert response.status_code == 403

    @given(st.uuids(), st.uuids())
    @settings(max_examples=30)
    def test_cross_workspace_kb_access_always_403(
        self, workspace_a: uuid.UUID, workspace_b: uuid.UUID
    ):
        """P1: Cross-workspace KB access always returns 403 regardless of IDs."""
        if workspace_a == workspace_b:
            return

        user_a = _mock_user(workspace_a)
        kb_b = _mock_kb(workspace_b)

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb_b
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        response = client.get(f"/knowledge-bases/{kb_b.id}")
        assert response.status_code == 403

    @given(st.uuids(), st.uuids())
    @settings(max_examples=30)
    def test_cross_workspace_upload_always_403(
        self, workspace_a: uuid.UUID, workspace_b: uuid.UUID
    ):
        """P1: Uploading to a cross-workspace KB always returns 403."""
        if workspace_a == workspace_b:
            return

        user_a = _mock_user(workspace_a, role="editor")
        kb_b = _mock_kb(workspace_b)

        async def mock_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb_b
            return result

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def get_mock_db():
            yield mock_db

        client = _build_app(user_a, get_mock_db)
        pdf_bytes = b"%PDF-1.4 fake content"
        response = client.post(
            "/documents/upload",
            data={"kb_id": str(kb_b.id)},
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 403
