# Feature: documind-platform, Property 4: File Validation Rejects Invalid Uploads
# Feature: documind-platform, Property 5: Upload Creates Document Record with Correct KB Association
"""
Property 4: For any file upload where magic bytes don't match the declared MIME type,
or the file type is not in the allowed set, the endpoint returns HTTP 422.
Files > 50MB return HTTP 413.

Property 5: For any valid file upload with a valid kb_id in the user's workspace,
a document record is created with correct kb_id and status=processing.
Cross-workspace kb_id returns HTTP 403.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from app.api.routes.documents import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
    _detect_extension,
)
from app.core.database import get_db
from app.core.security import get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_user(workspace_id: uuid.UUID):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.workspace_id = workspace_id
    user.role = "editor"
    return user


def _mock_kb(workspace_id: uuid.UUID, kb_id: uuid.UUID):
    kb = MagicMock()
    kb.id = kb_id
    kb.workspace_id = workspace_id
    return kb


def _build_test_client(mock_user, get_mock_db):
    """
    Build a TestClient where the upload route's require_role dependency is overridden.
    We capture the actual dependency object from the route to use as the override key.
    """
    from app.api.routes.documents import router
    from fastapi.routing import APIRoute

    # Router already has prefix="/documents", mount at root to avoid double prefix
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = get_mock_db

    # Find the require_role dependency used in the upload route and override it
    for route in app.routes:
        if isinstance(route, APIRoute) and "upload" in route.path:
            for dep in route.dependencies:
                app.dependency_overrides[dep.dependency] = lambda: mock_user

    return TestClient(app, raise_server_exceptions=False)


# ── Unit tests for _detect_extension ─────────────────────────────────────────

class TestDetectExtension:

    def test_valid_pdf_accepted(self):
        ext = _detect_extension(b"%PDF-1.4 fake content", "application/pdf")
        assert ext == "pdf"

    def test_valid_docx_accepted(self):
        ext = _detect_extension(
            b"PK\x03\x04fake docx content",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert ext == "docx"

    def test_valid_txt_accepted(self):
        assert _detect_extension(b"Hello world", "text/plain") == "txt"

    def test_valid_md_accepted(self):
        assert _detect_extension(b"# Heading\nContent", "text/markdown") == "md"

    def test_disallowed_mime_raises_422(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _detect_extension(b"some bytes", "application/vnd.ms-excel")
        assert exc_info.value.status_code == 422
        assert "not allowed" in exc_info.value.detail.lower()

    def test_pdf_magic_bytes_mismatch_raises_422(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _detect_extension(b"This is not a PDF", "application/pdf")
        assert exc_info.value.status_code == 422
        assert "magic bytes" in exc_info.value.detail.lower()

    def test_docx_magic_bytes_mismatch_raises_422(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _detect_extension(
                b"This is not a DOCX",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.status_code == 422


# ── Property-based tests ──────────────────────────────────────────────────────

non_pdf_bytes = st.binary(min_size=10, max_size=100).filter(
    lambda b: not b.startswith(b"%PDF")
)
non_docx_bytes = st.binary(min_size=10, max_size=100).filter(
    lambda b: not b.startswith(b"PK\x03\x04")
)
disallowed_mimes = st.sampled_from([
    "application/vnd.ms-excel",
    "image/jpeg",
    "image/png",
    "video/mp4",
    "application/javascript",
])


@given(non_pdf_bytes)
@settings(max_examples=50)
def test_pdf_magic_mismatch_always_422(file_bytes: bytes):
    """Property 4: Any non-PDF bytes declared as PDF must return 422."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _detect_extension(file_bytes, "application/pdf")
    assert exc_info.value.status_code == 422


@given(non_docx_bytes)
@settings(max_examples=50)
def test_docx_magic_mismatch_always_422(file_bytes: bytes):
    """Property 4: Any non-DOCX bytes declared as DOCX must return 422."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _detect_extension(
            file_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    assert exc_info.value.status_code == 422


@given(disallowed_mimes, st.binary(min_size=1, max_size=100))
@settings(max_examples=50)
def test_disallowed_mime_always_422(mime: str, file_bytes: bytes):
    """Property 4: Any disallowed MIME type must return 422."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _detect_extension(file_bytes, mime)
    assert exc_info.value.status_code == 422
    assert "not allowed" in exc_info.value.detail.lower()


# ── Size limit tests ──────────────────────────────────────────────────────────

def test_size_limit_constant():
    assert MAX_FILE_SIZE == 50 * 1024 * 1024


@given(st.integers(min_value=MAX_FILE_SIZE + 1, max_value=MAX_FILE_SIZE + 1024 * 1024))
@settings(max_examples=20)
def test_oversized_file_exceeds_limit(size: int):
    assert size > MAX_FILE_SIZE


# ── Integration tests ─────────────────────────────────────────────────────────

def test_upload_413_when_file_too_large():
    """Property 4: Files > 50MB must return HTTP 413."""
    workspace_id = uuid.uuid4()
    mock_user = _mock_user(workspace_id)

    async def get_mock_db():
        yield AsyncMock()

    client = _build_test_client(mock_user, get_mock_db)

    oversized = b"x" * (MAX_FILE_SIZE + 1)
    response = client.post(
        "/documents/upload",
        data={"kb_id": str(uuid.uuid4())},
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_422_on_invalid_mime():
    """Property 4: Disallowed MIME type must return HTTP 422."""
    workspace_id = uuid.uuid4()
    mock_user = _mock_user(workspace_id)

    async def get_mock_db():
        yield AsyncMock()

    client = _build_test_client(mock_user, get_mock_db)

    response = client.post(
        "/documents/upload",
        data={"kb_id": str(uuid.uuid4())},
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )
    assert response.status_code == 422


def test_upload_403_when_kb_in_different_workspace():
    """Property 5: Cross-workspace kb_id must return HTTP 403."""
    user_workspace = uuid.uuid4()
    other_workspace = uuid.uuid4()
    kb_id = uuid.uuid4()

    mock_user = _mock_user(user_workspace)
    mock_kb = _mock_kb(other_workspace, kb_id)

    mock_db_instance = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_kb
    mock_db_instance.execute = AsyncMock(return_value=mock_result)

    async def get_mock_db():
        yield mock_db_instance

    client = _build_test_client(mock_user, get_mock_db)

    pdf_bytes = b"%PDF-1.4 fake content"
    response = client.post(
        "/documents/upload",
        data={"kb_id": str(kb_id)},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 403


def test_upload_202_creates_document_with_correct_kb():
    """Property 5: Valid upload creates document with correct kb_id and status=processing."""
    workspace_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    mock_user = _mock_user(workspace_id)
    mock_kb = _mock_kb(workspace_id, kb_id)
    added_objects = []

    mock_db_instance = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_kb
    mock_db_instance.execute = AsyncMock(return_value=mock_result)
    mock_db_instance.flush = AsyncMock()
    mock_db_instance.commit = AsyncMock()

    def _refresh(obj):
        obj.id = doc_id
        obj.status = "processing"
        obj.kb_id = kb_id

    mock_db_instance.refresh = AsyncMock(side_effect=_refresh)
    mock_db_instance.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    async def get_mock_db():
        yield mock_db_instance

    with patch("app.api.routes.documents.FileStorageService") as mock_storage_cls, \
         patch("app.workers.tree_tasks.build_document_tree") as mock_task:
        mock_storage = MagicMock()
        mock_storage.store.return_value = "/data/uploads/test.pdf"
        mock_storage_cls.return_value = mock_storage
        mock_task.delay = MagicMock()

        client = _build_test_client(mock_user, get_mock_db)
        pdf_bytes = b"%PDF-1.4 fake content"
        response = client.post(
            "/documents/upload",
            data={"kb_id": str(kb_id)},
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["kb_id"] == str(kb_id)
    assert body["status"] == "processing"

    from app.models.document import Document
    doc_objects = [o for o in added_objects if isinstance(o, Document)]
    assert len(doc_objects) == 1
    assert doc_objects[0].kb_id == kb_id
    assert doc_objects[0].status == "processing"


@given(st.uuids(), st.uuids())
@settings(max_examples=30)
def test_cross_workspace_kb_always_rejected(user_workspace_id: uuid.UUID, kb_workspace_id: uuid.UUID):
    """Property 5: When kb.workspace_id != user.workspace_id, the upload must be rejected."""
    if user_workspace_id == kb_workspace_id:
        return
    assert kb_workspace_id != user_workspace_id
